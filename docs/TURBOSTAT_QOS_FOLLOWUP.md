# Turbostat telemetry and 800/1,000 µs QoS follow-up

## Research question

Does the timerlat pressure response persist when a CPU idle-exit latency constraint removes C10 eligibility, and what concurrent CPU/package telemetry changes accompany that response? This experiment observes latency and hardware-state proxies. It does not independently measure elapsed time.

## Protocol and provenance

- Worker: `worker-03`, bare-metal Intel Core i7-9700, eight online CPUs; experiment code revision `7dacc8e`.
- Campaign: `20261028T073611Z-timerlat-campaign-21325dbd`; five randomized replicates of a 1,000 µs control request and an 800 µs intervention request. Each arm has 30-second baseline, four-core CPU-pressure, and recovery observations.
- Placement: four bounded `nice +10` CPU workers on CPUs 1–4; ClockPressure probe on CPU 6; `SCHED_FIFO` timerlat reader (priority 90) on CPU 7. The CPU DMA-latency request was checked per trial and closed after the trial.
- Telemetry: timerlat and `power:cpu_idle` traces on CPU 7; `turbostat` at one-second intervals, with rows for CPU 7. Its `Time_Of_Day_Seconds` labels were joined to the probe's host `CLOCK_REALTIME` boundaries. This is a same-host wall-clock join, not an independent time reference; samples at a condition edge can straddle it.
- Observer condition: the live process snapshot [`observer-process-snapshot.json`](../../.clockpressure-data/worker-03/timerlat-idle-qos-800-vs1000-turbostat-5x30-20261028/observer-process-snapshot.json) records turbostat affined to CPU 7, nice `-20`, `SCHED_OTHER`. Thus the collector shared CPU 7 with the timerlat reader in every condition. This is an explicit observer workload and limits generalization to uninstrumented runs. The `--cpu 7` setting limits displayed CPU rows; turbostat still collects counters across CPUs ([upstream turbostat manual](https://github.com/torvalds/linux/blob/v6.17/tools/power/x86/turbostat/turbostat.8)).
- Raw campaign and generated analysis are preserved in the hidden worker-data archive; [`campaign.json`](../../.clockpressure-data/worker-03/timerlat-idle-qos-800-vs1000-turbostat-5x30-20261028/campaign.json) is the archived manifest. The worker source directory is `/home/worker-03/clockpressure-data/timerlat-idle-qos-800-vs1000-turbostat-5x30-20261028/`. The `turbostat.tsv` SHA-256 is `8d1f2a68e011caebc2a81beb3edf332d77b841b821730c09bb91fc3768fb4eba`.

The analyzer revalidated all 30 timerlat trace hashes. It found 90,000 matched IRQ/thread activations, 89,970 user-return activations, and zero missing/mismatched traces, incomplete or duplicate activations, malformed latency lines, trace overruns, commit overruns, or dropped events. All 30 trials completed, every QoS request restored the prior 2,000,000,000 µs effective value, and tracefs returned to its initial `nop`/empty-event state. The system package temperature peaked at 77°C, below the 85°C stop threshold.

The statistics below are medians across five trial-level medians. Paired intervals resample the five replicate-level differences; they are descriptive and do not include calibration uncertainty, serial correlation, or campaign-to-campaign variation. The raw and generated reports contain every trial and metric.

## Observed trial medians

| QoS request | Condition | Probe wake P99 (µs) | Timerlat IRQ P99 (µs) | CPU 7 C10 (turbostat, %) | CPU 7 Bzy_MHz | Package power (W) | Package temp (°C) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 µs | Baseline | 420.283 | 360.669 | 90.335 | 1,153.5 | 4.035 | 45 |
| 1,000 µs | CPU pressure | 94.546 | 36.643 | 90.530 | 4,369 | 67.420 | 77 |
| 1,000 µs | Recovery | 422.050 | 354.723 | 90.300 | 1,145 | 3.960 | 49 |
| 800 µs | Baseline | 325.948 | 249.882 | 0 | 1,162.5 | 4.095 | 44 |
| 800 µs | CPU pressure | 119.501 | 37.126 | 0 | 4,370.5 | 67.445 | 77 |
| 800 µs | Recovery | 314.212 | 252.471 | 0 | 1,168 | 4.080 | 48 |

Every 30-second trial had 30 aligned CPU 7 telemetry samples. The pressure condition raised median package power by 63.53 W in the 1,000 µs arm and 63.37 W in the 800 µs arm; median package temperature rose 32.5°C and 32°C. CPU 7's busy frequency increased by roughly 3.2 GHz. In the 1,000 µs arm, CPU 7 remained in C10 for about 90% of each condition; under 800 µs, the per-CPU C10 counter was zero in all conditions. `Pkg%pc6` and `Pk%pc10` were zero in every row, including idle, and are not evidence of package-state entry or non-entry.

## Paired pressure effects

| Outcome (pressure minus baseline) | 1,000 µs control | 800 µs intervention |
| --- | ---: | ---: |
| ClockPressure wake P99 | −326.256 µs [−327.133, −324.296] | −209.866 µs [−227.961, −198.943] |
| Timerlat IRQ P99 | −323.684 µs [−327.336, −323.505] | −212.655 µs [−214.735, −186.611] |
| Timerlat thread P99 | −338.731 µs [−341.305, −334.554] | −221.470 µs [−223.539, −211.888] |
| Timerlat user-return P99 | −372.978 µs [−392.195, −372.012] | −260.659 µs [−262.803, −253.532] |
| CPU 7 turbostat `C10%` | −1.81 pp [−4.42, +4.93] | 0 pp [0, 0] |
| CPU 7 `Bzy_MHz` | +3,215.5 MHz [+3,204.7, +3,239.9] | +3,200 MHz [+3,172.8, +3,228.8] |
| Package power | +63.53 W [+62.60, +64.03] | +63.37 W [+62.58, +63.59] |
| Package temperature | +32.5°C [+31.6, +32.9] | +32°C [+30.7, +33.2] |

Intervals are the analyzer's descriptive 95% bootstrap intervals for the mean paired change, with five replicate pairs. The QoS-by-pressure difference-in-differences was +113.677 µs for wake P99 [ +97.587, +127.569 ] and +111.802 µs for timerlat IRQ P99 [ +108.924, +140.570 ]. The 800 µs request attenuated the pressure-associated latency reduction by about 112–114 µs but did not remove it.

## Interpretation

**Observed:** CPU pressure was associated with substantially lower wake and timerlat P99 latency in both QoS arms, and the response returned near baseline during recovery. The latency reduction remained when CPU 7 C10 residency was zero under the 800 µs request. With the 1,000 µs request, pressure also reduced latency while CPU 7 remained near 90% C10. This is inconsistent with a simple explanation in which avoiding CPU 7 C10 alone produces the entire pressure response. The QoS intervention changed idle eligibility and baseline latency, and attenuated the pressure response, so idle policy may contribute without being the sole mechanism.

**Correlated hardware-state changes:** pressure increased reported CPU 7 active frequency, package power and temperature. These changes are candidates for follow-up, not identified causes. The per-CPU C10 counter is not package C-state residency, and the available package C6/C10 columns were unusable in this dataset. Turbostat's CPU 7 affinity and high-priority nice value are also part of the measured system and may shape absolute latency and idle behavior.

**Clock-rate evidence:** no independent elapsed-time reference was collected; the report sets `clockrate_claim_allowed` to false. The paired PHC/MONORAW fit-rate contrasts included zero in both arms. A small MONOTONIC-versus-RAW pressure contrast appeared in the 800 µs arm (median −0.00150 ppm; descriptive interval −0.00191 to −0.00097 ppm). Those are related same-host clock domains, and the result does not establish absolute clock accuracy, physical oscillator drift, or a timing-contract false pass.

**Not demonstrated:** a physical elapsed-time discrepancy; a causal thermal, frequency, package-state, firmware or oscillator path; natural failure of the 100-second contract example; or an agent manipulating its evaluator. The reproduced timing-contract false pass remains the explicit software-maintained-timer positive control.

## Turbostat affinity smoke: relocation does not isolate the observer

After the campaign, a short smoke asked turbostat to collect CPU 7 counters while its process was moved to CPU 0 after the first sample. The initial observed affinity was `{7}`, the post-request snapshot was `{0}`, and shutdown showed `{7}`. A separate 4.19-second timeline sampled affinity 206 times at about 20 ms intervals: 45 observations were `{0}` through 0.8994 s and 161 were `{7}` from 0.9199 s onward. The outputs are retained in [`smoke.json`](../../.clockpressure-data/worker-03/turbostat-observer-affinity-smoke-20261028/smoke.json), [`timeline.json`](../../.clockpressure-data/worker-03/turbostat-observer-affinity-timeline-smoke-20261028/timeline.json), and the associated `turbostat.tsv` files. These are tool-behavior checks only; they contain no latency or clock-accuracy outcome.

The Linux v6.17 turbostat implementation migrates to the CPU being sampled for local counter reads ([upstream source](https://github.com/torvalds/linux/blob/v6.17/tools/power/x86/turbostat/turbostat.c)). The requested process affinity therefore cannot keep this collector off the sampled CPU. The experimental relocation option and its mocked isolation test were withdrawn; the runner now records process state without changing affinity. The main campaign remains explicitly subject to a CPU-7 turbostat observer condition.

| Smoke artifact | SHA-256 |
| --- | --- |
| `smoke.json` | `ec1597b7c2089db37d9874fb06d11543eae15e0696fae2a3df90c3a566de1c50` |
| first `turbostat.tsv` | `a011e0d85ac56ca50cd039106bb91d8b5d45d9bca05862dd853259d2fecc4120` |
| `timeline.json` | `dc7a730231af0473f0b4c48e6294ce2da7fdb2ab80f55bba2cefe3573d0c2afb` |
| timeline `turbostat.tsv` | `f13c7f9d65ecec159b56789e83ee2bd2fb6028efc970c99f4002439aa3498f34` |

## Next experiment

Inspect an alternate path for per-CPU frequency/idle/power telemetry, beginning with read-only sysfs interfaces and recording whether reads use kernel snapshots, per-CPU files, or cross-CPU calls. Worker-03 exposes per-CPU cpuidle `state0`–`state8` counters; measure sampling overhead and confirm CPU attribution before using them in a matched collector-placement experiment. The current clocksource is `tsc`, and `acpi_pm` is available; a short reversible comparison can test source-dependent timer and cross-stamp behavior. Neither experiment substitutes for a calibrated external elapsed-time reference.
