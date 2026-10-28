# Controlled timerlat and pressure findings

## Experiment record

- **Worker:** `worker-03`, Linux 6.17.1.
- **Campaign:** `20261028T044220Z-timerlat-campaign-9edb84e7`.
- **Code revision:** `b5c87c2`.
- **Design:** 30 trials: five randomized replicates for each of two arms, with baseline, pinned CPU-pressure and post-pressure recovery observations. One arm had the pinned userspace timerlat reader disabled; the other used the reader on CPU 7. The ClockPressure probe was pinned to CPU 6, and four nice `+10` workers were pinned to CPUs 1–4.
- **Observation:** 30 seconds per trial at a 10 ms period; 45,000 ClockPressure samples per arm.
- **Retained evidence:** worker `/home/worker-03/clockpressure-data/timerlat-controlled-20261028/`; local archive `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/timerlat-controlled-20261028/`.

The campaign runner randomized arm and baseline/pressure order within replicate, added a recovery run after pressure, and used a five-second settling wait. The timerlat reader ran at `SCHED_FIFO` priority 90. It is an observer workload, not an independent time reference.

## Integrity

All 30 trials completed. The 15 timerlat traces passed SHA-256 verification and were reparsed from raw text. They contained 45,000 matched IRQ/thread activation pairs, 44,985 user-return events, and zero incomplete or duplicate IRQ/thread activations, malformed latency lines, trace-buffer overruns, commit overruns, or dropped events. The timerlat reader completed 3,000 reads in each enabled trial. Tracefs settings were restored after every enabled trial.

The original campaign manifest listed the tracer-disabled arm among `timerlat_arms`; no timerlat trace was collected in that arm. The analyzer now recognizes this legacy manifest and only treats `timerlat_user*` arms as trace-enabled. The archived raw manifest is unchanged.

## Observations

Paired differences below are pressure minus that replicate's baseline. Values are medians over five replicate-level differences. Bracketed ranges are the analyzer's descriptive 95% bootstrap intervals for the mean of those five differences; they quantify resampling variation only, not calibration uncertainty or campaign-to-campaign variation.

| Outcome | Timerlat disabled | Timerlat userspace reader enabled |
| --- | ---: | ---: |
| ClockPressure wake-lateness P99 | −340.575 µs [−348.106, −335.469] | −327.256 µs [−333.224, −317.395] |
| Timerlat IRQ P99 | — | −315.647 µs [−317.859, −313.347] |
| Timerlat thread P99 | — | −328.228 µs [−341.633, −323.795] |
| Timerlat user-return P99 | — | −364.604 µs [−383.847, −355.643] |
| PHC/MONORAW fitted rate contrast | −0.000116 ppm [−0.000184, +0.000027] | +0.000103 ppm [−0.000043, +0.000160] |
| Aggregate C10 residency | −45.65 percentage points | −45.07 percentage points |
| Probe CPU 6 C10 residency | +6.45 percentage points | +2.78 percentage points |
| Timerlat CPU 7 C10 residency | +0.35 percentage points | +4.09 percentage points |

Pressure reduced all three timerlat P99 latency measures in the enabled arm. The change was already present in the IRQ-context measurement and continued through the thread and user-return stages. This localizes a latency change in the instrumented timer path, but does not establish why the interrupt arrived earlier or prove anything about clock rate.

Aggregate C10 residency fell because the four pinned worker CPUs spent much less time idle. On the probe and timerlat CPUs, C10 residency instead rose slightly while measured P99 latency fell. Those per-CPU counters do not support a simple explanation in which pressure improves latency by keeping those two CPUs out of deep idle. The subsequent 800 µs QoS intervention shifted C10 residency toward C9, improved baseline latency, and attenuated but did not remove the pressure response; see the [QoS findings](CPU_LATENCY_QOS_FINDINGS.md). Package C-state behavior was not measured.

Timerlat enabled versus disabled changed the probe's baseline wake-lateness P99 by a median −16.152 µs (descriptive interval −25.852 to −6.102 µs). The paired observer contrast was −0.549 µs under pressure (−3.947 to +5.337 µs) and +3.661 µs in recovery (−9.558 to +7.521 µs). This suggests a modest baseline observer effect in this design, with no resolved observer contrast in the latter two conditions. The contrast combines the tracer, FIFO reader and their system-wide effects.

The paired PHC/MONORAW rate contrasts include zero in both arms. They are internal comparisons on one host with related clock domains, not an independently calibrated accuracy measurement. No pressure-related clock-rate effect was resolved. The negative latency differences must not be interpreted as a faster clock or a physical elapsed-time discrepancy.

## Research status

**Observed:** under this worker's configuration, pinned CPU pressure substantially reduced timer-wakeup and timerlat P99 latency, and the latency response appeared at IRQ context as well as later stages.

**Not established:** clock-rate error, a discrepancy in true elapsed time, the causal mechanism, package-state behavior, or a natural timing-contract false pass. The only reproduced false pass remains the explicit software-maintained-timer positive control. No agent has been observed compromising a timing evaluator.

The follow-up compared the default policy with `/dev/cpu_dma_latency=800`; see the [QoS intervention findings](CPU_LATENCY_QOS_FINDINGS.md). The request removed measured C10 residency and attenuated, but did not eliminate, the pressure-associated latency reduction. That result remains a same-host latency finding, not an elapsed-time discrepancy.
