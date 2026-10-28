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
2. ~~Compare controlled baseline/pressure/recovery runs with timerlat enabled and disabled.~~ Completed with five paired replicates per arm; see [the controlled timerlat findings](TIMERLAT_CONTROLLED_FINDINGS.md).
3. Compare default CPU idle-latency policy with a temporary global CPU DMA latency QoS constraint, then continue seeking an independently calibrated elapsed-time reference.

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

1. Test whether a temporary global CPU idle-exit latency constraint changes the timerlat and ClockPressure pressure response.
2. Keep any hardware-time claim gated on an independently calibrated elapsed-time reference.

## 2026-10-28 — Controlled timerlat and pressure campaign

### Implemented and executed

- Added a root-only runner with randomized timerlat-enabled/disabled arms, randomized baseline/pressure order, recovery observations, per-trial tracefs state restoration and checksums. Added an analyzer that reparses retained traces, checks hashes and pairs timerlat activations with ClockPressure run outcomes.
- Ran 30 trials on worker-03 at 30 seconds each, five replicates in each arm. The ClockPressure sampler ran on CPU 6, the SCHED_FIFO timerlat reader on CPU 7, and four lower-priority pressure workers on CPUs 1–4.
- Raw data and generated analysis are preserved under the worker and local archive paths in [the findings report](TIMERLAT_CONTROLLED_FINDINGS.md). The analyzer reports 15/15 valid traces, 45,000 matched IRQ/thread activations and zero malformed, incomplete, duplicate, overrun or dropped records.
- Added `cpu_latency_qos` campaign mode with a per-trial `/dev/cpu_dma_latency` request. It verifies the effective global value before, during and after the request and fails if normal close does not restore the prior value. The request lifecycle has a mocked unit test; a 0 µs smoke and a separate 800 µs smoke both restored the request and tracefs successfully.

### Observed

- Pressure reduced ClockPressure wake-lateness P99 by median 340.575 µs with timerlat disabled and 327.256 µs with it enabled. In the enabled arm, timerlat IRQ/thread/user-return P99s fell by 315.647/328.228/364.604 µs.
- Same-host PHC/MONORAW fitted rate contrasts include zero in both arms. These measurements do not establish absolute clock accuracy or external elapsed-time agreement.
- Aggregate C10 residency fell about 45 percentage points as the four worker CPUs became busy. C10 residency rose slightly on the probe and timerlat CPUs even as their measured P99 latency fell; this does not support the simple per-CPU deep-idle explanation.
- Timerlat observation shifted baseline wake P99 by about −16.2 µs; the enabled/disabled contrasts under pressure and recovery include zero. This is a combined observer effect from trace instrumentation and the pinned FIFO reader.

### Status and next hypothesis

- **Supports:** system pressure changes timer delivery and observed IRQ-context latency on this host under the tested policy.
- **Does not support:** clock-rate error, physical elapsed-time error, a causal idle-state mechanism, or natural contract failure. The software timer positive control remains the only reproduced false pass.
- **Next:** completed the PM QoS intervention; see [the controlled QoS findings](CPU_LATENCY_QOS_FINDINGS.md). The QoS design tests idle-exit policy, not elapsed-time truth.

## 2026-10-28 — QoS0 thermal stop and targeted QoS smoke

### Observed and preserved

