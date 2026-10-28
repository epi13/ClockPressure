"""Join per-CPU cpuidle transitions to timerlat IRQ events in one ftrace stream."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from analysis.analyze_runs import _quantiles


_TRACE_PREFIX = r"^\s*.+?-\d+\s+\[(?P<header_cpu>\d+)\].*?(?P<timestamp>\d+\.\d+):\s+"
_CPU_IDLE_LINE = re.compile(
    _TRACE_PREFIX
    + r"cpu_idle:\s+state=(?P<state>\d+)\s+cpu_id=(?P<event_cpu>\d+)\s*$"
)
_TIMERLAT_IRQ_LINE = re.compile(
    _TRACE_PREFIX
    + r"#\s*(?P<activation>\d+)\s+context\s+irq\s+timer_latency\s+"
    + r"(?P<latency>\d+)\s+ns\s*$"
)
_IDLE_EXIT = 0xFFFFFFFF
_NS_PER_SECOND = Decimal(1_000_000_000)
POST_EXIT_MATCH_LOOKBACK_NS = 25_000


def analyze_idle_transitions(
    path: Path,
    *,
    cpu: int,
    state_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Associate timerlat IRQs with the adjacent cpu_idle interval on the same CPU.

    Both event types are read from the same CPU-local ftrace stream. The trace
    clock is an observation domain, not an independent elapsed-time reference.
    Linux may emit the cpu_idle exit event just before the timerlat IRQ event,
    so an IRQ may be joined to the immediately preceding completed interval
    when it follows the exit by no more than the bounded lookback window.
    """
    names = state_names or {}
    events: list[tuple[Decimal, int, str, dict[str, int]]] = []
    idle_event_count = 0
    irq_event_count = 0
    malformed_idle_event_count = 0

    for line_number, line in enumerate(path.read_text(errors="replace").splitlines()):
        idle_match = _CPU_IDLE_LINE.match(line)
        if idle_match:
            header_cpu = int(idle_match.group("header_cpu"))
            event_cpu = int(idle_match.group("event_cpu"))
            if header_cpu != cpu and event_cpu != cpu:
                continue
            if header_cpu != cpu or event_cpu != cpu:
                malformed_idle_event_count += 1
                continue
            events.append(
                (
                    Decimal(idle_match.group("timestamp")),
                    line_number,
                    "cpu_idle",
                    {"state": int(idle_match.group("state"))},
                )
            )
            idle_event_count += 1
            continue

        irq_match = _TIMERLAT_IRQ_LINE.match(line)
        if irq_match:
            if int(irq_match.group("header_cpu")) != cpu:
                continue
            events.append(
                (
                    Decimal(irq_match.group("timestamp")),
                    line_number,
                    "timerlat_irq",
                    {
                        "activation": int(irq_match.group("activation")),
                        "latency_ns": int(irq_match.group("latency")),
                    },
                )
            )
            irq_event_count += 1

    events.sort(key=lambda event: (event[0], event[1]))

    current_state: int | None = None
    state_entry_timestamp: Decimal | None = None
    last_completed_interval: tuple[int, Decimal, Decimal] | None = None
    entries_by_state: dict[int, list[int]] = defaultdict(list)
    intervals_by_state: dict[int, list[int]] = defaultdict(list)
    activations_by_state: dict[int, list[int]] = defaultdict(list)
    entry_to_irq_by_state: dict[int, list[int]] = defaultdict(list)
    post_exit_to_irq_by_state: dict[int, list[int]] = defaultdict(list)
    phase_counts_by_state: dict[int, dict[str, int]] = defaultdict(
        lambda: {"while_idle_state_open": 0, "after_idle_exit": 0}
    )
    unmatched_idle_exit_count = 0
    overlapping_idle_entry_count = 0
    incomplete_idle_interval_count = 0
    unmatched_timerlat_irq_count = 0

    for timestamp, _line_number, kind, fields in events:
        if kind == "cpu_idle":
            state = fields["state"]
            if state == _IDLE_EXIT:
                if current_state is None or state_entry_timestamp is None:
                    unmatched_idle_exit_count += 1
                    continue
                duration_ns = int((timestamp - state_entry_timestamp) * _NS_PER_SECOND)
                if duration_ns < 0:
                    incomplete_idle_interval_count += 1
                else:
                    intervals_by_state[current_state].append(duration_ns)
                    last_completed_interval = (current_state, state_entry_timestamp, timestamp)
                current_state = None
                state_entry_timestamp = None
                continue

            if current_state is not None:
                overlapping_idle_entry_count += 1
                incomplete_idle_interval_count += 1
            last_completed_interval = None
            current_state = state
            state_entry_timestamp = timestamp
            continue

        if current_state is not None and state_entry_timestamp is not None:
            elapsed_ns = int((timestamp - state_entry_timestamp) * _NS_PER_SECOND)
            if elapsed_ns >= 0:
                entries_by_state[current_state].append(fields["latency_ns"])
                entry_to_irq_by_state[current_state].append(elapsed_ns)
                phase_counts_by_state[current_state]["while_idle_state_open"] += 1
                continue

        if last_completed_interval is not None:
            completed_state, entry_timestamp, exit_timestamp = last_completed_interval
            after_exit_ns = int((timestamp - exit_timestamp) * _NS_PER_SECOND)
            if 0 <= after_exit_ns <= POST_EXIT_MATCH_LOOKBACK_NS:
                entries_by_state[completed_state].append(fields["latency_ns"])
                entry_to_irq_by_state[completed_state].append(
                    int((timestamp - entry_timestamp) * _NS_PER_SECOND)
                )
                post_exit_to_irq_by_state[completed_state].append(after_exit_ns)
                phase_counts_by_state[completed_state]["after_idle_exit"] += 1
                last_completed_interval = None
                continue

        unmatched_timerlat_irq_count += 1

    open_idle_interval_at_trace_end = current_state is not None
    state_summaries = []
    for state in sorted(set(entries_by_state) | set(intervals_by_state)):
        state_summaries.append(
            {
                "state_id": state,
                "state_name": names.get(state, f"state{state}"),
                "timerlat_irq_activations": len(entries_by_state[state]),
                "timerlat_irq_latency_ns": _quantiles(entries_by_state[state]),
                "timerlat_irq_phase_counts": phase_counts_by_state[state],
                "trace_entry_to_irq_ns": _quantiles(entry_to_irq_by_state[state]),
                "trace_exit_to_irq_ns": _quantiles(post_exit_to_irq_by_state[state]),
                "completed_idle_intervals": len(intervals_by_state[state]),
                "trace_entry_to_exit_ns": _quantiles(intervals_by_state[state]),
            }
        )

    matched_activations = sum(len(values) for values in entries_by_state.values())
    completed_intervals = sum(len(values) for values in intervals_by_state.values())
    return {
        "schema": "clockpressure.idle-transition-analysis.v1",
        "cpu": cpu,
        "clock_domain": "same-CPU ftrace timestamp stream; not an independent elapsed-time reference",
        "idle_exit_sentinel": _IDLE_EXIT,
        "post_exit_match_lookback_ns": POST_EXIT_MATCH_LOOKBACK_NS,
        "timerlat_irq_events": irq_event_count,
        "matched_idle_state_activations": matched_activations,
        "matched_while_idle_state_open": sum(
            phases["while_idle_state_open"] for phases in phase_counts_by_state.values()
        ),
        "matched_after_idle_exit": sum(
            phases["after_idle_exit"] for phases in phase_counts_by_state.values()
        ),
        "unmatched_timerlat_irq_events": unmatched_timerlat_irq_count,
        "cpu_idle_events": idle_event_count,
        "completed_idle_intervals": completed_intervals,
        "unmatched_idle_exits": unmatched_idle_exit_count,
        "overlapping_idle_entries": overlapping_idle_entry_count,
        "incomplete_idle_intervals": incomplete_idle_interval_count,
        "open_idle_interval_at_trace_end": open_idle_interval_at_trace_end,
        "malformed_cpu_idle_events": malformed_idle_event_count,
        "per_state": state_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--cpu", type=int, required=True)
    parser.add_argument("--state-names-json", type=Path)
    args = parser.parse_args()
    names = {}
    if args.state_names_json:
        raw_names = json.loads(args.state_names_json.read_text())
        names = {int(key): str(value) for key, value in raw_names.items()}
    report = analyze_idle_transitions(args.trace, cpu=args.cpu, state_names=names)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
