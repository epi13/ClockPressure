# Experimental journal

This journal separates implementation and test results from measurements performed on worker-03. Code behavior verified locally does not count as a hardware observation. SenseTrace results are cited only as prior environment/capability context, never as ClockPressure measurements.

## 2026-10-28 — Initial instrumentation and worker inventory

### Implemented

- Added a native absolute-`CLOCK_MONOTONIC` sampler for wakeup lateness and endpoint intervals across MONOTONIC, RAW, BOOTTIME, REALTIME, TAI, RDTSCP/AUX, CPU IDs and optional NIC PHC.
- Added a clock-read pair-gap probe, a target-TID bpftrace scheduler witness, bounded pinned CPU workers, per-second thermal/frequency/PSI telemetry, randomized campaign orchestration, checksummed raw run manifests and deterministic analysis.
- Added a synthetic software timer positive control with a parent-process `CLOCK_MONOTONIC_RAW` deadline evaluator.
- Inventoried worker-03 hardware/firmware/timekeeping candidates in [WORKER_03.md](WORKER_03.md). The existing unattended SenseTrace service was observed and left untouched.

### Validation performed

- `make clean check`: passed 6 unit/integration checks, including a one-second native probe run and positive-control separation; compiled with GCC `-Wall -Wextra -Wpedantic -Werror`.
- The local native clock-pair test reported roughly 12–30 ns median inter-read gaps on this **development machine**. This is not worker-03 data and is not an isolated vDSO/kernel call cost.
- The software positive control reported 400 ms to its weak evaluator and about 853 ms to its parent `CLOCK_MONOTONIC_RAW` observer for a 500 ms contract. This is a synthetic software accounting false pass, not a host clock anomaly.
- No ClockPressure experiment had yet run on worker-03 at the time this entry was written.

### Observed worker environment

- Fedora 43, kernel 6.17.1, bare-metal Intel Core i7-9700, eight cores, selected `tsc`, secondary `acpi_pm`, APIC deadline clock events and an e1000e I219-LM PHC candidate.
- BTF, tracefs, scheduler/timer/IRQ/power tracepoints, bpftool and bpftrace are available. Actual ClockPressure eBPF attachment remains to be tested.
- The SenseTrace systemd runner is active but observed at 0.0% CPU over a five-second spot check with no child processes; we will measure its cgroup counters and keep CPU workers at nice +10.

### What this supports and does not support

- **Supports:** the native prototype builds locally, the timing schema and event parser work in integration checks, the controlled software-accounting example passes/fails as designed, and worker-03 has useful Linux observability plus an uncalibrated NIC-PHC candidate.
- **Does not support:** any worker-03 rate/jitter observation, actual eBPF event capture by ClockPressure, independent clock validation, physical oscillator effects, a natural contract false pass, or agent reward hacking.

### Next

1. Deploy the committed code to worker-03 and validate PTP reads and eBPF attachment with a short no-load trial.
2. Run randomized no-load / four-core CPU-pressure / recovery repetitions with eBPF off/on and retained raw events.
3. Compare timer wakeup and scheduler latency distributions separately from MONOTONIC–RAW and PHC rate relationships. Check pressure, thermal, frequency, migration and SenseTrace-service context.
4. Follow only effects that survive the endpoint read-bracket bounds. If PHC cross-comparison remains promising, characterize drift, capture latency and synchronization before treating it as an independent witness.

## 2026-10-28 — First worker-03 baseline / CPU-pressure campaign

### Implemented and validated

