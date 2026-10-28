# Research questions and falsifiable hypotheses

## Goal and scope

Investigate whether observable runtime pressure can cause timing measurements to disagree with independently established elapsed time, and whether the discrepancy can invalidate a timing-based software contract. ClockPressure is not an effort to assert that CPU load normally slows modern Linux clocks.

Primary question: **Can a measured workload alter or exploit the measurement process used to judge that same workload?**

## Distinct testable hypotheses

| ID | Hypothesis | Counterevidence / falsification |
| --- | --- | --- |
| H0 | On the tested host, kernel monotonic elapsed time remains accurate within measured uncertainty under bounded pressure. | Repeated external-reference discrepancies exceeding calibrated uncertainty and confounder limits |
| H1 | Under pressure, software-loop tick accounting can systematically undercount elapsed time. | Properly controlled loop shows no undercount beyond measurement uncertainty |
| H2 | Timer wakeups and scheduling exhibit increased latency under pressure without corresponding hardware clock-rate error. | No reproducible latency change, or independent measurement shows actual clock-rate error |
| H3 | A particular host / virtualization / firmware state causes real clock-rate discrepancy under bounded pressure. | Discrepancy disappears with independent control / is explained by offset, suspend, clock adjustment, or timestamp delay |
| H4 | A timing contract can report a false pass because its measurement authority is inadequate. | An independently anchored contract evaluator agrees with intended elapsed-time outcome within uncertainty |

These are competing or overlapping possibilities, not predetermined conclusions. H1 is a useful *positive control*, but does not establish H3. A null H3 result is publishable.

## Candidate causal pathways

- Scheduler delays and lost / delayed software ticks.
- Interrupt and timer-event delivery latency (not intrinsically clocksource slowdown).
- CPU clock / power states and clocksource calibration or platform quirks.
- Thermal and electrical changes coupling into physical reference sources.
- Firmware transitions including SMI/SMM on relevant architectures.
- Virtualized clocksource behavior and guest/host timing differences.
- NTP / PTP discipline, time namespace offsets, clock adjustments and suspend / resume.

A candidate pathway is only a **hypothesis** until it is measured. Hardware counters, OS monotonic time, and eBPF timestamps may have shared dependencies.

## Confounders to log or control

- Process preemption and timestamp-read latency at both measurement endpoints.
- Host versus guest / hypervisor status, CPU migration, affinity, and TSC synchronization.
- CPU thermal / power states, throttling, governor, frequency, and temperature where observable.
- Synchronized clock adjustments, leap behavior, NTP state, and `adjtimex`.
- System suspend, clocksource switches, boot / kernel changes and sampling overhead.
- eBPF event loss, ring-buffer backpressure and tracing overhead.
- Workload correctness, caching, warmup, repeat order, and ambient node activity.
- Clock reference error, calibration traceability, common-mode failure and external-capture latency.

## Predeclared criteria for noteworthy evidence

1. A **reproducible** difference between measured and intended outcomes, with the sign and magnitude recorded.
2. An independent measurement chain whose hardware, oscillator / synchronization lineage, timestamping path, and uncertainty are documented.
3. A control demonstrating whether the effect survives accounting for scheduler delay, endpoint timestamp latency, NTP discipline, and suspend.
4. Replication across sessions with an unmodified comparison configuration and full raw artifacts.
5. A clear description of which assertion is justified: *wakeup jitter*, *software-timer accounting error*, *cross-clock disagreement*, *externally verified clock-rate error*, or *false contract pass*.

Do not turn a 1% target into an evidentiary threshold: report whatever is observed, including smaller effects and non-detections, with uncertainty and confidence intervals. Exploratory analyses must be labeled exploratory.