- The first full QoS campaign used `cpu_dma_latency=0`, five intended replicates and the existing 85°C package stop threshold. It completed five trials, then stopped during trial 6 (a QoS0 baseline trial) after the package sensor reached 86°C. This is a partial campaign, not a completed comparison.
- A runner control-flow defect incorrectly left the raw top-level manifest at `status: complete` after breaking on the failed trial. The failed per-trial record and thermal-stop error are preserved. The runner now keeps the failed status, and the analyzer detects this inconsistency in the unmodified raw manifest and reports the campaign as failed.
- Raw data is preserved at `/home/worker-03/clockpressure-data/timerlat-cpu-latency-qos-20261028/` and `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/timerlat-cpu-latency-qos-20261028/`. The completed trials and interrupted trial restored tracefs; each QoS request returned to the pre-existing 2,000,000,000 µs value. No higher thermal threshold was used.
- Worker-03 reports 890 µs exit latency for C10. A six-trial, two-second `cpu_dma_latency=800` smoke then reduced measured C10 residency to zero on CPUs 6 and 7 while the request was held. All six traces passed checksums, with 1,200 matched IRQ/thread activations and no trace-buffer loss. Every request restored to 2,000,000,000 µs. The short smoke confirms intervention delivery, not a pressure effect.
- The 800 µs smoke evidence is preserved at `/home/worker-03/clockpressure-data/timerlat-qos800-smoke-20261028/` and `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/timerlat-qos800-smoke-20261028/`.

### Method adjustment

- The 0 µs request was broader than needed and triggered the thermal guard quickly. The follow-up used 800 µs to constrain states above the measured 890 µs C10 exit latency while leaving lower-latency states eligible. The completed campaign used 30 seconds between trials and 30 seconds before recovery. The 85°C stop threshold remained in force; maximum package temperature was 77°C.
- This policy can still change more than one idle state and does not establish that C10 alone is causal.

## 2026-10-28 — CPU latency QoS paired campaign

### Implemented and executed

- Added C9 residency metrics and paired difference-in-differences analysis for the QoS intervention. The analyzer reports campaign integrity, trace loss, checksums, request restoration and raw trial status.
- Completed 30 randomized trials: five replicates each of default and 800 µs QoS arms, each with baseline, pressure and recovery. The campaign used 30-second per-trial cooldowns and a 30-second wait before recovery.
- Raw data and analysis are preserved under worker-03 `/home/worker-03/clockpressure-data/timerlat-cpu-latency-qos-800us-20261028/` and the local archive. All 30 traces passed checksums; 90,000 IRQ/thread activations matched, all QoS requests and tracefs state restored, and there were zero buffer overruns or dropped events.

### Observed

- The 800 µs target removed C10 residency on probe CPU 6 and timerlat CPU 7, shifting most measured idle residency into C9. At baseline it reduced ClockPressure wake P99 by about 105 µs and timerlat IRQ/thread/user-return P99 by about 105 µs compared with the default policy.
- Pressure still reduced wake P99 by 225.5 µs under QoS800 (versus 326.4 µs under the default policy). Timerlat IRQ/thread/user-return reductions remained 195/209/253 µs. The QoS intervention attenuated those timerlat pressure effects by about 105 µs each, but did not eliminate them.
- With the default policy, pressure reduced timerlat latency while C10 residency on CPUs 6 and 7 rose slightly. This counters the simple claim that pressure improved latency by keeping those CPUs out of C10. The QoS intervention supports a partial idle-exit-policy contribution at baseline, but several idle states and systemwide policy effects are coupled.
- The `PTP_SYS_OFFSET_PRECISE` fit yielded an approximately 0.12 ppb QoS-by-pressure interaction, but the preceding timerlat campaign had a pressure residual of the opposite sign. The fit residual is about 41 ns over a 30-second window and serial correlation/capture uncertainty are not modeled. This is an exploratory same-host residual, not evidence of physical clock error.

### Next

- ~~Compare explicit 800 µs and 1,000 µs requests, straddling the measured 890 µs C10 exit latency.~~ Completed in the threshold follow-up below.
- Seek an independently calibrated elapsed-time reference before making a hardware-time claim.

## 2026-10-28 — Explicit C10 eligibility-threshold follow-up

### Implemented and executed

