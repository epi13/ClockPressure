# ClockPressure

**Investigating whether system pressure can influence time measurements—and cause a program to pass a timing contract while failing its intended objective.**

ClockPressure is an open, Linux-focused experimental research project. It uses low-overhead observability (including eBPF where appropriate), controlled workloads, and independently validated measurements to distinguish:

- **Scheduling or timer-event jitter:** work or callbacks happen late, even while the system's clock continues advancing correctly.
- **Measurement / accounting error:** a program's timer logic undercounts real elapsed time, such as a tick-counting loop that ignores delayed ticks.
- **Clock-rate error:** a reported clock advances at a different rate from a trustworthy external time reference.
- **Contract / evaluation failure:** a test reports success because its measurement authority differs from the requirement being tested.

**Status:** The executable instrumentation and synthetic timing-contract positive control are implemented. Three initial worker-03 campaigns and four controlled timerlat/QoS campaigns are complete. Four-core pressure repeatedly reduced timer-wakeup and timerlat P99 latency by 0.2–0.36 ms. In the direct 1,000-vs-800 µs comparison, the lower target removed measured C10 residency and reduced baseline timer-path P99 by about 0.10 ms; the large pressure response remained under both targets. A three-pair TSC/ACPI PM pilot found that `PTP_SYS_OFFSET_PRECISE` worked in all 18 TSC samples but returned `ENODEV` in all 18 ACPI PM samples, exposing a clocksource-dependent measurement capability. No externally validated clock anomaly or natural false pass has been observed.

The first-campaign results are in [the initial worker-03 findings](docs/INITIAL_PILOT_FINDINGS.md), the cross-stamp and cpuidle follow-up is in [the second findings report](docs/CSTATE_CROSSSTAMP_FOLLOWUP.md), and sampler-placement results are in [the third findings report](docs/SAMPLER_AFFINITY_FOLLOWUP.md). Raw worker data and regenerated analysis are preserved outside the repository under `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/` and on worker-03 under `/home/worker-03/clockpressure-data/`.