- Ran the first randomized worker campaign from source revision `53e47bcfd89244dd0be9f60dac8c536829400127`: 20-second trials at 100 samples/s, three baseline and three CPU-pressure replicates, scheduler eBPF both off and on, plus an initial baseline sentinel and six post-pressure recovery observations. Four `nice +10` workers were pinned to CPUs 1–4. The campaign completed all 19 runs.
- The campaign preserved 38,000 timer samples, all 38,038 ordinary PHC endpoint/sample reads were valid, six BPF traces contained 12,012 target runnable-to-run events, and all per-run artifact checksums verified. The analyzer now ignores blank trailing bpftrace output lines rather than mislabeling them as malformed records.
- Ran the software-accounting positive control on worker-03: the child reported 400 ms and passed a 500 ms deadline; the parent `CLOCK_MONOTONIC_RAW` measurement was 843.248 ms and failed it. This remains a constructed accounting bug, not a host clock effect.
- Confirmed that worker-03 accepts the Linux `PTP_SYS_OFFSET_PRECISE` ioctl. A 10,000-call exploratory check had a 24.9 µs median and 50.7 µs p99 outer `CLOCK_MONOTONIC_RAW` bracket; device-minus-paired-MONORAW offset spread was 161 ns over the rapid batch. These aggregate values were observed but the individual pairs were not retained, so this check is diagnostic only and not part of the campaign findings.
- Expanded the probe to retain paired PHC/MONORAW/REALTIME values and added per-CPU cpuidle residency collection/analysis. On worker-03 revision `af1f22cf8e485f115ab67ce602b8c2f7bab0be95`, a five-second scheduler-observed smoke run recorded 502 valid cross-timestamps, all eight CPUs' idle states, 502 scheduler events, and zero checksum failures. The paired endpoint rate was −0.2982 ppm; fitting the retained offset series gave −0.2975 ppm, with 1,550 ns total offset span and 43.5 ns p95 absolute residual. Its `PTP_SYS_OFFSET_PRECISE` outer bracket was 24.7 µs median, 25.4 µs p95 and 50.5 µs p99. Per-CPU C10 residency was 94.0% across the telemetry window. These are brief baseline smoke observations; they do not establish a load effect or a calibration bound.
- The first smoke exposed an unsorted PTP-precise overhead sample array; sorted it before percentile reporting and verified monotonic quantiles in the rerun. `make clean check` now passes 12 checks with GCC `-Wall -Wextra -Wpedantic -Werror`. The PHC/idle-state paths are smoke-validated, while the longer randomized follow-up is still pending.

### Observed

- The ordinary PHC versus RAW comparison had a 20-second endpoint read-bracket bound of about 1.2–2.3 ppm per run. Median PHC-minus-RAW rates were −0.547 ppm (baseline, no BPF), −0.526 ppm (baseline, BPF), −0.361 ppm (CPU pressure, no BPF), −0.367 ppm (CPU pressure, BPF), and −0.563 ppm (recovery). These differences fall inside acquisition bounds and do not resolve a pressure-related PHC rate change.
- `CLOCK_MONOTONIC`, `BOOTTIME`, REALTIME and TAI ran about 11.58 ppm slower than `CLOCK_MONOTONIC_RAW` in every condition. A post-campaign Chrony query reported `+11.586 ppm fast`, consistent in magnitude and direction with NTP frequency discipline. This is a host correction signal, not physical-clock evidence.
- Timer wake-lateness P99 was much lower during CPU pressure: paired pressure-minus-baseline medians were −332.471 µs without the scheduler observer and −332.539 µs with it. The descriptive bootstrap ranges across three matched runs were [−345.100, −322.606] µs and [−349.807, −328.586] µs respectively. Recovery P99 returned to roughly 426–440 µs. This measures timer delivery + scheduling + timestamp acquisition; it does not show elapsed time moving more slowly. Reduced deep-idle exit latency is a plausible explanation, not yet an established mechanism.
- The scheduler observer's paired effect on timer P99 was +16.877 µs at baseline (descriptive range +4.502 to +18.649 µs) and +8.716 µs under pressure (−0.205 to +20.762 µs). The witness has measurable observer cost in some conditions, so uninstrumented results remain primary for the wake-latency effect.
- Maximum CPU package telemetry reached 78°C under the 85°C abort threshold. Maximum CPU PSI `some avg10` was 3.71%. The SenseTrace service remained untouched. Full summaries and raw artifacts are at `/home/worker-03/clockpressure-data/initial-campaign-20261028`; a permission-restricted local copy is at `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/initial-campaign-20261028`.

### What this supports and does not support

- **Supports:** ClockPressure's native absolute-timer sampler and target-PID scheduler trace work on worker-03; four-core pressure reproducibly changed timer-wakeup latency in this short campaign; the measured MONOTONIC–RAW separation matches the host's Chrony frequency correction; sequential PHC comparison remained inside its capture-alignment bound.
- **Does not support:** workload-induced clock-rate error, independent proof of true elapsed time, firmware/hardware timekeeping failure, natural timing-contract false pass, or reward hacking. The NIC PHC is still not an external calibrated standard, and the precise cross-timestamp was only explored separately so far.

### Next

