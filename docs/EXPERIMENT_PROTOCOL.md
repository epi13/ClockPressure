# Experiment protocol (initial proposal)

**State:** Proposed, not executed. Do not treat illustrative timings as measured worker-03 results.

## General method

Use a preregistered matrix of control and bounded-pressure conditions. Preserve both raw timestamps and derived statistics. Keep the observation mechanism independent from the workload where feasible and characterize any observer impact.

### Phase A: readiness / preflight

1. Complete [worker-03 inventory](WORKER_03.md) and document node ownership and load permissions.
2. Choose the **device under test** (DUT) clock API / timer implementation and the **reference**. Record their dependency graphs.
3. Record clocksource, `clock_getres`, current time discipline, suspend policy and CPU power state.
4. Determine max permitted CPU load, memory pressure, storage write rate, run duration and temperature, plus immediate abort criteria.
5. Verify eBPF attachment privilege and kernel support *without changing* global settings or installing production-impacting hooks.
6. Calibrate timestamping overhead and reference synchronization / external event capture, if used.

### Phase B: idle baseline

- Collect multiple runs at idle with fixed acquisition duration and repeatable start / stop markers.
- Record DUT / reference start and end, timer wakeups, scheduling latency quantiles, CPU utilization, available temperature/frequency, lost events, and sampling overhead.
- Run the same measurement with eBPF off, then on, to estimate observer effect.
- Record ambient workload and timestamps of any clock adjustments or node configuration changes.

### Phase C: software-accounting positive control

- Demonstrate the *known* failure mode: tick-based accounting that increments fixed time per iteration while timer wakeups are delayed.
- Compare it with start/end measurements from `CLOCK_MONOTONIC` and `CLOCK_MONOTONIC_RAW`.
- Use a modest controlled workload; show both the intended elapsed-time outcome and the flawed reported outcome.
- Label this a **constructed example**, never a hardware clock anomaly.

### Phase D: bounded pressure matrix

Proposed factors (each independently, then small selected combinations where safe):

| Factor | Observable candidate | Control |
| --- | --- | --- |
| CPU scheduling contention | Wakeup lateness, preemption, tail latency | Same measurement without competing task |
| Memory / cache pressure | Scheduling / timestamp-read latency | Equal elapsed duration and bounded allocation |
| I/O / IRQ activity | Latency distribution, delayed events | Controlled device activity within wear / throughput limits |
| CPU power / thermal state | Cross-clock discrepancy or timing changes | Log governor, temperature, throttling, steady-state |
| Guest / host timekeeping (if applicable) | Cross-boundary clock disagreement | Explicitly identify virtualized versus bare-metal source |

Use fixed resource ceilings, bounded durations, recovery periods, and randomized or counterbalanced condition ordering. Do not change system-wide time, kernel boot arguments, power limits, BIOS/UEFI or firmware as part of routine experiments.

### Phase E: cross-clock comparison

- Compare DUT readings from identical event boundaries.
- Contrast `CLOCK_MONOTONIC`, `CLOCK_MONOTONIC_RAW`, and where appropriate `CLOCK_BOOTTIME` as **internal diagnostics**, not independent proof.
- Check if differences track NTP / PTP discipline or suspend.
- For genuine rate error claims, repeat against a documented **external** instrument / reference with an independent time base and validated capture latency.
- Investigate outliers: timestamp path delay, dropped events, CPU migration, clocksource failover and drift-versus-offset.

### Phase F: recovery and replication

- Allow system to recover and repeat baseline.
- Replicate on a separate boot / session, preserving tool versions and configuration.
- Analyze within-run and between-run variation; do not select only favorable runs.
- Save negative outcomes and aborts.

## Suggested eBPF observation (subject to hook availability)

- Scheduler switches / wakeups / task runtime from stable tracepoints if available.
- IRQ / softirq / timer tracepoints where available.
- Counters for probe invocation, event drop, ring buffer utilization and lost samples.
- Optional sampled CPU or kernel trace context rather than exhaustive per-event logging.

Probe names, structures, and privileges must be checked on the real kernel; no BPF implementation or host probes are currently claimed. Watch for tracing overhead, probe perturbation, and loss. Avoid capturing user data, process arguments, or payloads not needed for the hypothesis.

## Analysis and interpretation

Calculate each run's signed rate error and corresponding ppm using [clock model](CLOCKS_AND_INDEPENDENCE.md). Summarize timer wakeup lateness separately from clock-rate error; give distribution quantiles, sample counts, repeat-to-repeat variability, reference uncertainty, excluded runs with reasons, and data-loss counters.

Predeclare primary comparisons and error thresholds in a versioned protocol revision **before** experimental collection. No arbitrary 1% success threshold is required. Distinguish exploratory correlation from experimentally supported causal mechanism.

## Stop conditions

Abort on thermal / power alarms, unexpected shared-node load, data integrity problems, kernel instability, lost event budgets, excessive trace overhead, insufficient reference confidence, or inability to restore baseline. See [safety](SAFETY_AND_ETHICS.md).
