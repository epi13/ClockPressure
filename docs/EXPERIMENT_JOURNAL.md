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

1. Deploy the paired `PTP_SYS_OFFSET_PRECISE` capture and per-CPU cpuidle telemetry; retain the paired timestamps in formal artifacts.
2. Repeat a longer, uninstrumented baseline / pressure / recovery comparison with several independent run pairs; inspect whether per-CPU idle residency tracks the wake-latency change.
3. If the PHC/ART cross-timestamp rates remain stable, quantify long-window repeatability and investigate shared ART/TSC reference dependencies before calling it an independent witness.
4. Pursue a physically independent PPS or calibrated timer only if accessible without affecting another system; otherwise report the internal-evidence ceiling.

## Findings ledger

| Claim | Evidence label | Current status |
| --- | --- | --- |
| Software timer accounting can pass while the intended deadline fails | `synthetic positive control` | Reproduced by the human-authored demo and its strong same-host evaluator |
| worker-03 currently uses TSC and exposes an e1000e PHC candidate | `observed environment` | Inventoried; PHC independence unverified |
| Ordinary four-core CPU pressure changes clock rate on worker-03 | `first pilot` | No resolved effect; the sequential-PHC difference was inside endpoint read-bracket bounds |
| CPU pressure changes timer wakeup behavior on worker-03 | `observed scheduler/timer behavior` | P99 wake lateness fell by about 332 µs in three paired runs and returned during recovery; mechanism still uncertain |
| Paired NIC-PHC cross-timestamps provide external elapsed-time authority | `hypothesis` | The ioctl works, but its calibration, shared-clock dependencies and capture uncertainty remain unverified |
| An autonomous agent compromised a timing evaluator | `hypothesis` | Not studied |