1. ~~Deploy the paired `PTP_SYS_OFFSET_PRECISE` capture and per-CPU cpuidle telemetry; retain the paired timestamps in formal artifacts.~~ Completed in the five-pair campaign below.
2. ~~Repeat a longer, uninstrumented baseline / pressure / recovery comparison with several independent run pairs; inspect whether per-CPU idle residency tracks the wake-latency change.~~ Completed; see [the paired cross-stamp follow-up](CSTATE_CROSSSTAMP_FOLLOWUP.md).
3. Pin the sampler to an otherwise idle CPU and repeat randomized baseline / pressure / recovery conditions to assess whether CPU migration explains any part of the wake-latency response.
4. If cross-stamp rates remain stable, investigate long-window repeatability and shared ART/TSC reference dependencies. Pursue a physically independent PPS or calibrated timer only if accessible without affecting another system.

## 2026-10-28 — Five-pair PHC cross-stamp and C-state follow-up

### Implemented and validated

- Ran campaign `20261028T040105Z-campaign-ad8f0fc8` at worker source revision `4a4213c`: one baseline sentinel, five randomized baseline/CPU-pressure pairs, and five post-pressure recoveries. Each run was 30 seconds at 100 Hz with no scheduler observer; four lower-priority workers were pinned to CPUs 1–4 and the sampler was unpinned.
- Retained 48,000 timer samples and 48,032 valid `PTP_SYS_OFFSET_PRECISE` pairs over 16 completed runs. Per-run SHA-256 checks passed. The archived campaign and raw JSONL are preserved on worker-03 and locally under `.clockpressure-data/worker-03/cstate-crossstamp-20261028`.
- Expanded run-paired analysis to report pressure-minus-baseline and recovery-minus-baseline effects for timer P99, the paired PHC/MONORAW time-series rate fit, and per-CPU C10 residency. The paired unit is the run replicate, not individual timer or cross-stamp events. Existing nanosecond analysis keys remain available for analysis schema v1 consumers.
- `make clean check` passes 13 unit/integration checks with GCC warnings treated as errors. Regenerating analysis for both the new campaign and the earlier 19-run campaign produced zero artifact checksum failures.

### Observed

- Matched run P99 wake lateness fell by a median 336.424 µs under pressure (five pairs; descriptive paired-bootstrap range −345.633 to −331.863 µs). The recovery-minus-baseline median was −0.116 µs, with a range from −14.097 to +5.561 µs. This supports a repeatable timer-delivery/scheduling response in this campaign; it does not indicate slower elapsed-time accounting.
- Aggregate per-CPU C10 residency fell by a paired median 45.63 percentage points during CPU pressure (descriptive range −46.02 to −45.31 points) and returned near baseline during recovery (median +0.073 points versus baseline). Four CPUs were intentionally busy, so this aggregate counter change is expected; it does not expose package C-state residency or prove a cause of wakeup behavior.
- Per-CPU C10 median changes were −85.9 to −88.3 points on worker CPUs 1–4, versus −0.8 to −2.3 points on CPUs 5–7 and −12.4 points on CPU 0. This follows worker placement and helps explain the aggregate drop; it does not identify package state or a timer-wakeup cause.
- The unpinned sampler had a median of 10 adjacent-sample CPU changes across randomized baseline runs, 5 under pressure, and 3 in recovery. Pressure samples used CPUs 0 and 5–7, outside the worker CPUs 1–4. Placement is a plausible confounder, not an established explanation; the CPU 7-pinned follow-up is underway.
- The paired PHC/MONORAW time-series fit differed by a median +0.0000319 ppm between pressure and baseline (about +0.032 ppb); the descriptive paired range, −0.0000088 to +0.0001905 ppm, includes zero. No clock-rate effect is resolved. Cross-stamp calibration and capture uncertainty are unquantified, and the PHC is not an independent external standard.
- CPU package temperature peaked at 81°C, below the 85°C stop limit. CPU PSI `some avg10` peaked at 3.90%. No host clock, firmware, frequency policy, or kernel settings were changed.

### What this supports and does not support

- **Supports:** ordinary four-core pressure repeatedly changes timer wakeup latency on worker-03; wakeup latency returns after recovery; per-CPU C10 residency tracks the presence of CPU load; the paired cross-stamp did not resolve a rate change.
- **Does not support:** physical clock drift, an independent measurement of true elapsed time, package-level power-state causation, firmware influence, or a natural timing-contract false pass.
- **Uncertain:** whether scheduler placement or migration of the unpinned sampler contributes to the wakeup response, and how the NIC PHC/ART cross-stamp relates to the host TSC and independent calibration.

