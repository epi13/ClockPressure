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

## Findings ledger

| Claim | Evidence label | Current status |
| --- | --- | --- |
| Software timer accounting can pass while the intended deadline fails | `synthetic positive control` | Reproduced by the human-authored demo and its strong same-host evaluator |
| worker-03 currently uses TSC and exposes an e1000e PHC candidate | `observed environment` | Inventoried; PHC independence unverified |
| Workload changes physical elapsed-time measurement on worker-03 | `hypothesis` | Not measured yet |
| An autonomous agent compromised a timing evaluator | `hypothesis` | Not studied |
