# CPU latency QoS intervention findings

## Experiment record

- **Worker:** `worker-03`, Linux 6.17.1.
- **Campaign:** `20261028T052349Z-timerlat-campaign-44866da1`.
- **Code revision:** `8846d73`.
- **Design:** five randomized replicates with timerlat enabled in both arms. The control used the existing global CPU latency QoS policy; the intervention held a global `/dev/cpu_dma_latency=800` request during each trial. Each arm included a baseline, four-CPU pressure, and recovery observation. The recovery trial followed a 30-second wait; the runner also inserted a 30-second idle cooldown after every trial.
- **Placement:** ClockPressure probe CPU 6, pinned `SCHED_FIFO` timerlat reader CPU 7, and four lower-priority pressure workers on CPUs 1–4.
- **Observation:** 30 seconds at a 10 ms period; five runs per arm and condition.
- **Raw evidence:** worker `/home/worker-03/clockpressure-data/timerlat-cpu-latency-qos-800us-20261028/`; local archive `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/timerlat-cpu-latency-qos-800us-20261028/`.

The global QoS interface accepts a latency constraint for CPU idle states; closing the request descriptor removes it ([Linux PM QoS interface](https://docs.kernel.org/6.18/power/pm_qos_interface.html), [CPU idle documentation](https://docs.kernel.org/6.13/admin-guide/pm/cpuidle.html)). worker-03's measured C10 exit latency is 890 µs, so the 800 µs target was chosen to exclude states with a longer exit latency while allowing shallower states. It is a policy intervention, not a clock or elapsed-time reference.

An initial `0 µs` attempt was stopped by the established 85°C package guard after five completed trials; the sixth trial reached 86°C. No safety threshold was raised. The runner had incorrectly written `status: complete` after that early break. The corrected code preserves failures, and the analyzer now reports the unchanged raw campaign as failed based on its sixth trial record. That partial campaign is preserved separately and is not included below.

## Integrity and worker recovery

All 30 trials in the 800 µs campaign completed: five in each arm/condition cell. All 30 timerlat traces passed SHA-256 verification and reparsing. They contained 90,000 matched IRQ/thread activation pairs, 89,970 user-return events, and zero incomplete or duplicate activations, malformed lines, overruns, commit overruns, or dropped events. Each userspace reader completed 3,000 reads. Tracefs was restored after all 30 trials.

In all 15 intervention trials, the effective request changed from 2,000,000,000 µs to 800 µs and returned to 2,000,000,000 µs after close. The maximum package temperature recorded was 77°C. At completion, `current_tracer=nop`, tracing was enabled as before, and the effective QoS value was 2,000,000,000 µs.

## Pressure response with and without the QoS constraint

Values are pressure minus that replicate's baseline. Each median is over five paired run-level differences; brackets are descriptive 95% bootstrap intervals for the mean of those differences. They do not include clock calibration uncertainty or between-campaign variation.

| Outcome | Existing QoS policy | QoS target 800 µs |
| --- | ---: | ---: |
| ClockPressure wake-lateness P99 | −326.430 µs [−331.737, −321.903] | −225.537 µs [−234.007, −42.802] |
| Timerlat IRQ P99 | −308.701 µs [−315.547, −285.660] | −195.459 µs [−207.190, −177.892] |
| Timerlat thread P99 | −323.575 µs [−331.850, −311.904] | −209.410 µs [−219.371, −204.237] |
| Timerlat user-return P99 | −359.770 µs [−375.023, −355.187] | −253.319 µs [−264.572, −248.754] |

The difference-in-differences estimates how much the QoS intervention changed the pressure response. A positive value means pressure reduced latency less under the QoS constraint:

| Outcome | QoS effect on pressure response |
| --- | ---: |
| ClockPressure wake-lateness P99 | +99.771 µs [+92.776, +282.525] |
| Timerlat IRQ P99 | +106.270 µs [+91.813, +122.988] |
| Timerlat thread P99 | +104.845 µs [+101.285, +121.294] |
| Timerlat user-return P99 | +106.451 µs [+95.787, +122.547] |

The C10 residency counters confirm that the intervention changed the idle-state mix. At baseline, QoS800 versus control reduced C10 by 86.47 percentage points on probe CPU 6 and 85.47 points on timerlat CPU 7, while C9 residency increased by 89.48 and 82.63 points. C10 residency remained zero on both CPUs throughout the intervention arm. The same constraint reduced ClockPressure wake P99 by 105.23 µs at baseline. Timerlat IRQ, thread, and user-return P99s were each about 105 µs lower at baseline under QoS800.

Under pressure, the two arms' timerlat P99 outcomes were nearly the same. Yet pressure still reduced latency substantially under QoS800: about 195 µs at IRQ context, 209 µs at thread context, and 253 µs at user return. Thus, the C10 constraint accounts for part of the measured baseline/pressure contrast, while a large pressure-associated latency change remains when C10 is absent. The QoS intervention altered more than one state counter, so this does not isolate C10 as the sole cause.

In the existing-policy arm, pressure increased C10 residency by 4.64 points on CPU 6 and 3.02 points on CPU 7 while all three timerlat P99 measures fell by about 309–360 µs. That is evidence against a simple explanation that pressure improves latency merely by keeping these CPUs out of C10. Residency percentages measure time in states, not the latency of each state exit.

## Clock-rate interpretation

The pressure-minus-baseline `PTP_SYS_OFFSET_PRECISE` fit was −0.0000966 ppm (−0.0966 ppb) under the existing policy and +0.0000064 ppm (+0.0064 ppb) under QoS800. The difference-in-differences was +0.1190 ppb, with a descriptive interval of +0.0939 to +0.1794 ppb. This is an exploratory relation between the NIC PHC and `CLOCK_MONOTONIC_RAW` on the same host.

It is not verified clock drift. The fit uses 3,002 serially correlated cross-timestamp pairs per run; serial dependence and capture uncertainty are not modeled. The median absolute fit residual is about 41 ns, while a 0.119 ppb slope amounts to about 3.6 ns over a 30-second observation. The preceding timerlat campaign estimated a pressure contrast of the opposite sign, so this small relation has not reproduced consistently. No calibrated external elapsed-time reference was present.

## Initial QoS campaign status

**Supports:** under this worker's conditions, a global latency constraint that removed C10 reduced baseline timer-path P99 latency by about 105 µs and attenuated the pressure-associated latency reduction by about 105 µs. Pressure still produced a large latency change while C10 residency was zero.

**Does not establish:** C10 as the unique causal mechanism, an actual elapsed-time discrepancy, clock-rate manipulation, or a natural timing-contract false pass. The only reproduced false pass remains the explicit software-timer positive control.

**Next experiment:** the direct comparison between 800 µs and 1,000 µs requests is complete below. The next mechanism-focused experiment should connect each timerlat activation to the preceding idle-state transition. An independently calibrated elapsed-time reference is still required before making a hardware-time claim.

## Explicit 800 vs 1,000 microsecond threshold follow-up

### Design and integrity

- **Worker and campaign:** `worker-03`, campaign `20261028T061004Z-timerlat-campaign-989b334f`, recorded at code revision `e03c69b`.
- **Design:** five randomized replicates in each of two arms, with timerlat enabled in both. The control explicitly requested 1,000 µs from `/dev/cpu_dma_latency`; the intervention requested 800 µs. Each arm included baseline, four-CPU pressure and recovery. Trials ran for 30 seconds at 100 Hz, with a 30-second wait before recovery and a 30-second cooldown between trials.
- **Placement:** probe CPU 6, timerlat reader CPU 7, and four lower-priority pressure workers on CPUs 1–4. The same thermal stop at 85°C remained enabled.
- **Raw evidence:** worker `/home/worker-03/clockpressure-data/timerlat-c10-threshold-20261028/`; local archive `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/timerlat-c10-threshold-20261028/`.

All 30 trials completed, with five observations per arm/condition cell. The 30 traces passed checksum and reparsing checks. They contained 90,000 matched IRQ/thread activations and 89,970 user-return activations, with no incomplete or duplicate pairs, malformed lines, ring-buffer overruns or dropped events. Every reader completed 3,000 reads. All 15 control requests changed 2,000,000,000 µs to 1,000 µs and back; all 15 intervention requests changed it to 800 µs and back. Tracefs was restored after each trial. The maximum package temperature was 77°C; the worker finished with `current_tracer=nop` and tracing enabled as before.

During late-campaign diagnostics, I opened `trace_pipe` shortly after a status poll had observed the timerlat tracer active. Reading this interface can consume buffered events, and the exact timing relative to trial 22 is uncertain. Trial 22's saved trace still contains IRQ and thread IDs 1–3,000 and user-return IDs 1–2,999, with no gaps or duplicates and zero recorded buffer losses. The normal final user-return is absent as in the other trials. The file checksum verifies the saved artifact, not the absence of a transient observer effect. I therefore retained the raw trial but also computed a sensitivity analysis excluding its QoS-800 pressure record.

### Measured C10 eligibility and timer latency

At 1,000 µs, C10 remained eligible because the measured C10 exit latency is 890 µs. The target CPU counters confirm that C10 was used. At 800 µs, measured C10 residency was zero on both observation CPUs throughout all conditions:

| C10 residency | 1,000 µs request: baseline / pressure / recovery | 800 µs request: baseline / pressure / recovery |
| --- | ---: | ---: |
| Probe CPU 6 | 89.27% / 90.18% / 86.95% | 0% / 0% / 0% |
| Timerlat CPU 7 | 87.42% / 90.59% / 87.32% | 0% / 0% / 0% |
| Aggregate per-CPU capacity | 94.20% / 48.56% / 94.62% | 0% / 0% / 0% |

The aggregate pressure reduction is expected because CPUs 1–4 were kept busy. Residency counters are time fractions; they do not report the actual exit latency of an individual wakeup.

Pressure-minus-baseline values below are medians of five paired run-level differences. Brackets are descriptive 95% bootstrap intervals for their mean; they do not model cross-campaign variation or clock calibration uncertainty.

| Outcome | 1,000 µs request | 800 µs request | QoS-by-pressure difference-in-differences |
| --- | ---: | ---: | ---: |
| ClockPressure wake-lateness P99 | −325.545 µs [−332.726, −321.911] | −218.477 µs [−223.667, −204.679] | +107.068 µs [+102.537, +127.035] |
| Timerlat IRQ P99 | −315.618 µs [−316.512, −311.537] | −206.700 µs [−213.758, −195.348] | +107.399 µs [+98.841, +120.984] |
| Timerlat thread P99 | −324.918 µs [−327.800, −322.075] | −219.263 µs [−224.660, −211.389] | +103.627 µs [+98.167, +115.497] |
| Timerlat user-return P99 | −362.533 µs [−363.593, −358.283] | −252.794 µs [−255.412, −252.243] | +106.048 µs [+105.240, +110.499] |

At baseline, the 800 µs arm reduced each P99 by about 104–108 µs relative to the 1,000 µs arm, matching the large C10-to-shallower-state shift. Under pressure, the direct 800-minus-1,000 µs timerlat differences were small: IRQ +0.172 µs [−0.811, +0.613], thread +0.175 µs [−0.443, +0.582], and user-return −0.675 µs [−1.787, +2.092]. ClockPressure wake P99 differed by +1.870 µs [+0.536, +12.523].

Excluding trial 22 leaves four matched pressure replicates. The pressure-response interaction remains similar: wake P99 +107.742 µs [+101.404, +131.678], IRQ +103.589 µs [+96.701, +115.026], thread +101.068 µs [+96.802, +113.965], and user-return +105.740 µs [+104.995, +108.910]. The direct 800-minus-1,000 µs pressure differences also remain small: wake +1.357 µs [+0.139, +14.417], IRQ −0.094 µs [−1.057, +0.663], thread +0.040 µs [−0.598, +0.682], and user-return −1.236 µs [−2.006, +2.738]. This sensitivity check leaves the interpretation unchanged, while trial 22 remains explicitly flagged.

### Interpretation and clock-rate limits

The threshold comparison reproduces a baseline latency reduction when the 800 µs constraint excludes measured C10, but the much larger pressure-associated latency reduction persists in both arms. In the 1,000 µs arm, CPUs 6 and 7 spent about 90% of the observation in C10 even during pressure, while their timerlat P99 still fell by roughly 0.32–0.36 ms. In the 800 µs arm, those CPUs recorded no C10 residency, yet timerlat P99 fell by roughly 0.21–0.25 ms. C10 occupancy alone therefore does not account for the pressure response. This experiment does not isolate C10 as the unique cause of the baseline arm difference; the global latency request also changes other idle-state choices.

The pressure difference-in-differences for the `PTP_SYS_OFFSET_PRECISE` PHC/`CLOCK_MONOTONIC_RAW` fit was +0.0000465 ppm (+0.0465 ppb), with an interval from −0.0000595 to +0.0001184 ppm. This corresponds to about 1.4 ns over 30 seconds at the point estimate, and the interval includes zero. The same-host `CLOCK_MONOTONIC` versus RAW pressure interaction also includes zero. These interfaces share system timekeeping dependencies, and the PHC cross-stamp is not a calibrated external elapsed-time reference. Neither result establishes clock drift.

**Supports:** the request threshold reproducibly changes measured idle-state residency; C10 exclusion reduces baseline timer-path P99; and a substantial pressure-associated scheduling/timer-latency response remains with C10 excluded.

**Does not establish:** a C10-only mechanism, a physical clock-rate change, a discrepancy in actual elapsed time, a natural timing-contract false pass, or reward hacking.

**Next:** capture per-transition CPU idle state entry/exit events alongside timerlat on CPUs 6 and 7, then test whether individual wake latencies track the preceding idle state and residency duration. Continue seeking an independently calibrated elapsed-time reference.

The subsequent five-replicate, 30-second threshold campaign added timestamp-aligned turbostat telemetry and confirmed the pressure-associated timerlat response. It also exposed that turbostat itself was affined to CPU 7 during measurement. See [the turbostat QoS follow-up](TURBOSTAT_QOS_FOLLOWUP.md) for per-trial power/frequency/temperature results and the observer limitation.