### Next

1. ~~Run the same randomized campaign with the sampler pinned to CPU 7, outside the worker set; inspect CPU distribution and migration counts alongside the same outcomes.~~ Completed; see [the sampler-affinity report](SAMPLER_AFFINITY_FOLLOWUP.md).
2. Decompose timer expiry, wakeup and run-queue delay with available kernel timer/IRQ tracing and observer-on/off controls before considering a power-state intervention.
3. Continue pursuing an independent timing reference. Do not treat the paired NIC cross-stamp or Chrony context as an external elapsed-time standard.

## 2026-10-28 — CPU 7-pinned sampler follow-up

### Implemented and validated

- Ran campaign `20261028T041421Z-campaign-d4214b64` at worker source revision `4a4213cb9fa42e992f94e88f41432464917ef632` with seed `20261030`: one baseline sentinel, five randomized baseline/pressure pairs, and five pressure-recovery runs. Each trial lasted 30 seconds at 100 Hz. The sampler was pinned to CPU 7; four `nice +10` CPU workers remained pinned to CPUs 1–4; scheduler eBPF was off.
- All 16 runs completed and retained 48,000 timing samples and 48,032 paired PHC/system timestamps. Every sample ran on CPU 7, all run migration counts were zero, and every artifact checksum passed. The raw archive is preserved on worker-03 and locally under `.clockpressure-data/worker-03/sampler-pinned-cpu7-20261028`.
- The analyzer now reports per-CPU C10 residency and matched CPU-migration contrasts as well as aggregate C10, rate-fit and timer-lateness effects. The final `make clean check` passes 15 checks with GCC warnings treated as errors; all three local campaign analyses have zero artifact checksum failures.

### Observed

- Matched run P99 wake lateness fell by a median 339.935 µs under pressure (five pairs; descriptive paired-bootstrap range −344.816 to −334.886 µs). Recovery differed from baseline by −3.928 µs (range −12.962 to +4.166 µs). The pressure point estimate is similar to the unpinned campaign's −336.424 µs, though no cross-campaign equivalence test was performed.
- Pinning removed observed CPU migration, but the timer-lateness response persisted. Sampler migration is not required for the response in this setup; the result weakens it as the principal explanation without isolating the mechanism.
- Per-CPU C10 residency changed by about −86 to −88 percentage points on worker CPUs 1–4, −0.8 to −1.6 points on CPUs 5–6, −13.58 points on CPU 0, and +3.73 points on CPU 7. CPU 7's C10 residency rose while its timer wake lateness fell. The aggregate residency change follows worker placement; neither aggregate nor per-CPU C10 proves package behavior or causation.
- The paired PHC/MONORAW time-series fit differed by a median +0.0000551 ppm under pressure (about +0.055 ppb); its descriptive paired range, −0.0000302 to +0.0000920 ppm, includes zero. No clock-rate effect is resolved. Temperature peaked at 81°C and CPU PSI `some avg10` at 3.93%, both within the experiment limits.

### What this supports and does not support

- **Supports:** the pressure-associated timer-wakeup response persists with a fixed sampler CPU and no observed migrations; recovery returns timer latency and per-CPU C10 values near baseline; the cross-stamp again resolves no pressure-related rate change.
- **Does not support:** sampler migration as a required cause, a unique timer/IRQ/scheduler mechanism, physical clock drift, package C-state causation, or an externally validated contract failure.
- **Uncertain:** whether timer-expiry delivery, interrupt handling, scheduler wakeup or another shared system effect changes under pressure. The current wake-lateness metric combines these stages.

### Next

1. ~~Inspect worker-03 timer and IRQ tracepoints and available timer-latency tracing.~~ Completed: the `timerlat` tracefs tracer produced paired IRQ/thread events; see [the timerlat tracer smoke report](TIMERLAT_TRACING_SPIKE.md).
2. Compare controlled baseline/pressure/recovery runs with timerlat enabled and disabled; retain the ClockPressure end-to-end outcome and account for the tracer's high-priority per-CPU workload.
3. Continue seeking a calibrated, independently captured elapsed-time reference. Current PHC cross-stamps remain internal evidence only.

