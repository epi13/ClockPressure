"""Bounded CPU load pinned to an explicit CPU list."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import signal
import sys
import time


def _burn(cpu: int, stop: mp.synchronize.Event) -> None:
    os.sched_setaffinity(0, {cpu})
    os.setpriority(os.PRIO_PROCESS, 0, 10)
    value = (0x9E3779B97F4A7C15 ^ cpu) & ((1 << 64) - 1)
    while not stop.is_set():
        value = (value * 0x5851F42D4C957F2D + 0x14057B7EF767814F) & ((1 << 64) - 1)
    # Retain a data-dependent result in the child so this remains real CPU work.
    sys.exit(0 if value >= 0 else 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpus", required=True, help="comma-separated CPU IDs")
    args = parser.parse_args()
    try:
        cpus = sorted({int(cpu) for cpu in args.cpus.split(",") if cpu.strip()})
    except ValueError:
        parser.error("--cpus must be a comma-separated list of CPU IDs")
    if not cpus or any(cpu < 0 for cpu in cpus):
        parser.error("--cpus must contain at least one non-negative CPU ID")
    available = os.cpu_count() or 1
    if any(cpu >= available for cpu in cpus):
        parser.error(f"CPU IDs must be below the online CPU count ({available})")

    stop = mp.Event()
    children = [mp.Process(target=_burn, args=(cpu, stop), name=f"burn-cpu-{cpu}") for cpu in cpus]

    def stop_children(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, stop_children)
    signal.signal(signal.SIGINT, stop_children)
    for child in children:
        child.start()
    print(
        json.dumps(
            {
                "event": "load_started",
                "clock_id": "CLOCK_MONOTONIC_RAW",
                "monotonic_raw_ns": time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW),
                "cpus": cpus,
                "worker_pids": [child.pid for child in children],
                "workers": len(children),
                "worker_nice": 10,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    while not stop.wait(0.1):
        if any(not child.is_alive() for child in children):
            stop.set()
            break
    for child in children:
        child.join(timeout=2)
    for child in children:
        if child.is_alive():
            child.terminate()
            child.join(timeout=1)
    print(
        json.dumps(
            {
                "event": "load_stopped",
                "clock_id": "CLOCK_MONOTONIC_RAW",
                "monotonic_raw_ns": time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW),
                "exit_codes": [child.exitcode for child in children],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if all(child.exitcode == 0 for child in children) else 1


if __name__ == "__main__":
    raise SystemExit(main())
