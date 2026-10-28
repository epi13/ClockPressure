"""Drive one Linux timerlat_fd from a fixed-CPU userspace thread."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections import Counter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--fd-path", required=True)
    parser.add_argument("--reads", type=int, required=True)
    parser.add_argument("--fifo-priority", type=int, default=90)
    args = parser.parse_args()
    if args.cpu < 0 or args.reads < 1:
        parser.error("--cpu must be non-negative and --reads must be positive")
    if not 1 <= args.fifo_priority <= 99:
        parser.error("--fifo-priority must be in 1..99")

    interrupted = False

    def stop_requested(_signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGTERM, stop_requested)
    signal.signal(signal.SIGINT, stop_requested)

    started_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    read_lengths: Counter[int] = Counter()
    fd = -1
    completed = 0
    try:
        os.sched_setaffinity(0, {args.cpu})
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(args.fifo_priority))
        fd = os.open(args.fd_path, os.O_RDONLY)
        while completed < args.reads and not interrupted:
            payload = os.read(fd, 4096)
            read_lengths[len(payload)] += 1
            completed += 1
    except BaseException as exc:
        print(f"timerlat_user_worker: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if fd >= 0:
            os.close(fd)

    ended_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    print(
        json.dumps(
            {
                "schema": "clockpressure.timerlat-user-worker.v1",
                "cpu": args.cpu,
                "fifo_priority": args.fifo_priority,
                "requested_reads": args.reads,
                "completed_reads": completed,
                "read_return_length_counts": dict(sorted(read_lengths.items())),
                "interrupted": interrupted,
                "elapsed_monotonic_raw_ns": ended_ns - started_ns,
                "clock_domain": "worker host CLOCK_MONOTONIC_RAW; not independent",
            },
            sort_keys=True,
        )
    )
    return 0 if not interrupted and completed == args.reads else 2


if __name__ == "__main__":
    raise SystemExit(main())