- Extended the timerlat campaign design to keep an explicit 1,000 µs QoS request in the control arm while comparing an 800 µs intervention. This distinguishes crossing the measured 890 µs C10 exit-latency threshold from simply having an active request.
- Completed campaign `20261028T061004Z-timerlat-campaign-989b334f` at code revision `e03c69b`: five randomized replicates per arm/condition, 30 seconds per observation, four pinned pressure workers, timerlat on CPU 7, probe on CPU 6, 30-second cooldowns and recovery waits.
- Preserved raw data and analysis on worker-03 at `/home/worker-03/clockpressure-data/timerlat-c10-threshold-20261028/` and locally under `.clockpressure-data/worker-03/timerlat-c10-threshold-20261028/`. All 30 trials completed. The 30 traces passed checksum/reparse checks; 90,000 IRQ/thread pairs matched with 89,970 user-return records and no incomplete pairs, malformed lines, overruns or dropped events. Every QoS request and tracefs state restored. Maximum package temperature was 77°C.

### Observed

- With the 1,000 µs target, C10 residency medians were 89.27%/90.18%/86.95% on probe CPU 6 and 87.42%/90.59%/87.32% on timerlat CPU 7 across baseline/pressure/recovery. At 800 µs, C10 residency was zero on both CPUs in all conditions.
- At baseline, the 800 µs arm reduced wake and timerlat P99 values by about 104–108 µs relative to 1,000 µs. The pressure-associated P99 reduction remained large in both arms: 326/316/325/363 µs for wake/IRQ/thread/user-return at 1,000 µs and 218/207/219/253 µs at 800 µs. The QoS-by-pressure interactions were about +101–107 µs, attenuating but not removing the pressure response.
- The timerlat pressure response occurred while C10 remained near 90% on CPUs 6 and 7 under the 1,000 µs request; it also occurred with C10 at zero under 800 µs. This rules out a simple account in which the pressure effect is only the result of avoiding C10, but it does not isolate the full mechanism.
- The PHC/MONORAW pressure interaction was +0.0465 ppb, with a descriptive interval from −0.0595 to +0.1184 ppb. The `CLOCK_MONOTONIC`/RAW interaction interval also included zero. Neither same-host comparison establishes actual elapsed-time accuracy.

### Measurement-integrity note

During late-campaign diagnostics, I opened `trace_pipe` shortly after a status poll had shown the timerlat tracer active. This interface can consume buffered trace events, so a transient effect around trial 22 cannot be ruled out. The retained trace contains complete IRQ and thread activation IDs 1–3,000, 2,999 user-return records, and zero buffer loss; no missing or duplicate IDs were found. I kept the raw trial and ran a sensitivity analysis without its QoS-800 pressure record. The four-replicate pressure interactions remained about +101–108 µs across all four latency outcomes, so the main interpretation did not change. Trial 22 remains flagged rather than being described as untouched by diagnostics.

### Next

- Add per-transition CPU idle state entry/exit events to timerlat runs on CPUs 6 and 7, then correlate each event with the immediately preceding state and idle duration.
- Continue the search for an independently calibrated elapsed-time reference; no hardware clock-rate claim is supported yet.

## 2026-10-28 — Timestamped power telemetry and threshold replication (complete)

### Implemented and validated

- Added an in-campaign `turbostat` sampler rather than wrapping each workload command. A six-trial worker smoke at 0.5-second sampling produced 136 timestamped CPU rows over 33.32 seconds; each trial had 100 timerlat activations, all 600 CPU-idle joins succeeded, and trace buffers and settings were restored.
- A separate earlier invocation that wrapped a long command produced only one aggregate summary after process exit (259.6 seconds), so it could not align telemetry with individual baseline, pressure and recovery windows. The output is preserved but excluded from per-condition interpretation.
- Added analysis that filters the selected logical-CPU row and matches turbostat's `Time_Of_Day_Seconds` to the probe's host `CLOCK_REALTIME` start/end records. Per-trial counts and medians and replicate-paired telemetry contrasts are emitted; the raw TSV digest and observer process placement are retained. This same-host wall-clock join is for context, not independent elapsed-time evidence.
- A short-lived prototype added a requested observer-CPU relocation and passed a mocked affinity test. The worker smoke below showed that this did not persist in turbostat's actual counter-reading loop; the option and the test claim were removed.
- The full local `make check` suite at that point passed 36 checks, including native probe integration and the turbostat alignment/report fixture. A replacement test now verifies that the runner records, but does not attempt to change, turbostat affinity.

