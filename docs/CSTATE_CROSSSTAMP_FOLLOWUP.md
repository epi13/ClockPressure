# worker-03 paired cross-stamp and cpuidle follow-up

**Observation date:** 2026-10-28 UTC
**Campaign:** `20261028T040105Z-campaign-ad8f0fc8` (seed `20261029`)
**Probe revision:** `4a4213c` (`4a4213c` source checkout on worker-03)

## Question and design

The first campaign showed lower timer-wakeup lateness under four-core pressure, but it had only sequential PHC reads and no cpuidle counters. This follow-up asked whether the change remained visible alongside paired PHC/system cross-timestamps and whether it tracked per-CPU idle residency.

The campaign ran a no-load baseline sentinel, then five randomized matched pairs of baseline and CPU-pressure trials, followed by a recovery observation after each pressure trial. It used 30-second windows at 100 Hz, four `nice +10` workers pinned to CPUs 1–4, no scheduler eBPF observer, and an unpinned sampler. No clock, firmware, power policy, or kernel settings were changed. Each run retained `PTP_SYS_OFFSET_PRECISE` pairs and per-CPU cpuidle counters. The paired analysis uses independent run summaries as its unit; its bootstrap ranges are descriptive and do not account for systematic error or session-level dependence.

All 16 runs completed: one sentinel, five baseline trials, five pressure trials, and five recovery observations. They contain 48,000 timer samples and 48,032 valid paired cross-timestamps. All retained artifact checksums match.

The worker command was:

```sh
sudo -n python3 -m experiments.run_campaign \
  --duration-sec 30 --period-us 10000 --repeats 5 --observer off \
  --cpu-load-workers 4 --load-cpus 1,2,3,4 --pin-cpu -1 \
  --recovery-seconds 5 --seed 20261029 \
  --data-dir /home/worker-03/clockpressure-data/cstate-crossstamp-20261028
```

## Observations

| Outcome | Baseline median | CPU-pressure median | Paired pressure minus baseline | Recovery minus baseline |
| --- | ---: | ---: | ---: | ---: |
| Run P99 timer wake lateness | 434.5 µs | 92.3 µs | −336.424 µs; descriptive interval −345.633 to −331.863 µs | −0.116 µs; interval −14.097 to +5.561 µs |
| Paired PHC/MONORAW offset-fit rate | −0.298072 ppm | −0.297972 ppm | +0.0000319 ppm; interval −0.0000088 to +0.0001905 ppm | +0.0000909 ppm; interval +0.0000644 to +0.0001194 ppm |
| Aggregate per-CPU C10 residency | 96.00% | 50.46% | −45.63 percentage points; interval −46.02 to −45.31 points | +0.073 points; interval −0.095 to +0.330 points |

Intervals are percentile-bootstrap ranges for the mean difference over five matched run-level differences, not calibrated uncertainty bounds. The confidence interval terminology is intentionally avoided: serial samples are not independent replicates, and cross-stamp capture and calibration uncertainty remain unquantified.

Per-CPU matched median C10 changes were −87.8, −85.9, −88.1, and −88.3 percentage points on worker CPUs 1–4. CPUs 5–7 changed by −2.3, −0.8, and −2.1 points; CPU 0 changed by −12.4 points. This distribution matches the pinned CPU work and shows why the aggregate C10 decline should not be interpreted as a package-wide state measurement.

Sampler placement varied in this unpinned campaign. Across the five randomized baseline trials the median was 10 CPU changes between adjacent samples; under pressure it was 5, and in recovery it was 3. During pressure, sampled execution occurred on CPUs 0 and 5–7, outside the worker set on CPUs 1–4. This is a plausible source of condition-dependent scheduling context, not an explanation established by these data. The pinned-CPU follow-up tests that placement question directly.

The pressure-associated wakeup change was large and reversed during recovery. C10 residency also fell under load and returned to baseline; four of eight CPUs were deliberately kept busy, so the aggregate residency change is expected in direction and does not establish a package C-state transition or explain the wakeup effect. The sampler was unpinned and generally ran on CPUs outside the four worker CPUs. Whether placement or CPU migration contributes remains open.

The paired PHC/MONORAW fit difference under pressure was about 0.032 parts per billion and its descriptive interval included zero. This is not a resolved clock-rate effect. Even the recovery fit difference is not evidence of a clock change: the cross-stamp is an internal comparison, its uncertainty is not calibrated, and its hardware/software dependencies may be shared with the system timing path but have not been independently characterized. A delayed wakeup remains distinct from a clock-rate discrepancy.

CPU package temperature peaked at 81°C, below the 85°C stop threshold; CPU PSI `some avg10` peaked at 3.90%. The baseline, pressure, and recovery per-run median maxima were 42°C, 75°C, and 54°C respectively. The observed cpuidle `C10` quantity is the fraction of aggregate per-CPU time capacity, not package residency.

## What the evidence supports

- On this worker and in this campaign, ordinary four-core CPU pressure repeatedly reduced timer wakeup lateness and the observed change returned after pressure stopped.
- The same pressure treatment reduced per-CPU C10 residency, as expected when four CPUs are occupied; this telemetry does not establish the causal path to wakeup latency.
- The paired cross-stamp did not resolve a pressure-associated rate change at the observed scale. This is a negative result about this setup and measurement, not proof of perfect clock accuracy.
- These observations do not show a false pass from system-clock behavior, physical elapsed-time error, firmware influence, or agent reward hacking.

## Reproduction and provenance

Worker data: `/home/worker-03/clockpressure-data/cstate-crossstamp-20261028`
Local preserved copy: `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/cstate-crossstamp-20261028`

The raw manifests record the per-run source revision and SHA-256 checksums. `analysis.json` and `analysis.md` are regenerable with:

```sh
python3 -m analysis.analyze_runs /path/to/cstate-crossstamp-20261028
```

The campaign and analysis logs are separate from this report; this document records findings and their limits, not new measurements made during report generation.

## Follow-up

The sampler-pinned campaign has been completed; see [the pinned-sampler findings](SAMPLER_AFFINITY_FOLLOWUP.md). A two-second tracefs smoke verified Linux `timerlat` support and exposed substantial per-CPU latency differences; see [the timerlat tracer report](TIMERLAT_TRACING_SPIKE.md). The next measurement should repeat controlled baseline/pressure/recovery conditions with timerlat enabled and disabled, retaining the ClockPressure end-to-end result. The PHC comparison remains internal and uncalibrated.
