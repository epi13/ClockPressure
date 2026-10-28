# ClockPressure

**Investigating whether system pressure can influence time measurements—and cause a program to pass a timing contract while failing its intended objective.**

ClockPressure is an open, Linux-focused experimental research project. It uses low-overhead observability (including eBPF where appropriate), controlled workloads, and independently validated measurements to distinguish:

- **Scheduling or timer-event jitter:** work or callbacks happen late, even while the system's clock continues advancing correctly.
- **Measurement / accounting error:** a program's timer logic undercounts real elapsed time, such as a tick-counting loop that ignores delayed ticks.
- **Clock-rate error:** a reported clock advances at a different rate from a trustworthy external time reference.
- **Contract / evaluation failure:** a test reports success because its measurement authority differs from the requirement being tested.

**Status:** Initial executable instrumentation is implemented and its local functionality checks pass. worker-03 has been inventoried. The first worker-03 baseline and pressure campaign are still pending; no ClockPressure hardware result or clock anomaly is claimed yet.

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

- `src/clockpressure_probe.c` records absolute `CLOCK_MONOTONIC` deadlines, wakeup lateness, `CLOCK_MONOTONIC_RAW`, `CLOCK_BOOTTIME`, realtime/TAI, RDTSCP/AUX, CPU IDs and an optional PTP hardware clock. It emits one JSON line per event.
- `experiments/workloads/cpu_pressure.py` provides bounded CPU workers pinned to an explicit list. Workers use a lower CFS priority and are stopped after each trial.
- `instrumentation/sched_wakeup.bt` records the target process's kernel `sched_wakeup` to `sched_switch` interval using `bpftrace`/`bpf_ktime_get_ns`. It is contextual evidence in the kernel monotonic domain, not a separate clock.
- `experiments/run_trial.py` captures the environment, low-rate thermal/frequency/PSI context, per-clock read gaps, raw samples, logs and checksums. It retains interrupted runs.
- `experiments/run_campaign.py` runs an uninstrumented pressure-free baseline first, then seed-randomizes replicated baseline/CPU-pressure pairs, allows recovery and collects a recovery observation after every pressure run.
- `analysis/analyze_runs.py` derives latency quantiles and internal clock-rate comparisons from retained raw runs.

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

The default initial reference set is **not external**: Linux monotonic APIs and BPF timestamps are related, while the Intel NIC PHC is only a candidate independent oscillator until its rate, capture uncertainty and dependency path are characterized. NTP tracking is recorded as context and is not treated as a suitable short-window elapsed-time standard.

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