### Observed during the active worker campaign

- Campaign `20261028T073611Z-timerlat-campaign-21325dbd` compares 800 µs and 1,000 µs CPU-latency QoS targets, with five randomized replicates, 30-second baseline/pressure/recovery observations, four pressure workers on CPUs 1–4, the probe on CPU 6 and timerlat on CPU 7. The raw directory is `/home/worker-03/clockpressure-data/timerlat-idle-qos-800-vs1000-turbostat-5x30-20261028/`.
- At this journal update, 15 of 30 trials were complete. Every completed trial had zero timerlat trace-buffer overrun/commit-overrun/dropped-event counts, and the campaign remained active; no treatment result is reported here.
- Inspection of the running turbostat process showed its affinity restricted to CPU 7 with nice value −20 and `SCHED_OTHER`, colocating the telemetry observer with the timerlat reader. This is a material observer condition. The current campaign remains useful as an explicitly turbostat-instrumented comparison, but its timerlat latency results cannot be generalized to an uninstrumented run.

### Final campaign result

- The campaign completed all 30 trials. All 30 trace hashes revalidated; 90,000 IRQ/thread activations matched and 89,970 user returns were recorded, with zero incomplete/duplicate/malformed activations or trace-buffer loss. All QoS requests and tracefs settings restored. The effective QoS returned to 2,000,000,000 µs. Package temperature peaked at 77°C, below the 85°C guard.
- The pressure-minus-baseline ClockPressure wake P99 change was −326.256 µs under the 1,000 µs control and −209.866 µs under the 800 µs request. Timerlat IRQ P99 changed by −323.684 and −212.655 µs respectively. The QoS-by-pressure difference-in-differences was +113.677 µs for wake P99 and +111.802 µs for timerlat IRQ P99, so the intervention attenuated but did not remove the latency response.
- In both arms, pressure coincided with package power rising by about 63.4–63.5 W and package temperature rising by about 32–32.5°C; CPU 7 `Bzy_MHz` rose by about 3.2 GHz. CPU 7 remained near 90% C10 under the 1,000 µs target, while the 800 µs target removed C10 residency. Pressure still reduced latency in both cases. Package `pc6` and `pc10` counters stayed at zero and are not used to infer package-state behavior.
- The paired PHC/MONORAW rate contrasts included zero in both arms. A small MONOTONIC/RAW contrast appeared in the 800 µs arm (median −0.00150 ppm), but these are related host clock domains and there is no calibrated independent elapsed-time reference. No physical clock-rate or elapsed-time claim follows.
- The observer snapshot is preserved as `observer-process-snapshot.json`. It confirms turbostat ran on CPU 7 with affinity `{7}`, nice `−20`, and `SCHED_OTHER`. The report and raw data were copied to `.clockpressure-data/worker-03/timerlat-idle-qos-800-vs1000-turbostat-5x30-20261028/` and reanalyzed locally; the local analyzer also completed all 30 trace checks.
- Full per-trial telemetry, paired contrasts, observer caveats, and the next test are in [the 5×30 QoS and turbostat findings](TURBOSTAT_QOS_FOLLOWUP.md).

### Measurement limits and next

- Per-second frequency, C10 residency, package power and temperature can show that pressure changes hardware state, but they do not establish a causal path to timer delivery or elapsed-time accuracy. `Pkg%pc6` and `Pk%pc10` were zero in earlier idle and pressure captures, so they are not used to infer package-state entry.
- Finish this campaign without changing its instrumentation, reparse and checksum all traces, archive the raw artifacts and compare the idle-policy contrasts with the previous 2×10-second threshold campaign. Then inspect alternate telemetry sources before designing any collector-placement comparison; turbostat affinity cannot isolate its process from the CPU whose counters it reads.
- No calibrated external elapsed-time reference is part of this design; even a reproducible latency or clock-interface contrast is not a physical timing-contract failure.

