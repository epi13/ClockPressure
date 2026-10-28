"""Run paired timerlat campaigns under multiple Linux clocksource selections."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experiments.clocksource_selection import ClocksourceSelection
from experiments.environment import snapshot_environment


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLOCKSOURCE_ROOT = Path("/sys/devices/system/clocksource/clocksource0")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _parse_sources(value: str) -> list[str]:
    sources = [item.strip() for item in value.split(",") if item.strip()]
    if len(sources) != 2 or len(sources) != len(set(sources)):
        raise argparse.ArgumentTypeError("--sources needs exactly two distinct clocksource names")
    if any("/" in source or "\n" in source for source in sources):
        raise argparse.ArgumentTypeError("clocksource names cannot contain a slash or newline")
    return sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=_parse_sources, default=_parse_sources("tsc,acpi_pm"))
    parser.add_argument("--pairs", type=int, default=3, help="randomized pair count per clocksource")
    parser.add_argument("--duration-sec", type=int, default=10)
    parser.add_argument("--period-us", type=int, default=10_000)
    parser.add_argument("--warmup-sec", type=int, default=5)
    parser.add_argument("--recovery-seconds", type=int, default=5)
    parser.add_argument("--source-settle-sec", type=float, default=10)
    parser.add_argument("--cooldown-sec", type=float, default=15)
    parser.add_argument("--seed", type=int, default=20261039)
    parser.add_argument("--probe-cpu", type=int, default=6)
    parser.add_argument("--timerlat-cpu", type=int, default=7)
    parser.add_argument("--load-cpus", type=str, default="1,2,3,4")
    parser.add_argument("--cpu-load-workers", type=int, default=4)
    parser.add_argument("--host-alias", default="worker-03")
    parser.add_argument("--clocksource-root", type=Path, default=DEFAULT_CLOCKSOURCE_ROOT)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument(
        "--capture-cpu-idle",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return parser


def _run_logged(command: list[str], log_path: Path) -> int:
    with log_path.open("wb") as log_stream:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return process.wait()
        except KeyboardInterrupt:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
            raise


def _restore_source(clocksource_root: Path, source: str) -> str:
    current_path = clocksource_root / "current_clocksource"
    current = current_path.read_text().strip()
    if current != source:
        current_path.write_text(f"{source}\n")
    observed = current_path.read_text().strip()
    if observed != source:
        raise RuntimeError(
            f"final clocksource restoration failed: expected {source!r}, observed {observed!r}"
        )
    return observed


def _campaign_command(args: argparse.Namespace, seed: int, data_dir: Path) -> list[str]:
    load_cpus = [int(value.strip()) for value in args.load_cpus.split(",") if value.strip()]
    command = [
        sys.executable,
        "-m",
        "experiments.run_timerlat_campaign",
        "--design",
        "observer",
        "--duration-sec",
        str(args.duration_sec),
        "--period-us",
        str(args.period_us),
        "--repeats",
        "1",
        "--seed",
        str(seed),
        "--warmup-sec",
        str(args.warmup_sec),
        "--recovery-seconds",
        str(args.recovery_seconds),
        "--probe-cpu",
        str(args.probe_cpu),
        "--timerlat-cpu",
        str(args.timerlat_cpu),
        "--load-cpus",
        ",".join(str(cpu) for cpu in load_cpus),
        "--cpu-load-workers",
        str(args.cpu_load_workers),
        "--host-alias",
        args.host_alias,
        "--data-dir",
        str(data_dir),
    ]
    if args.capture_cpu_idle:
        command.append("--capture-cpu-idle")
    return command


def run_comparison(args: argparse.Namespace) -> Path:
    if os.geteuid() != 0:
        raise RuntimeError("clocksource comparison requires root; run under sudo")
    if args.pairs < 3 or args.pairs > 20:
        raise ValueError("--pairs must be in 3..20 so paired intervals can be estimated")
    if args.duration_sec < 1 or args.duration_sec > 3600:
        raise ValueError("--duration-sec must be in 1..3600")
    if args.period_us < 100 or args.period_us > 10_000_000:
        raise ValueError("--period-us must be in 100..10000000")
    if args.warmup_sec < 0 or args.warmup_sec > 30:
        raise ValueError("--warmup-sec must be in 0..30")
    if args.recovery_seconds < 0 or args.recovery_seconds > 120:
        raise ValueError("--recovery-seconds must be in 0..120")
    if not 0 <= args.source_settle_sec <= 120:
        raise ValueError("--source-settle-sec must be in 0..120")
    if not 0 <= args.cooldown_sec <= 600:
        raise ValueError("--cooldown-sec must be in 0..600")
    load_cpus = [int(value.strip()) for value in args.load_cpus.split(",") if value.strip()]
    if not load_cpus or len(load_cpus) != args.cpu_load_workers:
        raise ValueError("--load-cpus must contain one CPU per --cpu-load-workers process")
    if len(load_cpus) != len(set(load_cpus)):
        raise ValueError("--load-cpus must not contain duplicates")
    requested_cpus = set(load_cpus) | {args.probe_cpu, args.timerlat_cpu}
    if args.probe_cpu == args.timerlat_cpu or args.probe_cpu in load_cpus or args.timerlat_cpu in load_cpus:
        raise ValueError("probe, timerlat and load CPUs must be disjoint")
    if not requested_cpus.issubset(os.sched_getaffinity(0)):
        raise ValueError(f"requested CPUs {sorted(requested_cpus)} must be online and available")

    clocksource_root = args.clocksource_root
    current_path = clocksource_root / "current_clocksource"
    available_path = clocksource_root / "available_clocksource"
    initial_source = current_path.read_text().strip()
    available = available_path.read_text().split()
    missing = sorted(set(args.sources) - set(available))
    if missing:
        raise ValueError(f"requested clocksources are unavailable: {missing}; choices are {available}")

    out = Path(args.data_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(out, 0o700)
    (out / "logs").mkdir(mode=0o700)

    randomizer = random.Random(args.seed)
    source_orders = []
    for pair in range(1, args.pairs + 1):
        order = list(args.sources)
        randomizer.shuffle(order)
        source_orders.append({"pair": pair, "order": order})

    now = datetime.now(timezone.utc)
    manifest: dict[str, Any] = {
        "schema": "clockpressure.clocksource-comparison.v1",
        "comparison_id": f"{now.strftime('%Y%m%dT%H%M%SZ')}-clocksource-{uuid.uuid4().hex[:8]}",
        "created_at_utc": now.isoformat().replace("+00:00", "Z"),
        "code_revision": _git_revision(),
        "host": snapshot_environment(args.host_alias),
        "clocksource": {
            "sysfs_root": str(clocksource_root),
            "initial": initial_source,
            "available": available,
            "requested_sources": args.sources,
            "selection_semantics": (
                "Linux system timekeeping source; software clock interfaces using it are related, "
                "and the selected source is not an independent elapsed-time reference"
            ),
        },
        "design": {
            "pairs": args.pairs,
            "source_orders": source_orders,
            "duration_sec": args.duration_sec,
            "period_us": args.period_us,
            "warmup_sec": args.warmup_sec,
            "recovery_seconds": args.recovery_seconds,
            "source_settle_sec": args.source_settle_sec,
            "cooldown_sec": args.cooldown_sec,
            "seed": args.seed,
            "arms": ["timerlat_disabled", "timerlat_user"],
            "conditions": ["baseline", "cpu_pressure", "recovery"],
            "probe_cpu": args.probe_cpu,
            "timerlat_cpu": args.timerlat_cpu,
            "load_cpus": load_cpus,
            "capture_cpu_idle": args.capture_cpu_idle,
            "external_elapsed_time_reference": None,
        },
        "runs": [],
        "status": "running",
        "data_dir": str(out),
    }
    manifest_path = out / "comparison.json"
    _write_json(manifest_path, manifest)

    run_index = 0
    try:
        for pair_spec in source_orders:
            for source in pair_spec["order"]:
                run_index += 1
                label = f"pair-{pair_spec['pair']:02d}-{source}"
                run_dir = out / label
                campaign_path = run_dir / "campaign.json"
                analysis_path = run_dir / "timerlat-campaign-analysis.json"
                log_path = out / "logs" / f"{label}.log"
                run_record: dict[str, Any] = {
                    "pair": pair_spec["pair"],
                    "clocksource": source,
                    "label": label,
                    "data_dir": str(run_dir),
                    "status": "starting",
                    "campaign_path": str(campaign_path.relative_to(out)),
                    "analysis_path": str(analysis_path.relative_to(out)),
                    "log_path": str(log_path.relative_to(out)),
                }
                manifest["runs"].append(run_record)
                _write_json(manifest_path, manifest)
                print(f"[{run_index}/{args.pairs * len(args.sources)}] pair={pair_spec['pair']} clocksource={source}", flush=True)

                selection = ClocksourceSelection(source, clocksource_root=clocksource_root)
                try:
                    with selection:
                        run_record["clocksource_selection"] = selection.record
                        run_record["status"] = "running"
                        _write_json(manifest_path, manifest)
                        if args.source_settle_sec:
                            time.sleep(args.source_settle_sec)
                        campaign_seed = args.seed + run_index
                        command = _campaign_command(args, campaign_seed, run_dir)
                        run_record["campaign_seed"] = campaign_seed
                        run_record["campaign_command"] = command
                        run_record["campaign_returncode"] = _run_logged(command, log_path)
                except KeyboardInterrupt:
                    run_record["status"] = "interrupted"
                    run_record["clocksource_selection"] = selection.record
                    _write_json(manifest_path, manifest)
                    raise
                except Exception as exc:
                    run_record["status"] = "failed"
                    run_record["error"] = f"{type(exc).__name__}: {exc}"
                    run_record["clocksource_selection"] = selection.record
                    _write_json(manifest_path, manifest)
                    raise

                run_record["clocksource_selection"] = selection.record
                if campaign_path.is_file():
                    campaign = json.loads(campaign_path.read_text())
                    run_record["campaign_status"] = campaign.get("status")
                    run_record["campaign_sha256"] = _sha256(campaign_path)
                    analysis_command = [sys.executable, "-m", "analysis.analyze_timerlat_campaign", str(campaign_path)]
                    run_record["analysis_returncode"] = _run_logged(
                        analysis_command,
                        log_path.with_name(f"{label}.analysis.log"),
                    )
                    if analysis_path.is_file():
                        run_record["analysis_sha256"] = _sha256(analysis_path)
                else:
                    run_record["campaign_status"] = "missing"
                    run_record["analysis_returncode"] = None

                run_complete = (
                    run_record.get("campaign_returncode") == 0
                    and run_record.get("campaign_status") == "complete"
                    and run_record.get("analysis_returncode") == 0
                    and analysis_path.is_file()
                    and run_record["clocksource_selection"].get("active") == source
                    and run_record["clocksource_selection"].get("restored") is True
                )
                run_record["status"] = "complete" if run_complete else "failed"
                _write_json(manifest_path, manifest)
                if not run_complete:
                    raise RuntimeError(f"clocksource run {label} did not complete cleanly; inspect {log_path}")
                if run_index < args.pairs * len(args.sources) and args.cooldown_sec:
                    time.sleep(args.cooldown_sec)
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        manifest["failure"] = "received interrupt; active timerlat cleanup and clocksource restoration were attempted"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["failure"] = f"{type(exc).__name__}: {exc}"
    else:
        manifest["status"] = "complete"
    finally:
        try:
            manifest["final_clocksource"] = _restore_source(clocksource_root, initial_source)
            manifest["clocksource_restored"] = manifest["final_clocksource"] == initial_source
        except Exception as exc:
            manifest["final_clocksource_restore_error"] = f"{type(exc).__name__}: {exc}"
            manifest["clocksource_restored"] = False
            if manifest["status"] == "complete":
                manifest["status"] = "failed"
                manifest["failure"] = manifest["final_clocksource_restore_error"]
        manifest["finished_at_utc"] = _utc_now()
        _write_json(manifest_path, manifest)
    print(manifest_path)
    return manifest_path


def main() -> int:
    args = build_parser().parse_args()
    try:
        manifest_path = run_comparison(args)
    except Exception as exc:
        print(f"clockpressure: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") == "complete":
        try:
            result = subprocess.run(
                [sys.executable, "-m", "analysis.analyze_clocksource_comparison", str(manifest_path)],
                cwd=ROOT,
                check=False,
            )
        except OSError as exc:
            print(f"clockpressure: could not analyze comparison: {exc}", file=sys.stderr)
            return 1
        return result.returncode
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