The three controlled timerlat and CPU latency QoS campaigns show a clear latency response and a partial idle-policy contribution, but no independently verified elapsed-time discrepancy. The direct C10-threshold follow-up and its trace-integrity sensitivity check are in the [QoS findings](docs/CPU_LATENCY_QOS_FINDINGS.md#explicit-800-vs-1000-microsecond-threshold-follow-up). See also the [timerlat findings](docs/TIMERLAT_CONTROLLED_FINDINGS.md) and [campaign design](docs/TIMERLAT_CONTROLLED_CAMPAIGN.md).

The TSC/ACPI PM pilot did not resolve a source-dependent timerlat effect. It did reveal that the selected clocksource changes whether the kernel can convert the e1000e PHC's ART cross-timestamp into system time. Details, source-level explanation, and raw evidence are in the [clocksource pilot findings](docs/ACPI_PM_CLOCKSOURCE_FINDINGS.md).

## Research question

Can workload-induced system pressure, directly or through hardware / firmware / software dependencies, cause a measurable divergence between reported and independently observed elapsed time? If so, can that divergence produce a reproducible false pass in a timing contract?

We do **not** assume the answer is yes for modern Linux clocks. A well-behaved clocksource should account for delayed execution. Demonstrating that jitter alone does not slow a given clock is an important negative result.

## Why this matters

An agent or program can satisfy what a test *measures* without satisfying what the test was *intended to guarantee*. ClockPressure uses time as a concrete, inspectable example of a broader issue: the measured process and the measurement mechanism may share dependencies. Evidence from this project may help improve verification, authority boundaries, and environment accountability in agent systems including MNCS. Integration with MNCS is future work, not a current capability.

## Initial research platform

**worker-03** is the intended Linux test host, previously used for SenseTrace research. Its exact hardware, operating system, timing facilities, and permissions must be inventoried **before** claiming any capability or conducting experiments. eBPF is an observation method, not an independent clock.

## Repository map

| File | Purpose |
| --- | --- |
| [Research questions](docs/RESEARCH_QUESTIONS.md) | Falsifiable hypotheses, confounders, decision criteria |
| [Clock model and measurement authority](docs/CLOCKS_AND_INDEPENDENCE.md) | Timer taxonomy and independence limitations |
| [Experiment protocol](docs/EXPERIMENT_PROTOCOL.md) | Staged baseline, stress, recovery, analysis |
| [worker-03 preparation](docs/WORKER_03.md) | Read-only inventory and readiness gates |
| [Timing-contract demonstration](docs/CONTRACT_DEMONSTRATION.md) | Positive control vs discovered effect; agent evaluation |
| [Data and reproducibility](docs/DATA_AND_REPRODUCIBILITY.md) | Run manifest, raw data, reporting standards |
| [Dependencies and provenance](docs/DEPENDENCIES.md) | Runtime requirements and imported-code provenance |
| [Safety and research ethics](docs/SAFETY_AND_ETHICS.md) | Load ceilings, stop conditions, honest claims |
| [Experimental journal](docs/EXPERIMENT_JOURNAL.md) | Implementation, worker execution and research findings kept separate |
| [Paired cross-stamp follow-up](docs/CSTATE_CROSSSTAMP_FOLLOWUP.md) | Five-pair worker-03 PHC, timer and cpuidle findings |
| [Controlled timerlat findings](docs/TIMERLAT_CONTROLLED_FINDINGS.md) | Thirty-trial timerlat and pressure campaign with raw-trace integrity checks |
| [CPU latency QoS findings](docs/CPU_LATENCY_QOS_FINDINGS.md) | Controlled 800-vs-default and 1,000-vs-800 µs idle-latency interventions, thermal stop, and integrity sensitivity results |
| [Turbostat QoS follow-up](docs/TURBOSTAT_QOS_FOLLOWUP.md) | Five-replicate 30-second threshold comparison with aligned per-trial CPU/package telemetry and observer-effect caveats |
| [TSC and ACPI PM pilot](docs/ACPI_PM_CLOCKSOURCE_PILOT.md) | Reversible, randomized clocksource pressure comparison with per-subcampaign restoration metadata |
| [TSC and ACPI PM findings](docs/ACPI_PM_CLOCKSOURCE_FINDINGS.md) | Three-pair timerlat comparison and verified source-dependent PHC cross-stamp availability |
| [Sampler affinity follow-up](docs/SAMPLER_AFFINITY_FOLLOWUP.md) | Five-pair worker-03 sampler-pinned timer and cpuidle findings |
| [Timerlat tracer smoke](docs/TIMERLAT_TRACING_SPIKE.md) | Built-in IRQ/thread tracer capability and per-CPU diagnostic |
| [Contributing](CONTRIBUTING.md) | Contribution and review expectations |

## Planned phases

1. **Inventory:** record worker-03's hardware, software, selected clocksource, power states, eBPF hooks, background services and reference candidates. The initial inventory is in [worker-03 preparation](docs/WORKER_03.md).
2. **Baseline:** measure timestamp acquisition gaps, absolute timer wakeup lateness, internal clock deltas, scheduler runnable-to-run latency and environmental context without ClockPressure-generated load. Ambient services are logged; baseline does not mean a physically idle host.
3. **Controlled pressure:** repeat under bounded CPU, memory, I/O, and scheduling workloads with randomized order and recovery intervals.
4. **Independent validation:** use an external timing reference with documented uncertainty before claiming real elapsed-time drift.
5. **Reproducibility:** replicate across sessions / configurations, publish raw evidence, and keep negative results.
6. **Contract demonstration:** produce an unambiguous false-pass test only when independently validated; distinguish synthetic examples from observed failures.

Do not run stressors on shared or production machines without permission. This prototype does not alter the selected clocksource, system time, firmware, boot arguments, CPU voltage or clock limits. The CPU campaign is bounded, pins its lower-priority workers to specified CPUs, collects temperature and pressure telemetry, and aborts at its configured CPU-package temperature ceiling.

## Build and run

ClockPressure separates the native timing path, pressure generation, system instrumentation, experiment control and analysis:

- `src/clockpressure_probe.c` records absolute `CLOCK_MONOTONIC` deadlines, wakeup lateness, `CLOCK_MONOTONIC_RAW`, `CLOCK_BOOTTIME`, realtime/TAI, RDTSCP/AUX, CPU IDs, sequential PTP reads and—when supported—paired `PTP_SYS_OFFSET_PRECISE` PHC/system cross-timestamps. It emits one JSON line per event.
- `experiments/workloads/cpu_pressure.py` provides bounded CPU workers pinned to an explicit list. Workers use a lower CFS priority and are stopped after each trial.
- `instrumentation/sched_wakeup.bt` records the target process's kernel `sched_wakeup` to `sched_switch` interval using `bpftrace`/`bpf_ktime_get_ns`. It is contextual evidence in the kernel monotonic domain, not a separate clock.
- `experiments/run_trial.py` captures the environment, low-rate thermal/frequency/PSI and per-CPU cpuidle residency context, clock-read gaps, raw samples, logs and checksums. It retains interrupted runs.
- `experiments/run_campaign.py` runs an uninstrumented pressure-free baseline first, then seed-randomizes replicated baseline/CPU-pressure pairs, allows recovery and collects a recovery observation after every pressure run.
- `analysis/analyze_runs.py` derives latency quantiles, internal and paired cross-timestamp rate comparisons, endpoint read-bracket bounds, environmental summaries, per-CPU C10 residency, CPU migrations and run-paired contrasts from retained raw runs. `analysis/analyze_timerlat.py` summarizes retained Linux timerlat tracer output by CPU and pairs IRQ/thread records with optional userspace-return latency.
- `experiments/run_timerlat_campaign.py` manages a guarded tracefs timerlat user-read path beside the normal probe, compares enabled and disabled arms, and preserves tracefs restoration evidence. `analysis/analyze_timerlat_campaign.py` reports paired probe and timerlat latency contrasts without treating them as clock-rate measurements.

On worker-03, from a checkout of the recorded revision:

```sh
make
python3 -m experiments.run_campaign \
  --duration-sec 30 --repeats 2 --observer both \
  --cpu-load-workers 4 --load-cpus 1,2,3,4 --pin-cpu -1 \
  --data-dir ~/clockpressure-data
python3 -m analysis.analyze_runs ~/clockpressure-data
python3 demos/timing_contract_positive_control.py
```

The runner uses `sudo -n` only for the read-only NIC PHC clock and temporary eBPF tracing when the invoking account lacks device access. The normal output directory is outside the checkout at `~/clockpressure-data/`; raw observations and their per-run manifests are preserved there. Run the native/unit checks with `make check`.

The default reference set is **not external**: Linux monotonic APIs and BPF timestamps are related. The I219-LM's hardware-assisted cross-timestamp is a better-aligned internal witness than sequential reads, but it is still uncalibrated and may share a physical frequency reference with the system timer. NTP tracking is recorded as context and is not treated as a short-window elapsed-time standard.

## Quantities and interpretation

Let `T_ref` be elapsed time from a **validated independent reference** and `T_dut` the device-under-test elapsed-time reading. Report signed fractional rate discrepancy as:

```text
relative_error = (T_dut - T_ref) / T_ref
error_ppm = relative_error * 1,000,000
```

A hypothetical 1% slow clock is `-10,000 ppm`; over 100 real seconds it reports 99 seconds. A 100-second report over 101 real seconds instead corresponds to about `-0.9901%` relative error. Differences between `CLOCK_MONOTONIC` and `CLOCK_MONOTONIC_RAW` alone are **not** evidence of physically independent clocks.

## References

- [Linux: clock sources and clock events](https://docs.kernel.org/timers/timekeeping.html)
- [Linux: timekeeping accessors](https://docs.kernel.org/core-api/timekeeping.html)
- [Linux: virtualization and timekeeping](https://docs.kernel.org/virt/kvm/x86/timekeeping.html)
- [Linux clock_gettime(2) manual](https://man7.org/linux/man-pages/man2/clock_gettime.2.html)
- [Linux eBPF ring buffer documentation](https://docs.kernel.org/bpf/ringbuf.html)

## License

Apache License 2.0. See [LICENSE](LICENSE). Contributions should preserve source provenance and any third-party attribution requirements.
