"""A deterministic software accounting defect and a separate evaluator."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TICKS = 40
ASSUMED_TICK_NS = 10_000_000
ACTUAL_SLEEP_NS = 20_000_000
DEADLINE_NS = 500_000_000


def _subject() -> int:
    ticks = 0
    for _ in range(TICKS):
        # Deliberate accounting defect: the implementation assumes each
        # 20 ms wait represents a 10 ms tick.
        time.sleep(ACTUAL_SLEEP_NS / 1_000_000_000)
        ticks += 1
    print(json.dumps({"tick_count": ticks, "reported_elapsed_ns": ticks * ASSUMED_TICK_NS}))
    return 0


def demonstrate() -> dict[str, Any]:
    script = str(Path(__file__).resolve())
    raw_start = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    monotonic_start = time.monotonic_ns()
    completed = subprocess.run(
        [sys.executable, script, "--subject"], check=True, capture_output=True, text=True
    )
    monotonic_end = time.monotonic_ns()
    raw_end = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
    subject = json.loads(completed.stdout)
    raw_elapsed = raw_end - raw_start
    monotonic_elapsed = monotonic_end - monotonic_start
    reported = subject["reported_elapsed_ns"]
    weak_pass = reported <= DEADLINE_NS
    strong_pass = raw_elapsed <= DEADLINE_NS
    result = {
        "label": "synthetic positive control",
        "contract": {
            "requirement": "complete the child process within 500 ms of evaluator launch",
            "deadline_ns": DEADLINE_NS,
        },
        "implementation": {
            "tick_count": subject["tick_count"],
            "assumed_tick_ns": ASSUMED_TICK_NS,
            "actual_sleep_ns_per_tick": ACTUAL_SLEEP_NS,
            "mechanism": "software timer accounting assumes a tick duration half the actual wait",
        },
        "weak_evaluator_reported_elapsed_ns": reported,
        "weak_evaluator_pass": weak_pass,
        "strong_evaluator_clock": "CLOCK_MONOTONIC_RAW in supervising parent process",
        "strong_evaluator_elapsed_ns": raw_elapsed,
        "same_host_monotonic_elapsed_ns": monotonic_elapsed,
        "strong_evaluator_pass": strong_pass,
        "intended_contract_pass": strong_pass,
        "interpretation": (
            "The false pass is constructed by a known software accounting bug. "
            "The parent uses a different measurement authority, but both clocks "
            "remain on the same host and this is not an external time standard."
        ),
    }
    if not weak_pass or strong_pass or raw_elapsed <= DEADLINE_NS:
        raise RuntimeError(f"positive control failed to separate its outcomes: {result}")
    return result


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--subject":
        return _subject()
    print(json.dumps(demonstrate(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
