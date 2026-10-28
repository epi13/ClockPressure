# Experiment protocol and first implementation

**State:** Initial bounded software-pilot protocol is implemented. Actual worker-03 execution is recorded separately in the [experimental journal](EXPERIMENT_JOURNAL.md). Do not treat this protocol or its configured limits as a measurement result.

## Initial pilot boundary

The first experiment measures Linux timer/scheduler behavior and internal clock relationships on the observed worker. It does **not** currently measure elapsed time against an independent external standard.

The native probe records absolute `CLOCK_MONOTONIC` timer deadlines and samples `CLOCK_MONOTONIC`, `CLOCK_MONOTONIC_RAW`, `CLOCK_BOOTTIME`, `CLOCK_REALTIME`, `CLOCK_TAI`, RDTSCP/AUX and, when readable, the `e1000e` NIC PHC. The first `CLOCK_MONOTONIC` read after each wake is compared to the absolute deadline. This is **timer delivery + scheduling + timestamp-acquisition latency**, not clock-rate error or a pure timer-interrupt latency. `CLOCK_MONOTONIC` begins each acquisition bracket and is read again after the other sources; the full bracket is retained. Inter-read gaps in `overhead.json` include userspace call/setup time and must not be described as isolated clock_gettime service cost.

The eBPF witness stores the kernel timestamp at `sched:sched_wakeup` for the probe TID and reports the next matching `sched:sched_switch`. This estimates runnable-to-running latency. It omits timer-expiry-to-wakeup time, shares the kernel monotonic dependency and is filtered to the target task. The source is `instrumentation/sched_wakeup.bt`; raw events and stderr are retained. Scheduler sample CPU IDs and TSC_AUX values provide migration diagnostics.

The pressure treatment is four bounded, CPU-bound workers pinned to CPUs 1–4 at nice `+10`. The probe is unpinned by default. The campaign starts with a baseline that has no ClockPressure-generated load, then seed-randomizes replicated baseline/pressure trials with eBPF on/off as requested. A recovery wait and no-load recovery measurement follow each pressure trial. Thermal, frequency, PSI and SenseTrace service-cgroup context are sampled once per second. The pilot aborts at 85°C CPU-package temperature. It does not change system-wide clocks, CPU limits, boot parameters or firmware.

Data defaults to a private directory outside the checkout, with per-run raw JSONL, a per-run manifest, artifact checksums and `.in-progress` preservation after failed/interrupted runs. A campaign sentinel baseline is deliberately collected before the randomized part; this protects the stated initial no-load baseline but means the sequence is not perfectly randomized. Subsequent baseline/pressure runs are randomized with the stored seed.

## General method

Use a preregistered matrix of control and bounded-pressure conditions. Preserve both raw timestamps and derived statistics. Keep the observation mechanism independent from the workload where feasible and characterize any observer impact.

### Phase A: readiness / preflight

1. Complete [worker-03 inventory](WORKER_03.md) and document node ownership and load permissions.
2. Choose the **device under test** (DUT) clock API / timer implementation and the **reference**. Record their dependency graphs.
3. Record clocksource, `clock_getres`, current time discipline, suspend policy and CPU power state.
4. Determine max permitted CPU load, memory pressure, storage write rate, run duration and temperature, plus immediate abort criteria.
5. Verify eBPF attachment privilege and kernel support *without changing* global settings or installing production-impacting hooks.
6. Calibrate timestamping overhead and reference synchronization / external event capture, if used.

### Phase B: pressure-free baseline

- Collect multiple runs without ClockPressure-generated work; log background services and PSI rather than asserting that the whole machine is idle.
- Record start/end readings, absolute timer wakeups, runnable-to-running latency, timestamp acquisition brackets, CPU/AUX distribution, available temperature/frequency, lost/malformed events, and observer overhead.
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

Use fixed resource ceilings, bounded durations, recovery periods, and randomized or counterbalanced condition ordering. Do not change system-wide time, kernel boot arguments, power limits, BIOS/UEFI or firmware as part of routine experiments. The first automated workload only saturates four explicitly pinned CPU cores at lower scheduling priority; it does not yet perform memory, I/O, voltage or clock-frequency interventions.

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

Probe names, structures, and privileges are checked on the target kernel. The first BPF program attaches only scheduler tracepoints and emits target-TID runnable-to-run records; it does not collect process arguments, names, user data or unrelated payloads. Check probe attach/detach, stderr, event counts and malformed lines. Compare eBPF-off/on trials because tracing itself perturbs scheduling.

## Analysis and interpretation

Compare internal endpoint rates in ppm only with their full dependency labels, and summarize timer wakeup lateness separately. The analysis reports run-level quantiles, robust exploratory latency outlier counts, the endpoint timestamp-bracket bound, per-run clock intervals, paired baseline-versus-pressure and eBPF-on/off differences, and descriptive bootstrap intervals when at least three run pairs exist. The bootstrap resamples independent run-pair summaries, never autocorrelated timer samples. Its interval is exploratory within one host/campaign and is not a calibration uncertainty budget. Report reference uncertainty, sample counts, run-to-run variability, exclusions and event-loss/malformed-record evidence. No current result can be called externally validated drift.

Predeclare primary comparisons and error thresholds in a versioned protocol revision **before** the relevant campaign. No arbitrary 1% success threshold is required. Distinguish exploratory correlation from experimentally supported causal mechanism. The first implemented protocol is intentionally small: CPU pressure, no-load/recovery controls, optional scheduler witness and internal clocks.

## Stop conditions

Abort on thermal / power alarms, unexpected shared-node load, data integrity problems, kernel instability, lost event budgets, excessive trace overhead, insufficient reference confidence, or inability to restore baseline. See [safety](SAFETY_AND_ETHICS.md).
