"""Counterbalance timerlat user tracing against tracer-disabled clock probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import signal
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.analyze_timerlat import analyze_trace
from experiments.environment import snapshot_environment
from experiments.run_trial import _parse_cpus, _write_json

TRIAL = ROOT / "experiments" / "run_trial.py"
TIMERLAT_WORKER = ROOT / "experiments" / "timerlat_user_worker.py"
_BUFFER_COUNT = re.compile(r"entries-in-buffer/entries-written:\s*(\d+)/(\d+)")


def _read(path: Path) -> str:
    return path.read_text().strip()


def _write(path: Path, value: str) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write(value.rstrip("\n") + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative_artifact(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _empty_trace(trace: str) -> bool:
    match = _BUFFER_COUNT.search(trace)
    return bool(match and match.group(1) == "0" and match.group(2) == "0")


def _option_enabled(options: str, option: str) -> bool:
    words = set(options.split())
    if f"NO_{option}" in words:
        return False
    return option in words


class TracefsTimerlat:
    """Manage the global timerlat tracer and restore its previously idle state."""

    def __init__(self, tracefs: Path, cpu: int, period_us: int, buffer_kb: int):
        self.tracefs = tracefs
        self.cpu = cpu
        self.period_us = period_us
        self.buffer_kb = buffer_kb
        self.changed = False
        self.before = self._settings()
        self._check_idle_state()

    def _settings(self) -> dict[str, Any]:
        options = _read(self.tracefs / "osnoise/options")
        return {
            "current_tracer": _read(self.tracefs / "current_tracer"),
            "tracing_on": _read(self.tracefs / "tracing_on"),
            "buffer_size_kb": _read(self.tracefs / "buffer_size_kb"),
            "timerlat_period_us": _read(self.tracefs / "osnoise/timerlat_period_us"),
            "osnoise_cpus": _read(self.tracefs / "osnoise/cpus"),
            "osnoise_workload_enabled": _option_enabled(options, "OSNOISE_WORKLOAD"),
            "osnoise_options_raw": options,
            "enabled_events": _read(self.tracefs / "set_event"),
            "trace_empty": _empty_trace((self.tracefs / "trace").read_text(errors="replace")),
        }


    def _check_idle_state(self) -> None:
        settings = self.before
        if settings["current_tracer"] != "nop":
            raise RuntimeError("tracefs is already running a tracer; refusing to replace it")
        if settings["enabled_events"]:
            raise RuntimeError("tracefs has enabled events; refusing to disturb another trace")
        if not settings["trace_empty"]:
            raise RuntimeError("tracefs buffer has retained events; refusing to clear them")
        available = set(_read(self.tracefs / "available_tracers").split())
        if "timerlat" not in available:
            raise RuntimeError("the active tracefs does not expose the timerlat tracer")

    def start(self) -> None:
        self.changed = True
        _write(self.tracefs / "tracing_on", "0")
        _write(self.tracefs / "trace", "")
        _write(self.tracefs / "buffer_size_kb", str(self.buffer_kb))
        _write(self.tracefs / "osnoise/cpus", str(self.cpu))
        _write(self.tracefs / "osnoise/timerlat_period_us", str(self.period_us))
        if self.before["osnoise_workload_enabled"]:
            _write(self.tracefs / "osnoise/options", "NO_OSNOISE_WORKLOAD")
        _write(self.tracefs / "current_tracer", "timerlat")
        _write(self.tracefs / "tracing_on", "1")
        if _read(self.tracefs / "current_tracer") != "timerlat":
            raise RuntimeError("timerlat tracer did not become active")
        if not (self.tracefs / f"osnoise/per_cpu/cpu{self.cpu}/timerlat_fd").exists():
            raise RuntimeError("timerlat_fd is absent for the selected CPU")

    def stop_and_restore(self) -> dict[str, Any]:
        if not self.changed:
            return {"before": self.before, "after": self._settings(), "restored": True}

        trace = ""
        cpu_stats = ""
        errors: list[Exception] = []
        try:
            _write(self.tracefs / "tracing_on", "0")
            trace = (self.tracefs / "trace").read_text(errors="replace")
            stats_path = self.tracefs / f"per_cpu/cpu{self.cpu}/stats"
            if stats_path.exists():
                cpu_stats = stats_path.read_text(errors="replace")
        except Exception as exc:  # restoration still takes priority over collection
            errors.append(exc)
        finally:
            restore_actions = [
                (self.tracefs / "current_tracer", "nop"),
                (self.tracefs / "trace", ""),
                (self.tracefs / "osnoise/timerlat_period_us", self.before["timerlat_period_us"]),
                (self.tracefs / "osnoise/cpus", self.before["osnoise_cpus"]),
                (self.tracefs / "buffer_size_kb", self.before["buffer_size_kb"]),
            ]
            for path, value in restore_actions:
                try:
                    _write(path, value)
                except Exception as exc:
                    errors.append(exc)
            try:
                current_options = _read(self.tracefs / "osnoise/options")
                current_enabled = _option_enabled(current_options, "OSNOISE_WORKLOAD")
                if current_enabled != self.before["osnoise_workload_enabled"]:
                    toggle = (
                        "OSNOISE_WORKLOAD"
                        if self.before["osnoise_workload_enabled"]
                        else "NO_OSNOISE_WORKLOAD"
                    )
                    _write(self.tracefs / "osnoise/options", toggle)
            except Exception as exc:
                errors.append(exc)
            for path, value in (
                (self.tracefs / "current_tracer", self.before["current_tracer"]),
                (self.tracefs / "tracing_on", self.before["tracing_on"]),
            ):
                try:
                    _write(path, value)
                except Exception as exc:
                    errors.append(exc)
            self.changed = False

        after = self._settings()
        restored = all(
            after[key] == self.before[key]
            for key in (
                "current_tracer",
                "tracing_on",
                "buffer_size_kb",
                "timerlat_period_us",
                "osnoise_cpus",
                "osnoise_workload_enabled",
                "enabled_events",
                "trace_empty",
            )
        )
        if errors:
            raise RuntimeError(f"tracefs collection or restoration failed: {errors[0]}") from errors[0]
        if not restored:
            raise RuntimeError(f"tracefs state was not restored: before={self.before}, after={after}")
        return {
            "before": self.before,
            "after": after,
            "restored": restored,
            "cpu_buffer_stats": cpu_stats,
            "trace": trace,
        }


class CpuDmaLatencyRequest:
    """Hold one temporary global CPU latency QoS request on its own FD."""

    def __init__(self, device: Path, requested_us: int):
        self.device = device
        self.requested_us = requested_us
        self.fd: int | None = None
        if not device.is_char_device():
            raise RuntimeError(f"CPU latency QoS device is unavailable: {device}")
        self.effective_before_us = self._read_effective()
        self.effective_during_us: int | None = None

    def _read_effective(self) -> int:
        fd = os.open(self.device, os.O_RDONLY)
        try:
            value = os.read(fd, 4)
        finally:
            os.close(fd)
        if len(value) != 4:
            raise RuntimeError(f"short read of effective CPU latency from {self.device}")
        return struct.unpack("=i", value)[0]

    def start(self) -> None:
        if self.effective_before_us <= self.requested_us:
            raise RuntimeError(
                "existing CPU latency QoS is already at least as restrictive as the requested intervention "
                f"({self.effective_before_us} us <= {self.requested_us} us)"
            )
        self.fd = os.open(self.device, os.O_RDWR)
        try:
            written = os.write(self.fd, struct.pack("=i", self.requested_us))
            if written != 4:
                raise RuntimeError(f"short write to {self.device}: {written} bytes")
            self.effective_during_us = self._read_effective()
            if self.effective_during_us != self.requested_us:
                raise RuntimeError(
                    "the requested CPU latency QoS did not become effective: "
                    f"requested {self.requested_us} us, observed {self.effective_during_us} us"
                )
        except Exception:
            self.close()
            raise

    def close(self) -> dict[str, Any]:
        if self.fd is None:
            effective_after = self._read_effective()
            return {
                "device": str(self.device),
                "requested_us": self.requested_us,
                "effective_before_us": self.effective_before_us,
                "effective_during_us": self.effective_during_us,
                "effective_after_us": effective_after,
                "restored": effective_after == self.effective_before_us,
            }
        fd, self.fd = self.fd, None
        os.close(fd)
        effective_after = self._read_effective()
        restored = effective_after == self.effective_before_us
        state = {
            "device": str(self.device),
            "requested_us": self.requested_us,
            "effective_before_us": self.effective_before_us,
            "effective_during_us": self.effective_during_us,
            "effective_after_us": effective_after,
            "restored": restored,
        }
        return state


def _parse_cpus_arg(value: str) -> list[int]:
    try:
        cpus = _parse_cpus(value)
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return cpus


def _trial_command(
    args: argparse.Namespace,
    *,
    condition: str,
    arm: str,
    data_dir: Path,
    campaign_id: str,
    replicate: int,
) -> list[str]:
    workers = args.cpu_load_workers if condition == "cpu_pressure" else 0
    warmup = args.warmup_sec if workers else 0
    if condition == "recovery":
        warmup = 0
    return [
        sys.executable,
        str(TRIAL),
        "--condition",
        condition,
        "--duration-sec",
        str(args.duration_sec),
        "--period-us",
        str(args.period_us),
        "--cpu-load-workers",
        str(workers),
        "--load-cpus",
        ",".join(map(str, args.load_cpus)),
        "--pin-cpu",
        str(args.probe_cpu),
        "--observer",
        "none",
        "--host-alias",
        args.host_alias,
        "--data-dir",
        str(data_dir),
        "--campaign-id",
        f"{campaign_id}-{arm}",
        "--replicate",
        str(replicate),
        "--campaign-role",
        f"{arm}_{condition}",
        "--warmup-sec",
        str(warmup),
    ]


def _metadata_ready(run_root: Path, known_paths: set[Path]) -> Path | None:
    for candidate in run_root.glob("*.in-progress"):
        if candidate in known_paths:
            continue
        path = candidate / "probe.jsonl"
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    event = json.loads(line)
                    if event.get("kind") == "metadata":
                        return candidate
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _wait_for_metadata(run_root: Path, known_paths: set[Path], process: subprocess.Popen[bytes]) -> Path:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        found = _metadata_ready(run_root, known_paths)
        if found is not None:
            return found
        if process.poll() is not None:
            break
        time.sleep(0.025)
    raise RuntimeError(f"ClockPressure probe metadata did not appear (return code={process.poll()})")


def _stop_process(process: subprocess.Popen[bytes] | None, grace_seconds: float = 5) -> int | None:
    if process is None or process.poll() is not None:
        return process.returncode if process is not None else None
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return process.poll()
    try:
        return process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return process.wait(timeout=2)


def _run_trial(
    args: argparse.Namespace,
    *,
    out: Path,
    campaign_id: str,
    replicate: int,
    arm: str,
    condition: str,
    role: str,
) -> dict[str, Any]:
    arm_data_dir = out / "runs" / arm
    run_root = arm_data_dir
    run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    known_paths = set(run_root.glob("*.in-progress"))
    stem = f"r{replicate}-{arm}-{condition}-{uuid.uuid4().hex[:8]}"
    stdout_path = logs / f"{stem}.stdout"
    stderr_path = logs / f"{stem}.stderr"
    command = _trial_command(
        args,
        condition=condition,
        arm=arm,
        data_dir=arm_data_dir,
        campaign_id=campaign_id,
        replicate=replicate,
    )
    trace_session = None
    timerlat_enabled = arm.startswith("timerlat_user")
    qos_request = None
    qos_record: dict[str, Any] | None = None
    trial_process: subprocess.Popen[bytes] | None = None
    user_process: subprocess.Popen[bytes] | None = None
    user_stdout = b""
    user_stderr = b""
    in_progress: Path | None = None
    trial_returncode: int | None = None
    user_returncode: int | None = None
    trace_record: dict[str, Any] | None = None
    error: str | None = None

    if timerlat_enabled:
        trace_session = TracefsTimerlat(
            Path(args.tracefs_root), args.timerlat_cpu, args.period_us, args.buffer_kb
        )
    if arm == "timerlat_user_pm_qos":
        qos_request = CpuDmaLatencyRequest(
            Path(args.cpu_dma_latency_path), args.dma_latency_us
        )
    try:
        if qos_request is not None:
            qos_request.start()
        if trace_session is not None:
            trace_session.start()
        with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
            trial_process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                start_new_session=True,
            )
        in_progress = _wait_for_metadata(run_root, known_paths, trial_process)
        if timerlat_enabled:
            requested_reads = (args.duration_sec * 1_000_000 + args.period_us - 1) // args.period_us
            timerlat_fd = (
                Path(args.tracefs_root)
                / "osnoise"
                / "per_cpu"
                / f"cpu{args.timerlat_cpu}"
                / "timerlat_fd"
            )
            user_command = [
                sys.executable,
                str(TIMERLAT_WORKER),
                "--cpu",
                str(args.timerlat_cpu),
                "--fd-path",
                str(timerlat_fd),
                "--reads",
                str(requested_reads),
                "--fifo-priority",
                str(args.fifo_priority),
            ]
            user_process = subprocess.Popen(
                user_command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        timeout = args.duration_sec + args.warmup_sec + 60
        trial_returncode = trial_process.wait(timeout=timeout)
        if user_process is not None:
            try:
                user_stdout, user_stderr = user_process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                _stop_process(user_process)
                user_stdout, user_stderr = user_process.communicate(timeout=5)
            user_returncode = user_process.returncode
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if trial_process is not None and trial_process.poll() is None:
            _stop_process(trial_process)
            trial_returncode = trial_process.returncode
        if user_process is not None and user_process.poll() is None:
            _stop_process(user_process)
            user_stdout, user_stderr = user_process.communicate(timeout=5)
            user_returncode = user_process.returncode
        if trace_session is not None:
            try:
                trace_record = trace_session.stop_and_restore()
            except Exception as exc:
                error = error or f"tracefs restore: {type(exc).__name__}: {exc}"
        if qos_request is not None:
            try:
                qos_record = qos_request.close()
            except Exception as exc:
                error = error or f"CPU latency QoS restore: {type(exc).__name__}: {exc}"

    run_dir = None
    stdout_text = stdout_path.read_text(errors="replace") if stdout_path.exists() else ""
    for line in reversed(stdout_text.splitlines()):
        candidate = Path(line.strip())
        if candidate.is_dir() and (candidate / "manifest.json").is_file():
            run_dir = candidate
            break
    if run_dir is None and in_progress is not None:
        completed_path = in_progress.with_name(in_progress.name.removesuffix(".in-progress"))
        if completed_path.is_dir():
            run_dir = completed_path

    entry: dict[str, Any] = {
        "replicate": replicate,
        "arm": arm,
        "condition": condition,
        "role": role,
        "command": command,
        "trial_returncode": trial_returncode,
        "run_dir": _relative_artifact(run_dir, out) if run_dir else None,
        "trial_stdout": _relative_artifact(stdout_path, out),
        "trial_stderr": _relative_artifact(stderr_path, out),
        "status": "complete" if error is None and trial_returncode == 0 else "failed",
    }
    if timerlat_enabled:
        worker_summary: dict[str, Any] | None = None
        try:
            worker_summary = json.loads(user_stdout.decode(errors="replace").strip())
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        entry["timerlat_user_worker"] = {
            "returncode": user_returncode,
            "summary": worker_summary,
            "stderr": user_stderr.decode(errors="replace"),
        }
        if trace_record is not None:
            timerlat_dir = out / "timerlat" / arm
            timerlat_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            run_id = run_dir.name if run_dir is not None else stem
            trace_path = timerlat_dir / f"{run_id}.trace"
            trace_path.write_text(trace_record.get("trace", ""), encoding="utf-8")
            os.chmod(trace_path, 0o600)
            stats_path = timerlat_dir / f"{run_id}.cpu{args.timerlat_cpu}.stats"
            stats_path.write_text(trace_record.get("cpu_buffer_stats", ""), encoding="utf-8")
            os.chmod(stats_path, 0o600)
            analysis = analyze_trace(trace_path)
            analysis_path = timerlat_dir / f"{run_id}.analysis.json"
            _write_json(analysis_path, analysis)
            entry["timerlat_trace"] = _relative_artifact(trace_path, out)
            entry["timerlat_trace_sha256"] = _sha256(trace_path)
            entry["timerlat_analysis"] = _relative_artifact(analysis_path, out)
            entry["timerlat_analysis_summary"] = analysis["latency_ns"]
            entry["timerlat_activation_integrity"] = {
                "matched_irq_thread_activations": analysis["matched_irq_thread_activation_count"],
                "incomplete_irq_thread_activations": analysis["incomplete_irq_thread_activation_count"],
                "duplicate_activation_events": analysis["duplicate_activation_event_count"],
                "malformed_latency_lines": analysis["malformed_latency_line_count"],
            }
            entry["tracefs_restoration"] = {
                key: value for key, value in trace_record.items() if key != "trace"
            }
            if not analysis["matched_irq_thread_activation_count"]:
                entry["error"] = "timerlat trace retained no matched IRQ/thread activation"
                entry["status"] = "failed"
            if not trace_record.get("restored"):
                entry["error"] = "tracefs settings were not restored to their prior state"
                entry["status"] = "failed"
    if qos_record is not None:
        entry["cpu_dma_latency_request"] = qos_record
        if not qos_record.get("restored"):
            entry["error"] = "CPU latency QoS did not return to its prior effective value"
            entry["status"] = "failed"
    if error:
        entry["error"] = error
        entry["status"] = "failed"
    if trial_returncode not in (0, None):
        entry["error"] = entry.get("error") or f"ClockPressure trial exited {trial_returncode}"
    if timerlat_enabled and user_returncode not in (0, None):
        entry["error"] = entry.get("error") or f"timerlat user worker exited {user_returncode}"
        entry["status"] = "failed"
    return entry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--design",
        choices=("observer", "cpu_latency_qos"),
        default="observer",
        help="compare tracer off/on, or timerlat with default/PM QoS idle-latency policy",
    )
    parser.add_argument("--duration-sec", type=int, default=30)
    parser.add_argument("--period-us", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cpu-load-workers", type=int, default=4)
    parser.add_argument("--load-cpus", type=_parse_cpus_arg, default=_parse_cpus("1,2,3,4"))
    parser.add_argument("--probe-cpu", type=int, default=6)
    parser.add_argument("--timerlat-cpu", type=int, default=7)
    parser.add_argument("--fifo-priority", type=int, default=90)
    parser.add_argument("--buffer-kb", type=int, default=2048)
    parser.add_argument("--warmup-sec", type=float, default=5)
    parser.add_argument("--recovery-seconds", type=int, default=5)
    parser.add_argument(
        "--intertrial-cooldown-sec",
        type=int,
        default=0,
        help="idle cooling interval after each completed trial",
    )
    parser.add_argument("--seed", type=int)
    parser.add_argument("--host-alias", default="worker-03")
    parser.add_argument("--tracefs-root", default="/sys/kernel/tracing")
    parser.add_argument("--cpu-dma-latency-path", default="/dev/cpu_dma_latency")
    parser.add_argument("--dma-latency-us", type=int, default=0)
    parser.add_argument("--data-dir", default="~/clockpressure-data/timerlat-controlled")
    return parser


def run_campaign(args: argparse.Namespace) -> Path:
    if os.geteuid() != 0:
        raise RuntimeError("tracefs timerlat collection requires root; run under sudo")
    if not 1 <= args.duration_sec <= 3600:
        raise ValueError("--duration-sec must be in 1..3600")
    if not 100 <= args.period_us <= 10_000_000:
        raise ValueError("--period-us must be in 100..10000000")
    if not 1 <= args.repeats <= 100:
        raise ValueError("--repeats must be in 1..100")
    if args.cpu_load_workers != len(args.load_cpus):
        raise ValueError("provide one --load-cpus entry for each --cpu-load-workers process")
    if args.probe_cpu in args.load_cpus or args.timerlat_cpu in args.load_cpus:
        raise ValueError("probe and timerlat CPUs must not overlap CPU pressure workers")
    if args.probe_cpu == args.timerlat_cpu:
        raise ValueError("probe and timerlat user processes require separate CPUs")
    if args.recovery_seconds < 0 or args.recovery_seconds > 120:
        raise ValueError("--recovery-seconds must be in 0..120")
    if args.intertrial_cooldown_sec < 0 or args.intertrial_cooldown_sec > 600:
        raise ValueError("--intertrial-cooldown-sec must be in 0..600")
    if args.warmup_sec < 0 or args.warmup_sec > 30:
        raise ValueError("--warmup-sec must be in 0..30")
    if not 1 <= args.fifo_priority <= 99:
        raise ValueError("--fifo-priority must be in 1..99")
    if not 0 <= args.dma_latency_us <= 2_000_000_000:
        raise ValueError("--dma-latency-us must be in 0..2000000000")

    online_cpus = os.sched_getaffinity(0)
    requested_cpus = set(args.load_cpus) | {args.probe_cpu, args.timerlat_cpu}
    if not requested_cpus.issubset(online_cpus):
        raise ValueError(f"requested CPUs {sorted(requested_cpus)} must be online in {sorted(online_cpus)}")
    if not TRIAL.is_file() or not TIMERLAT_WORKER.is_file():
        raise RuntimeError("ClockPressure trial or timerlat user worker is missing")
    if not (ROOT / "build" / "clockpressure-probe").is_file():
        raise RuntimeError("native probe is missing; run `make all` first")

    qos_initial_effective_us = None
    if args.design == "cpu_latency_qos":
        qos_preflight = CpuDmaLatencyRequest(
            Path(args.cpu_dma_latency_path), args.dma_latency_us
        )
        qos_initial_effective_us = qos_preflight.effective_before_us
        if qos_initial_effective_us <= args.dma_latency_us:
            raise RuntimeError(
                "CPU latency QoS intervention would not change the effective setting: "
                f"current={qos_initial_effective_us} us, requested={args.dma_latency_us} us"
            )

    out = Path(args.data_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(out, 0o700)
    (out / "runs").mkdir(mode=0o700)
    (out / "timerlat").mkdir(mode=0o700)
    (out / "logs").mkdir(mode=0o700)

    now = datetime.now(timezone.utc)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1 << 63)
    randomizer = random.Random(seed)
    campaign_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-timerlat-campaign-{uuid.uuid4().hex[:8]}"
    if args.design == "observer":
        arms = ["timerlat_disabled", "timerlat_user"]
        timerlat_arms = ["timerlat_user"]
        power_intervention = None
    else:
        arms = ["timerlat_user_default", "timerlat_user_pm_qos"]
        timerlat_arms = arms.copy()
        power_intervention = {
            "device": args.cpu_dma_latency_path,
            "requested_us": args.dma_latency_us,
            "effective_before_us": qos_initial_effective_us,
            "arm": "timerlat_user_pm_qos",
            "lifetime": "one open file descriptor held over each trial; close removes this request",
        }

    campaign: dict[str, Any] = {
        "schema": "clockpressure.timerlat-campaign.v1",
        "campaign_id": campaign_id,
        "created_at_utc": now.isoformat().replace("+00:00", "Z"),
        "code_revision": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "seed": seed,
        "host": snapshot_environment(args.host_alias),
        "design": {
            "mode": args.design,
            "arms": arms,
            "duration_sec": args.duration_sec,
            "period_us": args.period_us,
            "replicates": args.repeats,
            "probe_cpu": args.probe_cpu,
            "timerlat_cpu": args.timerlat_cpu,
            "load_cpus": args.load_cpus,
            "cpu_load_workers": args.cpu_load_workers,
            "fifo_priority": args.fifo_priority,
            "timerlat_buffer_kb": args.buffer_kb,
            "intertrial_cooldown_sec": args.intertrial_cooldown_sec,
            "timerlat_arms": timerlat_arms,
            "cpu_dma_latency_intervention": power_intervention,
            "conditions": ["baseline", "cpu_pressure", "recovery"],
            "timerlat_reader_clock": "CLOCK_MONOTONIC_RAW on worker-03; not an independent reference",
            "external_elapsed_time_reference": None,
            "pressure_workload": "four bounded nice +10 CPU spin workers, pinned to configured load CPUs",
            "timerlat_user_workload": "one pinned SCHED_FIFO reader of timerlat_fd; no explicit computation",
            "control_clock_probe": "ClockPressure absolute CLOCK_MONOTONIC sampler pinned to probe CPU",
        },
        "initial_tracefs_state": TracefsTimerlat(
            Path(args.tracefs_root), args.timerlat_cpu, args.period_us, args.buffer_kb
        ).before,
        "trials": [],
        "status": "running",
        "data_dir": str(out),
    }
    campaign_path = out / "campaign.json"
    _write_json(campaign_path, campaign)

    plan: list[tuple[int, str, str, str]] = []
    for replicate in range(1, args.repeats + 1):
        randomized_arms = arms.copy()
        randomizer.shuffle(randomized_arms)
        for arm in randomized_arms:
            conditions = ["baseline", "cpu_pressure"]
            randomizer.shuffle(conditions)
            for condition in conditions:
                plan.append((replicate, arm, condition, "randomized_trial"))
                if condition == "cpu_pressure":
                    plan.append((replicate, arm, "recovery", "post_pressure_recovery"))
    campaign["requested_order"] = [
        {"replicate": rep, "arm": arm, "condition": condition, "role": role}
        for rep, arm, condition, role in plan
    ]
    _write_json(campaign_path, campaign)

    total = len(plan)
    try:
        for ordinal, (replicate, arm, condition, role) in enumerate(plan, start=1):
            print(
                f"[{ordinal}/{total}] replicate={replicate} arm={arm} condition={condition}",
                flush=True,
            )
            if role == "post_pressure_recovery" and args.recovery_seconds:
                time.sleep(args.recovery_seconds)
            entry = _run_trial(
                args,
                out=out,
                campaign_id=campaign_id,
                replicate=replicate,
                arm=arm,
                condition=condition,
                role=role,
            )
            entry["ordinal"] = ordinal
            campaign["trials"].append(entry)
            if entry["status"] != "complete":
                campaign["status"] = "failed"
                campaign["failure"] = entry.get("error", "trial failed")
                break
            _write_json(campaign_path, campaign)
            if ordinal < total and args.intertrial_cooldown_sec:
                print(
                    f"cooldown {args.intertrial_cooldown_sec}s before next trial",
                    flush=True,
                )
                time.sleep(args.intertrial_cooldown_sec)
    except KeyboardInterrupt:
        campaign["status"] = "interrupted"
        campaign["failure"] = "received interrupt; active trial cleanup was attempted"
    except Exception as exc:
        campaign["status"] = "failed"
        campaign["failure"] = f"{type(exc).__name__}: {exc}"
    else:
        if campaign["status"] == "running":
            campaign["status"] = "complete"
    campaign["finished_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(campaign_path, campaign)
    print(campaign_path)
    return campaign_path


def main() -> int:
    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    args = build_parser().parse_args()
    try:
        campaign_path = run_campaign(args)
    except Exception as exc:
        print(f"clockpressure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    campaign = json.loads(campaign_path.read_text())
    return 0 if campaign.get("status") == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
