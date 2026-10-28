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

## Research status

**Supports:** under this worker's conditions, a global latency constraint that removed C10 reduced baseline timer-path P99 latency by about 105 µs and attenuated the pressure-associated latency reduction by about 105 µs. Pressure still produced a large latency change while C10 residency was zero.

**Does not establish:** C10 as the unique causal mechanism, an actual elapsed-time discrepancy, clock-rate manipulation, or a natural timing-contract false pass. The only reproduced false pass remains the explicit software-timer positive control.

**Next experiment:** compare two explicit requests straddling the measured C10 exit latency (800 µs and 1,000 µs) to separate the C10 threshold from having any active QoS request. The runner and analyzer now support a named control arm with a second request target. Repeat the small PHC/MONORAW slope comparison as exploratory only, and pursue an independently calibrated elapsed-time reference before making a hardware-time claim.
