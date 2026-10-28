"""Run one bounded ClockPressure observation on the current host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.environment import snapshot_environment
from experiments.telemetry import sample_context

PROBE = ROOT / "build" / "clockpressure-probe"
WORKLOAD = ROOT / "experiments" / "workloads" / "cpu_pressure.py"
BPF_PROGRAM = ROOT / "instrumentation" / "sched_wakeup.bt"
PROTOCOL_VERSION = "initial-pilot-v1"


def _parse_cpus(value: str) -> list[int]:
    try:
        cpus = sorted({int(item.strip()) for item in value.split(",") if item.strip()})
    except ValueError as exc:
        raise argparse.ArgumentTypeError("CPU IDs must be comma-separated integers") from exc
    if not cpus or any(cpu < 0 for cpu in cpus):
        raise argparse.ArgumentTypeError("at least one non-negative CPU ID is required")
    return cpus


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return os.environ.get("CLOCKPRESSURE_REVISION")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _first_probe_metadata(path: Path, process: subprocess.Popen[bytes], timeout: float = 8) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with path.open("r", encoding="utf-8") as raw:
                for line in raw:
                    value = json.loads(line)
                    if value.get("kind") == "metadata":
                        return value
        except (OSError, json.JSONDecodeError):
            pass
        if process.poll() is not None:
            break
        time.sleep(0.025)
    raise RuntimeError(f"probe did not emit its metadata header (return code={process.poll()})")


def _stop_group(process: subprocess.Popen[bytes] | None, grace_seconds: float = 3) -> int | None:
    if process is None or process.poll() is not None:
        return process.returncode if process is not None else None
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return process.poll()
    try:
        return process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            return process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return process.wait(timeout=1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_first_json_event(path: Path) -> dict[str, Any] | None:
    try:
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if event.get("event") == "load_started":
                return event
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _start_command(command: list[str], out: BinaryIO, err: BinaryIO) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=err,
        start_new_session=True,
    )


def run_trial(args: argparse.Namespace) -> Path:
    if not PROBE.is_file():
        raise RuntimeError(f"native probe is missing: {PROBE}; run `make all` first")
    if args.observer == "sched_bpf" and not BPF_PROGRAM.is_file():
        raise RuntimeError(f"eBPF program is missing: {BPF_PROGRAM}")
    online_cpus = os.sched_getaffinity(0)
    if args.condition == "cpu_pressure":
        if not args.load_cpus or len(args.load_cpus) != args.cpu_load_workers:
            raise ValueError("cpu pressure requires one distinct --load-cpus entry per worker")
        if not set(args.load_cpus).issubset(online_cpus):
            raise ValueError(f"load CPUs {args.load_cpus} must be online in {sorted(online_cpus)}")
        if args.pin_cpu in args.load_cpus:
            raise ValueError("the probe CPU cannot also be assigned to a pressure worker")
    elif args.cpu_load_workers != 0:
        raise ValueError("--cpu-load-workers must be zero unless --condition cpu_pressure is selected")
    if args.condition not in {"baseline", "cpu_pressure", "recovery"}:
        raise ValueError("condition must be baseline, cpu_pressure, or recovery")

    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{args.condition}-{uuid.uuid4().hex[:8]}"
    root = Path(args.data_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    in_progress = root / f"{run_id}.in-progress"
    in_progress.mkdir(mode=0o700)
    destination = root / run_id

    probe_path = in_progress / "probe.jsonl"
    probe_err_path = in_progress / "probe.stderr"
    ebpf_path = in_progress / "scheduler.jsonl"
    ebpf_err_path = in_progress / "scheduler.stderr"
    ebpf_program_path = in_progress / "scheduler.generated.bt"
    workload_path = in_progress / "workload.jsonl"
    workload_err_path = in_progress / "workload.stderr"
    telemetry_path = in_progress / "telemetry.jsonl"
    overhead_path = in_progress / "overhead.json"
    overhead_err_path = in_progress / "overhead.stderr"

    environment = snapshot_environment(args.host_alias)
    manifest: dict[str, Any] = {
        "schema": "clockpressure.run.v1",
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "recorded_at_utc": now.isoformat().replace("+00:00", "Z"),
        "code_revision": _git_revision(),
        "campaign_id": args.campaign_id,
        "replicate": args.replicate,
        "campaign_role": args.campaign_role,
        "host": environment,
        "condition": args.condition,
        "workload": {
            "type": "none" if args.cpu_load_workers == 0 else "bounded_cpu_spin",
            "workers": args.cpu_load_workers,
            "cpus": args.load_cpus,
            "probe_pin_cpu": args.pin_cpu,
            "duration_sec": args.duration_sec,
            "period_us": args.period_us,
            "warmup_sec": args.warmup_sec,
            "max_cpu_package_temperature_c": args.max_temperature_c,
            "observer": args.observer,
            "ptp_device": args.ptp_device,
            "reference_class": "internal clocks plus uncalibrated NIC PHC candidate",
        },
        "measurement_semantics": {
            "timer_clock": "CLOCK_MONOTONIC absolute deadlines",
            "wakeup_lateness": "sample acquisition CLOCK_MONOTONIC minus scheduled absolute deadline",
            "clock_rate_comparison": "same-host CLOCK_MONOTONIC, CLOCK_MONOTONIC_RAW, CLOCK_BOOTTIME, CLOCK_REALTIME, CLOCK_TAI, optional NIC PHC",
            "ebpf_clock": "bpf_ktime_get_ns (kernel monotonic domain; not independent)",
            "external_elapsed_time_reference": None,
            "evidence_scope": "scheduler/timer delivery and internal cross-clock diagnostics only",
        },
        "artifacts": {},
        "status": "running",
    }
    _write_json(in_progress / "manifest.json", manifest)

    load_proc: subprocess.Popen[bytes] | None = None
    probe_proc: subprocess.Popen[bytes] | None = None
    observer_proc: subprocess.Popen[bytes] | None = None
    close_streams: list[BinaryIO] = []
    telemetry_stop = threading.Event()
    thermal_abort = threading.Event()
    telemetry_thread: threading.Thread | None = None
    telemetry_stream: BinaryIO | None = None
    status = "failed"
    failure: str | None = None
    started_monotonic = time.monotonic()
    try:
        if args.cpu_load_workers > 0:
            load_out = workload_path.open("wb")
            load_err = workload_err_path.open("wb")
            close_streams.extend([load_out, load_err])
            load_cmd = [
                sys.executable,
                str(WORKLOAD),
                "--cpus",
                ",".join(str(cpu) for cpu in args.load_cpus),
            ]
            load_proc = _start_command(load_cmd, load_out, load_err)
            load_started = None
            load_deadline = time.monotonic() + 8
            while time.monotonic() < load_deadline and load_proc.poll() is None:
                load_started = _read_first_json_event(workload_path)
                if load_started:
                    break
                time.sleep(0.025)
            if not load_started:
                raise RuntimeError("CPU pressure workers failed to start")
            time.sleep(args.warmup_sec)

        probe_needs_privilege = (
            args.ptp_device is not None
            and Path(args.ptp_device).exists()
            and not os.access(args.ptp_device, os.R_OK)
            and os.geteuid() != 0
        )

        telemetry_stream = telemetry_path.open("wb")
        close_streams.append(telemetry_stream)

        def telemetry_loop() -> None:
            while not telemetry_stop.is_set():
                context = sample_context()
                for name, sensor in context["temperatures"].items():
                    sensor_name = f"{name} {sensor.get('type', '')}".lower()
                    temperature = sensor.get("temp_millidegree_c")
                    if (
                        temperature is not None
                        and ("coretemp" in sensor_name or "x86_pkg_temp" in sensor_name)
                        and int(temperature) >= args.max_temperature_c * 1000
                    ):
                        thermal_abort.set()
                payload = json.dumps(context, sort_keys=True).encode() + b"\n"
                telemetry_stream.write(payload)
                telemetry_stream.flush()
                if telemetry_stop.wait(1.0):
                    break

        telemetry_thread = threading.Thread(target=telemetry_loop, name="clockpressure-telemetry")
        telemetry_thread.start()

        overhead_out = overhead_path.open("wb")
        overhead_err = overhead_err_path.open("wb")
        close_streams.extend([overhead_out, overhead_err])
        overhead_cmd = [
            str(PROBE),
            "--mode",
            "overhead",
            "--samples",
            str(args.overhead_samples),
            "--pin-cpu",
            str(args.pin_cpu),
        ]
        if args.ptp_device:
            overhead_cmd += ["--ptp-device", args.ptp_device]
        if probe_needs_privilege:
            overhead_cmd = ["sudo", "-n", *overhead_cmd]
        overhead_proc = _start_command(overhead_cmd, overhead_out, overhead_err)
        try:
            overhead_return_code = overhead_proc.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            _stop_group(overhead_proc)
            raise RuntimeError("timestamp overhead preflight exceeded 30 seconds") from exc
        if overhead_return_code != 0:
            diagnostic = overhead_err_path.read_text(errors="replace")
            raise RuntimeError(f"timestamp overhead preflight failed: {diagnostic[-2000:]}")

        probe_out = probe_path.open("wb")
        probe_err = probe_err_path.open("wb")
        close_streams.extend([probe_out, probe_err])
        probe_cmd = [
            str(PROBE),
            "--mode",
            "probe",
            "--run-id",
            run_id,
            "--condition",
            args.condition,
            "--duration-sec",
            str(args.duration_sec),
            "--period-us",
            str(args.period_us),
            "--start-delay-ms",
            "1500",
            "--pin-cpu",
            str(args.pin_cpu),
        ]
        if args.ptp_device:
            probe_cmd += ["--ptp-device", args.ptp_device]
        if probe_needs_privilege:
            probe_cmd = ["sudo", "-n", *probe_cmd]
        probe_proc = _start_command(probe_cmd, probe_out, probe_err)
        probe_meta = _first_probe_metadata(probe_path, probe_proc)
        if args.observer == "sched_bpf":
            observer_out = ebpf_path.open("wb")
            observer_err = ebpf_err_path.open("wb")
            close_streams.extend([observer_out, observer_err])
            observer_cmd = [
                "sudo",
                "-n",
                "bpftrace",
                "-q",
                str(ebpf_program_path),
            ]
            target_pid = int(probe_meta["pid"])
            if target_pid <= 1:
                raise RuntimeError(f"invalid probe PID for scheduler attachment: {target_pid}")
            template = BPF_PROGRAM.read_text(encoding="utf-8")
            if "CP_TARGET" not in template:
                raise RuntimeError("scheduler BPF template has no CP_TARGET placeholder")
            generated_program = template.replace("CP_TARGET", str(target_pid))
            ebpf_program_path.write_text(generated_program, encoding="utf-8")
            os.chmod(ebpf_program_path, 0o600)
            manifest["scheduler_observer"] = {
                "target_pid": target_pid,
                "template": "instrumentation/sched_wakeup.bt",
                "generated_script": ebpf_program_path.name,
                "generated_script_sha256": _sha256(ebpf_program_path),
                "clock_id": "bpf_ktime_get_ns",
            }
            _write_json(in_progress / "manifest.json", manifest)
            observer_proc = _start_command(observer_cmd, observer_out, observer_err)
            time.sleep(0.5)
            if observer_proc.poll() is not None:
                diagnostics = ebpf_err_path.read_text(errors="replace")
                raise RuntimeError(f"eBPF observer failed to attach: {diagnostics[-2000:]}")

        probe_deadline = time.monotonic() + args.duration_sec + 12
        while probe_proc.poll() is None:
            if thermal_abort.is_set():
                raise RuntimeError(
                    f"CPU package reached the {args.max_temperature_c} C stop threshold"
                )
            if time.monotonic() >= probe_deadline:
                raise RuntimeError("native probe exceeded its bounded run time")
            time.sleep(0.1)
        probe_return_code = probe_proc.returncode
        if observer_proc is not None:
            observer_return_code = _stop_group(observer_proc)
            if observer_return_code not in (0, -signal.SIGINT, 130):
                diagnostics = ebpf_err_path.read_text(errors="replace")
                raise RuntimeError(
                    f"eBPF observer exited with status {observer_return_code}: {diagnostics[-2000:]}"
                )
            observer_proc = None
        if load_proc is not None:
            _stop_group(load_proc)
            load_proc = None
        if probe_return_code != 0:
            raise RuntimeError(f"native probe exited with status {probe_return_code}")
        status = "complete"
    except KeyboardInterrupt:
        failure = "interrupted by operator"
        raise
    except Exception as exc:
        failure = str(exc)
        raise
    finally:
        telemetry_stop.set()
        if telemetry_thread is not None:
            telemetry_thread.join(timeout=2)
        for process in (observer_proc, probe_proc, load_proc):
            _stop_group(process)
        for stream in close_streams:
            if not stream.closed:
                stream.close()
        manifest["elapsed_orchestration_sec"] = round(time.monotonic() - started_monotonic, 6)
        manifest["status"] = status
        manifest["host_after"] = snapshot_environment(args.host_alias)
        if failure:
            manifest["failure"] = failure
        if probe_path.exists():
            try:
                records = [json.loads(line) for line in probe_path.read_text().splitlines()]
                starts = [record for record in records if record.get("kind") == "start"]
                ends = [record for record in records if record.get("kind") == "end"]
                manifest["probe_metadata"] = next(
                    (record for record in records if record.get("kind") == "metadata"), None
                )
                if starts and ends:
                    start, end = starts[0], ends[-1]
                    for clock in ("monotonic_ns", "monotonic_raw_ns", "boottime_ns", "ptp_ns"):
                        if start.get(clock) is not None and end.get(clock) is not None:
                            manifest.setdefault("measured_intervals_ns", {})[clock] = (
                                end[clock] - start[clock]
                            )
                    manifest["observed_sample_count"] = sum(
                        record.get("kind") == "sample" for record in records
                    )
            except (OSError, json.JSONDecodeError, TypeError):
                manifest["probe_parse_status"] = "incomplete_or_invalid"
        if workload_path.exists() and (load_started := _read_first_json_event(workload_path)):
            manifest["workload_start_event"] = load_started
        for path in (
            probe_path,
            probe_err_path,
            ebpf_path,
            ebpf_err_path,
            ebpf_program_path,
            workload_path,
            workload_err_path,
            telemetry_path,
            overhead_path,
            overhead_err_path,
        ):
            if path.is_file():
                manifest["artifacts"][path.name] = {
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
        _write_json(in_progress / "manifest.json", manifest)
        # Atomic finalization keeps interrupted data visible as .in-progress.
        if status == "complete":
            in_progress.replace(destination)

    return destination if status == "complete" else in_progress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condition", choices=("baseline", "cpu_pressure", "recovery"), required=True)
    parser.add_argument("--duration-sec", type=int, default=30)
    parser.add_argument("--period-us", type=int, default=10000)
    parser.add_argument("--cpu-load-workers", type=int, default=0)
    parser.add_argument("--load-cpus", type=_parse_cpus, default=_parse_cpus("1,2,3,4"))
    parser.add_argument("--pin-cpu", type=int, default=-1)
    parser.add_argument("--warmup-sec", type=float, default=1.0)
    parser.add_argument("--overhead-samples", type=int, default=10000)
    parser.add_argument("--max-temperature-c", type=int, default=85)
    parser.add_argument("--observer", choices=("none", "sched_bpf"), default="none")
    parser.add_argument("--ptp-device", default="/dev/ptp0", help="empty string disables PHC reads")
    parser.add_argument("--host-alias", default="worker-03")
    parser.add_argument("--campaign-id")
    parser.add_argument("--replicate", type=int)
    parser.add_argument("--campaign-role")
    parser.add_argument("--data-dir", default="~/clockpressure-data/runs")
    return parser


def main() -> int:
    def raise_interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, raise_interrupt)
    args = build_parser().parse_args()
    if args.duration_sec < 1 or args.duration_sec > 3600:
        raise SystemExit("--duration-sec must be in 1..3600")
    if args.period_us < 100 or args.period_us > 10_000_000:
        raise SystemExit("--period-us must be in 100..10000000")
    if args.cpu_load_workers < 0 or args.cpu_load_workers > 256:
        raise SystemExit("--cpu-load-workers must be in 0..256")
    if args.warmup_sec < 0 or args.warmup_sec > 30:
        raise SystemExit("--warmup-sec must be in 0..30")
    if args.max_temperature_c < 60 or args.max_temperature_c > 95:
        raise SystemExit("--max-temperature-c must be in 60..95")
    if args.ptp_device == "":
        args.ptp_device = None
    try:
        path = run_trial(args)
    except Exception as exc:
        print(f"clockpressure: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
