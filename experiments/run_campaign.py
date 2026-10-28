"""Counterbalanced baseline and CPU-pressure experiment campaign."""

from __future__ import annotations

import argparse
import json
import os
import random
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

from experiments.run_trial import _parse_cpus, _write_json

TRIAL = ROOT / "experiments" / "run_trial.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-sec", type=int, default=30)
    parser.add_argument("--period-us", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=3, help="replicates per condition / observer pair")
    parser.add_argument("--cpu-load-workers", type=int, default=4)
    parser.add_argument("--load-cpus", type=_parse_cpus, default=_parse_cpus("1,2,3,4"))
    parser.add_argument("--pin-cpu", type=int, default=-1)
    parser.add_argument("--observer", choices=("off", "on", "both"), default="both")
    parser.add_argument("--recovery-seconds", type=int, default=5)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--host-alias", default="worker-03")
    parser.add_argument("--data-dir", default="~/clockpressure-data")
    return parser


def _trial_command(
    args: argparse.Namespace,
    condition: str,
    observer: str,
    data_dir: Path,
    campaign_id: str,
    replicate: int,
    role: str,
    recovery_seconds: int | None = None,
) -> list[str]:
    workers = args.cpu_load_workers if condition == "cpu_pressure" else 0
    command = [
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
        ",".join(str(cpu) for cpu in args.load_cpus),
        "--pin-cpu",
        str(args.pin_cpu),
        "--observer",
        observer,
        "--host-alias",
        args.host_alias,
        "--data-dir",
        str(data_dir / "runs"),
        "--campaign-id",
        campaign_id,
        "--replicate",
        str(replicate),
        "--campaign-role",
        role,
    ]
    if recovery_seconds is not None:
        command += ["--warmup-sec", str(recovery_seconds)]
    return command


def main() -> int:
    args = build_parser().parse_args()
    if args.duration_sec < 1 or args.duration_sec > 3600:
        raise SystemExit("--duration-sec must be in 1..3600")
    if args.period_us < 100 or args.period_us > 10_000_000:
        raise SystemExit("--period-us must be in 100..10000000")
    if args.repeats < 1 or args.repeats > 100:
        raise SystemExit("--repeats must be in 1..100")
    if args.cpu_load_workers != len(args.load_cpus):
        raise SystemExit("provide one --load-cpus entry for each --cpu-load-workers process")
    if args.pin_cpu in args.load_cpus:
        raise SystemExit("--pin-cpu must not overlap a CPU pressure worker")
    if args.recovery_seconds < 0 or args.recovery_seconds > 120:
        raise SystemExit("--recovery-seconds must be in 0..120")

    output = Path(args.data_dir).expanduser().resolve()
    (output / "campaigns").mkdir(parents=True, exist_ok=True, mode=0o700)
    (output / "runs").mkdir(parents=True, exist_ok=True, mode=0o700)
    observers = {
        "off": ["none"],
        "on": ["sched_bpf"],
        "both": ["none", "sched_bpf"],
    }[args.observer]
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1 << 63)
    randomizer = random.Random(seed)
    jobs = [
        (condition, observer, replicate)
        for replicate in range(1, args.repeats + 1)
        for condition in ("baseline", "cpu_pressure")
        for observer in observers
    ]
    # Obtain a pressure-free, uninstrumented anchor before any CPU stress.
    sentinel = ("baseline", "none", 0)
    randomizer.shuffle(jobs)
    campaign_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-campaign-{uuid.uuid4().hex[:8]}"
    campaign_path = output / "campaigns" / f"{campaign_id}.json"
    campaign: dict[str, Any] = {
        "schema": "clockpressure.campaign.v1",
        "campaign_id": campaign_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "protocol_version": "initial-pilot-v1",
        "seed": seed,
        "requested_order": [
            {"condition": sentinel[0], "observer": sentinel[1], "replicate": sentinel[2], "role": "initial_baseline"},
            *(
                {"condition": cond, "observer": obs, "replicate": rep, "role": "randomized_trial"}
                for cond, obs, rep in jobs
            ),
        ],
        "recovery_seconds_after_pressure": args.recovery_seconds,
        "trials": [],
        "status": "running",
    }
    _write_json(campaign_path, campaign)

    plan = [
        (sentinel[0], sentinel[1], sentinel[2], "initial_baseline"),
        *[(condition, observer, replicate, "randomized_trial") for condition, observer, replicate in jobs],
    ]
    for ordinal, (condition, observer, replicate, role) in enumerate(plan, start=1):
        print(
            f"[{ordinal}/{len(plan)}] {role}: {condition}, observer={observer}, replicate={replicate}",
            flush=True,
        )
        command = _trial_command(
            args, condition, observer, output, campaign_id, replicate, role
        )
        started = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        ended = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
        entry: dict[str, Any] = {
            "ordinal": ordinal,
            "role": role,
            "condition": condition,
            "observer": observer,
            "replicate": replicate,
            "orchestration_clock": "CLOCK_MONOTONIC_RAW",
            "orchestration_start_ns": started,
            "orchestration_end_ns": ended,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr[-4000:],
            "command": command,
        }
        campaign["trials"].append(entry)
        if result.returncode != 0:
            campaign["status"] = "failed"
            campaign["failure"] = f"trial {ordinal} exited with {result.returncode}"
            break

        if condition == "cpu_pressure":
            if args.recovery_seconds:
                recovery_start = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
                time.sleep(args.recovery_seconds)
                recovery_end = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
            else:
                recovery_start = recovery_end = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
            recovery_command = _trial_command(
                args,
                "recovery",
                "none",
                output,
                campaign_id,
                replicate,
                "post_pressure_recovery",
                recovery_seconds=0,
            )
            print(f"[{ordinal}/{len(plan)}] recovery observation, observer=none", flush=True)
            recovery_result = subprocess.run(
                recovery_command, check=False, capture_output=True, text=True
            )
            campaign["trials"].append(
                {
                    "ordinal": f"{ordinal}.recovery",
                    "role": "post_pressure_recovery",
                    "condition": "recovery",
                    "observer": "none",
                    "paired_pressure_ordinal": ordinal,
                    "recovery_wait_start_ns": recovery_start,
                    "recovery_wait_end_ns": recovery_end,
                    "returncode": recovery_result.returncode,
                    "stdout": recovery_result.stdout.strip(),
                    "stderr": recovery_result.stderr[-4000:],
                    "command": recovery_command,
                }
            )
            if recovery_result.returncode != 0:
                campaign["status"] = "failed"
                campaign["failure"] = f"recovery trial after {ordinal} exited with {recovery_result.returncode}"
                break
        _write_json(campaign_path, campaign)

    if campaign["status"] == "running":
        campaign["status"] = "complete"
    campaign["finished_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_json(campaign_path, campaign)
    print(campaign_path)
    return 0 if campaign["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