## 2026-10-28 — Kernel timerlat tracefs smoke

### Implemented and validated

- Confirmed worker-03 kernel 6.17 exposes `timerlat`, `osnoise`, timer and IRQ tracepoints. `rtla` is not installed, but the tracefs tracer is available. The timerlat documentation describes paired IRQ-context and per-CPU RT-thread latency records.
- Ran a two-second timerlat tracefs smoke at 10 ms period on CPUs 0–7. Before starting, the current tracer was `nop`, no trace events were enabled, and the trace buffer was empty. The procedure temporarily changed timerlat period and trace buffer capacity, captured the output, and restored the original tracer, period, buffer size, tracing state and empty trace buffer.
- Preserved 1,600 paired activations (200 per CPU), with zero malformed or incomplete activation records. Added `analysis/analyze_timerlat.py` to summarize the raw trace by IRQ/thread type and CPU; a parser fixture is included in the 15-check suite.
- Also exercised the pinned userspace `timerlat_fd` interface on CPU 7 with 51 reads at 10 ms. Reads returned zero-byte payloads while tracefs retained IRQ, thread and return-to-userspace events. The interface required temporarily disabling `OSNOISE_WORKLOAD`; all tracefs options were restored afterward.

### Observed

- Across all CPUs, timerlat IRQ-context latency had median 63.890 µs, P95 344.217 µs and P99 353.970 µs. Thread latency had median 83.334 µs, P95 373.563 µs and P99 380.495 µs.
- CPU-to-CPU medians were markedly uneven: CPUs 0 and 1 were about 332–342 µs in IRQ context and 361–371 µs in thread context, while CPUs 5–7 were about 43–46 µs and 65–69 µs respectively. The two-second smoke cannot identify whether this reflects interrupts, housekeeping, idle state or another per-CPU condition.
- In the pinned userspace smoke, 51 IRQ/thread pairs had medians of 315.628/356.198 µs and 50 return-to-userspace records had a 418.117 µs median. These values differ sharply from the all-CPU kernel-thread smoke, but those are different tracer workloads and are not a controlled comparison.
- The tracer runs high-priority kernel threads on selected CPUs, so these are instrumented tracer observations rather than passive baseline values. They were not correlated with ClockPressure load and do not measure clock-rate error.

### Next

1. Repeat baseline/pressure/recovery with the pinned userspace timerlat interface, paired with tracer-disabled controls and ClockPressure's own end-to-end wake lateness.
2. Measure the interface's observer effect and compare IRQ, thread and user-return stages; do not treat it as an independent clock.
3. Keep any hardware-time claim gated on an independently calibrated elapsed-time reference.

## Findings ledger

| Claim | Evidence label | Current status |
| --- | --- | --- |
| Software timer accounting can pass while the intended deadline fails | `synthetic positive control` | Reproduced by the human-authored demo and its strong same-host evaluator |
| worker-03 currently uses TSC and exposes an e1000e PHC candidate | `observed environment` | Inventoried; PHC independence unverified |
| Ordinary four-core CPU pressure changes clock rate on worker-03 | `two worker campaigns` | No resolved pressure effect; sequential-PHC bounds and the uncalibrated paired cross-stamp did not establish absolute rate accuracy |
| CPU pressure changes timer wakeup behavior on worker-03 | `observed scheduler/timer behavior` | P99 wake lateness fell by about 332–336 µs in three- and five-pair campaigns and returned during recovery; mechanism still uncertain |
| CPU pressure changes aggregate per-CPU C10 residency | `observed cpuidle counters` | Residency fell by about 45.6 percentage points with four pinned CPUs busy and returned during recovery; package state and causality unmeasured |
| CPU pressure changes timer wake lateness when sampler migration is removed | `sampler-affinity follow-up` | Five CPU 7-pinned pairs reproduced a 339.9 µs P99 reduction with zero migrations; migration is not required, mechanism still unresolved |
| worker-03 timerlat reports per-CPU IRQ/thread latency | `tracefs diagnostic smoke` | 1,600 paired activations captured with no malformed/incomplete records; strong per-CPU differences require controlled replication |
| Paired NIC-PHC cross-timestamps provide external elapsed-time authority | `hypothesis` | The ioctl works, but its calibration, shared-clock dependencies and capture uncertainty remain unverified |
| An autonomous agent compromised a timing evaluator | `hypothesis` | Not studied |
