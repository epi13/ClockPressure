# ClockPressure

**Investigating whether system pressure can influence time measurements—and cause a program to pass a timing contract while failing its intended objective.**

ClockPressure is an open, Linux-focused experimental research project. It uses low-overhead observability (including eBPF where appropriate), controlled workloads, and independently validated measurements to distinguish:

- **Scheduling or timer-event jitter:** work or callbacks happen late, even while the system's clock continues advancing correctly.
- **Measurement / accounting error:** a program's timer logic undercounts real elapsed time, such as a tick-counting loop that ignores delayed ticks.
- **Clock-rate error:** a reported clock advances at a different rate from a trustworthy external time reference.
- **Contract / evaluation failure:** a test reports success because its measurement authority differs from the requirement being tested.

**Status:** Research design and documentation only. No ClockPressure experiments, worker-03 results, or clock anomalies are claimed yet.

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
| [Safety and research ethics](docs/SAFETY_AND_ETHICS.md) | Load ceilings, stop conditions, honest claims |
| [Contributing](CONTRIBUTING.md) | Contribution and review expectations |

## Planned phases

1. **Inventory:** record host identity, clocksource, suspend policy, kernel, virtualization, available eBPF hooks, and reference instrumentation.
2. **Baseline:** measure timestamp overhead, timer wakeup lateness, cross-clock deltas, instrument loss, and environmental stability at idle.
3. **Controlled pressure:** repeat under bounded CPU, memory, I/O, and scheduling workloads with randomized order and recovery intervals.
4. **Independent validation:** use an external timing reference with documented uncertainty before claiming real elapsed-time drift.
5. **Reproducibility:** replicate across sessions / configurations, publish raw evidence, and keep negative results.
6. **Contract demonstration:** produce an unambiguous false-pass test only when independently validated; distinguish synthetic examples from observed failures.

Do not run stressors on shared or production machines without permission. No global clock modifications, firmware experiments, overclocking, or unbounded load are part of the default protocol.

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
