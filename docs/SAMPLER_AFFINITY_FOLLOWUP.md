# worker-03 pinned-sampler follow-up

**Observation date:** 2026-10-28 UTC
**Campaign:** `20261028T041421Z-campaign-d4214b64` (seed `20261030`)
**Probe revision:** `4a4213cb9fa42e992f94e88f41432464917ef632`

## Question and design

The previous five-pair campaign used an unpinned sampler. Under pressure, Linux scheduled it on CPUs outside the four-worker set, and its CPU placement and migration counts differed by condition. This follow-up tested whether sampler migration or placement was required for the wake-latency change by pinning the sampler to CPU 7 while the four pressure workers remained pinned to CPUs 1–4.

The campaign collected one baseline sentinel, five randomized matched baseline/pressure pairs, and one recovery observation after each pressure run. It used 30-second windows at 100 Hz, no scheduler eBPF observer, and no clock, firmware, frequency-policy or kernel-setting changes. All sampled events in every run came from CPU 7; the recorded adjacent-sample migration count was zero.

All 16 runs completed: one sentinel, five trials per baseline and pressure condition, and five recoveries. They retained 48,000 timer samples and 48,032 valid paired PHC/system cross-timestamps. Every per-run artifact checksum verifies.

The worker command was:

```sh
sudo -n python3 -m experiments.run_campaign \
  --duration-sec 30 --period-us 10000 --repeats 5 --observer off \
  --cpu-load-workers 4 --load-cpus 1,2,3,4 --pin-cpu 7 \
  --recovery-seconds 5 --seed 20261030 \
  --data-dir /home/worker-03/clockpressure-data/sampler-pinned-cpu7-20261028
```

## Observations

| Outcome | Baseline median | CPU-pressure median | Paired pressure minus baseline | Recovery minus baseline |
| --- | ---: | ---: | ---: | ---: |
| Run P99 timer wake lateness | 437.9 µs | 97.8 µs | −339.935 µs; descriptive interval −344.816 to −334.886 µs | −3.928 µs; interval −12.962 to +4.166 µs |
| Paired PHC/MONORAW offset-fit rate | −0.298034 ppm | −0.297961 ppm | +0.0000551 ppm; interval −0.0000302 to +0.0000920 ppm | +0.0000012 ppm; interval −0.0000493 to +0.0001221 ppm |
| Aggregate per-CPU C10 residency | 96.17% | 50.72% | −45.52 percentage points; interval −45.87 to −43.79 points | −0.20 points; interval −1.14 to +0.69 points |
| Adjacent-sample CPU migrations | 0 | 0 | 0 | 0 |

Intervals are percentile-bootstrap ranges for the mean difference over five matched run-level differences. They are descriptive, not calibrated uncertainty bounds; cross-stamp capture and calibration uncertainty remain unquantified.

CPU 7 stayed on the same CPU and its per-CPU C10 residency increased by 3.73 percentage points under pressure (descriptive interval +2.87 to +6.49 points), while P99 wake lateness fell. C10 residency fell by about 86–88 points on worker CPUs 1–4, changed by about −0.8 to −1.6 points on CPUs 5–6, and fell by 13.58 points on CPU 0. During recovery, per-CPU C10 values returned close to their baseline values. This makes the aggregate C10 reduction expected from worker placement and shows that CPU 7's local C10 fraction does not simply track wakeup latency.

The pressure-associated timer-lateness change persisted with sampler migration eliminated. The point estimate was similar to the preceding unpinned campaign (−339.9 µs versus −336.4 µs); this comparison was not designed as a formal equivalence test, but it weakens sampler migration as a necessary explanation. The mechanism remains unresolved. Wake lateness still combines timer delivery, scheduling and timestamp acquisition.

The paired PHC/MONORAW rate-fit difference under pressure was about 0.055 parts per billion; its descriptive range included zero. No pressure-associated clock-rate change is resolved. The PHC cross-stamp is not an external calibrated elapsed-time reference.

CPU package telemetry peaked at 81°C, below the 85°C stop threshold. CPU PSI `some avg10` peaked at 3.93%. The baseline, pressure and recovery group median per-run package maxima were 47°C, 77°C and 58°C respectively.

## What the evidence supports

- The timer-wakeup response persisted in five matched trials when the sampler was fixed to CPU 7 with zero observed migration. Sampler migration is therefore not required for this response under these conditions.
- The per-CPU C10 change followed load placement on CPUs 1–4; CPU 7's C10 fraction slightly increased while wakeup lateness fell. The data do not show package C-state behavior or establish a causal path.
- The paired cross-stamp again did not resolve a pressure-related rate change. This does not prove absolute time accuracy.
- No timing-contract false pass from host clock behavior, physical elapsed-time error, firmware effect, or agent reward hacking was observed.

## Reproduction and provenance

Worker data: `/home/worker-03/clockpressure-data/sampler-pinned-cpu7-20261028`
Local preserved copy: `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/sampler-pinned-cpu7-20261028`

Analysis can be regenerated with:

```sh
python3 -m analysis.analyze_runs /path/to/sampler-pinned-cpu7-20261028
```

## Next experiment

The response does not require sampler migration, and the cross-stamp remains stable within this setup's unresolved uncertainty. A short tracefs smoke verified that Linux timerlat is available; its per-CPU IRQ/thread results were highly uneven, so they need controlled repetitions before interpretation. The next experiment should compare baseline/pressure/recovery with timerlat enabled and disabled while retaining ClockPressure's end-to-end outcome. This may identify which part of the timer-to-userspace path changes under pressure, but it still cannot establish clock-rate accuracy without an independent elapsed-time reference.