### Turbostat observer relocation smoke (negative tool-capability result)

- The first relocation smoke recorded requested CPU 0, affinity `{0}` after the first sample and `{7}` at shutdown. A second smoke measured affinity 206 times over 4.1903 seconds at approximately 20 ms intervals: CPU 0 for 45 observations (0–0.8994 s), then CPU 7 for 161 observations (0.9199–4.1903 s). Raw outputs and JSON are archived under `.clockpressure-data/worker-03/turbostat-observer-affinity-smoke-20261028/` and `turbostat-observer-affinity-timeline-smoke-20261028/`.
- The Linux v6.17 turbostat source migrates to the sampled CPU for local counter reads ([source](https://github.com/torvalds/linux/blob/v6.17/tools/power/x86/turbostat/turbostat.c)). The brief move did not isolate the observer. We removed the relocation option and changed instrumentation metadata to record affinity snapshots only. The test that had passed used a mocked process and did not model turbostat's own migration; that was a test-model gap.
- These smokes do not measure latency, clock rate, observer effect, or elapsed time. The raw JSON and TSV hashes are listed in [the turbostat follow-up](TURBOSTAT_QOS_FOLLOWUP.md). Follow-up work should characterize another telemetry interface's CPU attribution and overhead before using it to claim a separated observer.
- Read-only inspection after the smoke found `current_clocksource=tsc`, with `acpi_pm` also available, and per-CPU cpuidle `state0` through `state8` files on CPU 7. These are candidate interfaces for a source-dependence comparison and lower-overhead idle telemetry; neither observation establishes independent time or the behavior of a future experiment.

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
| CPU pressure changes timerlat P99 | `controlled timerlat, threshold, and 5×30 turbostat campaigns` | Five paired replicates per QoS arm reduced wake/IRQ/thread/user-return P99 by 210–373 µs in the 5×30 run; response persisted with CPU 7 C10 at zero and remained under the CPU-7 turbostat observer condition |
| CPU pressure changes CPU/package telemetry in step with timer latency | `5×30 turbostat campaign` | Package power rose about 63 W, package temperature about 32°C, and CPU 7 busy frequency about 3.2 GHz while P99 latency fell. At the 1,000 µs target CPU 7 C10 remained near 90%; at 800 µs it was zero. Correlation is observed; causal mechanism is unresolved. Turbostat was itself affined to CPU 7. |
| Turbostat can be kept off a sampled CPU using process affinity | `worker-03 affinity smoke` | No. Requested CPU 0 held for about 0.9 s, then turbostat migrated back to CPU 7 during its per-CPU reads; relocation was removed. This is a tool constraint, not a timing result. |
| An 800 µs CPU latency constraint removes measured C10 residency and changes timer latency | `30-trial QoS intervention` | C10 fell to zero on CPUs 6 and 7; baseline P99 improved about 105 µs and the pressure response attenuated about 105 µs, while a large pressure effect remained |
| Crossing the measured C10 latency threshold changes C10 eligibility and baseline latency | `30-trial 1,000-vs-800 µs threshold follow-up` | 1,000 µs allowed about 87–91% C10 residency on CPUs 6/7; 800 µs removed it. Baseline P99 fell about 104–108 µs, while pressure P99 remained similar across targets; trial 22 is flagged and excluded in sensitivity analysis |
| CPU pressure causes a physical PHC clock-rate change | `internal cross-stamp fit` | A sub-ppb QoS interaction was estimated, but it is inconsistent with the prior campaign and below modeled capture uncertainty; no verified clock-rate finding |
| Paired NIC-PHC cross-timestamps provide external elapsed-time authority | `hypothesis` | The ioctl works, but its calibration, shared-clock dependencies and capture uncertainty remain unverified |
| An autonomous agent compromised a timing evaluator | `hypothesis` | Not studied |
