"""Summarize retained Linux timerlat tracefs output."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from analysis.analyze_runs import _quantiles


_LATENCY_LINE = re.compile(
    r"^\s*.+?-\d+\s+\[(?P<cpu>\d+)\].*?"
    r"#\s*(?P<activation>\d+)\s+context\s+(?P<kind>irq|thread|user-ret)"
    r"\s+timer_latency\s+(?P<latency>\d+)\s+ns\s*$"
)


def analyze_trace(path: Path) -> dict[str, Any]:
    values: dict[str, list[int]] = {"irq": [], "thread": [], "user_return": []}
    per_cpu: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: {"irq": [], "thread": [], "user_return": []}
    )
    activations: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    malformed = 0

    for line in path.read_text(errors="replace").splitlines():
        if "timer_latency" not in line:
            continue
        match = _LATENCY_LINE.match(line)
        if not match:
            malformed += 1
            continue
        cpu = match.group("cpu")
        kind = {"user-ret": "user_return"}.get(match.group("kind"), match.group("kind"))
        activation = int(match.group("activation"))
        latency = int(match.group("latency"))
        values[kind].append(latency)
        per_cpu[cpu][kind].append(latency)
        activations[(cpu, activation)][kind] += 1

    matched = sum(
        counts["irq"] == 1 and counts["thread"] == 1
        for counts in activations.values()
    )
    incomplete = sum(counts["irq"] != 1 or counts["thread"] != 1 for counts in activations.values())
    duplicate = sum(
        counts[kind] > 1
        for counts in activations.values()
        for kind in ("irq", "thread", "user_return")
    )
    return {
        "schema": "clockpressure.timerlat-analysis.v1",
        "source_trace": str(path),
        "clock_domain": "kernel timerlat tracer; not an independent elapsed-time reference",
        "latency_ns": {kind: _quantiles(samples) for kind, samples in values.items()},
        "latency_ns_by_cpu": {
            cpu: {kind: _quantiles(samples) for kind, samples in sorted(per_cpu[cpu].items())}
            for cpu in sorted(per_cpu, key=int)
        },
        "matched_irq_thread_activation_count": matched,
        "user_return_activation_count": sum(counts["user_return"] == 1 for counts in activations.values()),
        "incomplete_irq_thread_activation_count": incomplete,
        "duplicate_activation_event_count": duplicate,
        "malformed_latency_line_count": malformed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="trace file produced by the kernel timerlat tracer")
    args = parser.parse_args()
    report = analyze_trace(args.trace.expanduser().resolve())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
