# Controlled timerlat observer campaign

## Research question

The earlier worker-03 campaigns found a pressure-associated change in end-to-end timer wake lateness, while same-host PHC/MONORAW comparisons resolved no pressure-related rate change. The existing `timerlat_fd` smoke established that Linux can report IRQ-context, timerlat-thread, and return-to-userspace latency, but the smoke was not a controlled workload comparison.

The `observer` design compares randomized baseline, CPU-pressure, and recovery observations with the pinned userspace timerlat reader disabled and enabled. ClockPressure collects its end-to-end absolute-sleep outcome in both arms. The `cpu_latency_qos` design keeps timerlat active in both arms and compares the default CPU idle-latency policy with a temporary `/dev/cpu_dma_latency` request. With `--control-dma-latency-us`, it instead compares two active QoS requests, which can bracket a measured idle-state exit-latency threshold. Timerlat splits latency along its instrumented path; it is not a clock-rate or independent elapsed-time measurement.

## Placement and workload

- ClockPressure probe: pinned to CPU 6.
- Timerlat userspace reader: pinned to CPU 7 and scheduled `SCHED_FIFO` priority 90.
- CPU-pressure workers: four bounded, lower-priority CPU workers pinned to CPUs 1–4.
- Default observation: 30 seconds at a 10 ms period; five randomized replicates per arm.
- `--intertrial-cooldown-sec` inserts an idle interval after each completed trial, reducing thermal carryover when a policy intervention changes power behavior.
- Each replicate randomizes the order of the tracer-disabled and timerlat-user arms and the baseline/pressure condition order. A recovery observation follows each pressure observation after the configured settling wait.
- The QoS design instead randomizes `timerlat_user_default` and `timerlat_user_pm_qos` arms. In the intervention arm, the runner opens one request descriptor per trial, verifies that the effective global value equals the requested target, holds it through baseline/pressure/recovery, then closes it and verifies that the prior effective value returned. It refuses to run if the current policy already meets or exceeds the requested constraint. It does not modify the tuned service or per-CPU sysfs settings.
- Timerlat uses only its userspace `timerlat_fd` activation on CPU 7, period 10 ms, and the kernel's `NO_OSNOISE_WORKLOAD` option. ClockPressure uses its normal sampler and internal PHC cross-stamp when the device is available.
- The trace buffer is enlarged for retained events. Each trial stores the trace, parser output, trace-buffer statistics, user-reader summary, full tracefs before/after settings and checksums.

The timerlat interface requires an active tracer, the workload option disabled, a thread pinned to one CPU, and exclusive use of that CPU's file descriptor. A read arms the next interval; the IRQ, thread, and following user-return events are written to tracefs ([Linux 6.17 timerlat documentation](https://docs.kernel.org/6.17/trace/timerlat-tracer.html#user-space-interface)). The reader is a deliberate observer workload. Its scheduling policy and placement are fixed and recorded so its effect can be compared with the tracer-disabled arm.

## Tracefs state protection

The runner requires root to configure tracefs. It refuses to start if another tracer is active, if trace events are enabled, if the trace buffer contains retained events, or if timerlat is unavailable. It records the original tracer, tracing state, buffer size, timerlat period, CPU selection and `OSNOISE_WORKLOAD` state. It restores those settings after every enabled trial, verifies the result and fails the campaign if restoration is incomplete. The worker's initial global trace buffer was empty with `current_tracer=nop`; the diagnostic smoke also confirmed the configured tracer/options are restored.

An interrupted run still attempts tracefs restoration and leaves its raw, checksummed partial trial directory. A crash or power loss remains outside the process-level cleanup guarantee; the machine's recovery state must be inspected before reusing tracefs. The QoS request is tied to its file descriptor and is removed when normal cleanup closes that descriptor; after a host crash, verify the current effective QoS value before reuse.

On worker-03, the measured C10 exit latency is 890 µs. An 800 µs request is intended to exclude states with longer exit latency while allowing shallower states. This is an intervention on idle policy; it does not establish that C10 alone causes the timer response.

## Run and analyze

From the recorded repository revision on worker-03:

```sh
make
sudo -n python3 -m experiments.run_timerlat_campaign \
  --design observer \
  --duration-sec 30 --period-us 10000 --repeats 5 --seed 20261031 \
  --probe-cpu 6 --timerlat-cpu 7 --load-cpus 1,2,3,4 \
  --data-dir /home/worker-03/clockpressure-data/timerlat-controlled-20261031
sudo -n python3 -m analysis.analyze_timerlat_campaign \
  /home/worker-03/clockpressure-data/timerlat-controlled-20261031/campaign.json
sudo -n chown -R worker-03:worker-03 \
  /home/worker-03/clockpressure-data/timerlat-controlled-20261031
```

The analyzer reports per-trial P99 outcomes, paired pressure/recovery contrasts, and the paired ClockPressure-probe difference between timerlat enabled and disabled. Its bootstrap intervals resample run-level paired summaries. They are descriptive, not a calibration uncertainty budget. Verify every per-run checksum and timerlat activation count before interpreting effects.

Run the idle-latency intervention with the same runner and analyzer using a distinct data directory:

```sh
sudo -n python3 -m experiments.run_timerlat_campaign \
  --design cpu_latency_qos --dma-latency-us 800 \
  --duration-sec 30 --period-us 10000 --repeats 5 --seed 20261037 \
  --recovery-seconds 30 --intertrial-cooldown-sec 30 \
  --probe-cpu 6 --timerlat-cpu 7 --load-cpus 1,2,3,4 \
  --data-dir /home/worker-03/clockpressure-data/timerlat-cpu-latency-qos
sudo -n python3 -m analysis.analyze_timerlat_campaign \
  /home/worker-03/clockpressure-data/timerlat-cpu-latency-qos/campaign.json
```

The campaign analyzer verifies each trace checksum, reparses activation pairs, and reports trace-buffer overrun/drop totals. Confirm the per-trial QoS `effective_before_us`, `effective_during_us`, `effective_after_us`, and `restored` fields before interpreting the intervention.

For experiments that need idle-state and package telemetry alongside timerlat, add `--capture-cpu-idle --capture-turbostat --turbostat-interval-sec 1`. The idle trace is restricted to the selected timerlat CPU. Turbostat runs as a separate sampler for the campaign and records timestamped rows for the selected CPU. On worker-03, `--cpu 7` also leaves the turbostat process affined to CPU 7 by default, which makes it an active observer on the timerlat CPU. The option restricts displayed CPU rows; upstream turbostat still collects counters across CPUs ([turbostat manual](https://github.com/torvalds/linux/blob/v6.17/tools/power/x86/turbostat/turbostat.8)). To move the sampler after its startup sample, specify an otherwise unused CPU, for example `--turbostat-observer-cpu 0`; the campaign records affinity before and after placement and at shutdown, plus nice value and scheduler policy. Select an observer CPU outside the probe, timerlat and pressure CPUs when possible. This reduces direct same-CPU contention, though the sampler remains a system-wide observer.

The analyzer matches rows to each run's start/end `CLOCK_REALTIME` markers, then reports per-trial medians and sample counts for `Busy%`, `Bzy_MHz`, `C10%`, `PkgWatt`, and `PkgTmp`; other selected fields remain in the JSON metrics. It also calculates paired pressure-minus-baseline and recovery-minus-baseline telemetry contrasts. `Time_Of_Day_Seconds` and the probe's wall-clock markers share the host's realtime domain, so this is a coarse same-host alignment that can be affected by clock adjustments. It supplies no independent elapsed-time evidence, and interval samples near a condition boundary can straddle it. Preserve the raw `turbostat.tsv`, inspect the per-trial sample count and status, and interpret package power, temperature, and frequency as context rather than proof of a timing mechanism. `Pkg%pc6`/`Pk%pc10` values of zero are reported as observed and are not taken to prove entry or non-entry into those states.

To compare active requests immediately above and below worker-03's 890 µs C10 exit latency, run 1,000 µs as the control and 800 µs as the intervention:

```sh
sudo -n python3 -m experiments.run_timerlat_campaign \
  --design cpu_latency_qos --control-dma-latency-us 1000 --dma-latency-us 800 \
  --duration-sec 30 --period-us 10000 --repeats 5 --seed 20261038 \
  --recovery-seconds 30 --intertrial-cooldown-sec 30 \
  --probe-cpu 6 --timerlat-cpu 7 --load-cpus 1,2,3,4 \
  --data-dir /home/worker-03/clockpressure-data/timerlat-c10-threshold-20261028
sudo -n python3 -m analysis.analyze_timerlat_campaign \
  /home/worker-03/clockpressure-data/timerlat-c10-threshold-20261028/campaign.json
```

The dataset remains local to the experimental worker and the designated hidden research-data archive; raw traces and timing samples do not belong in git. Report timerlat IRQ/thread/user-return changes separately from ClockPressure end-to-end wake lateness. Do not infer clock-rate error or contract failure from either latency measure. No calibrated external elapsed-time reference is collected by this design.

## Status

Both the `observer` design and the default-versus-800 µs `cpu_latency_qos` design have completed on worker-03; see the [timerlat findings](TIMERLAT_CONTROLLED_FINDINGS.md) and [QoS findings](CPU_LATENCY_QOS_FINDINGS.md). A first 0 µs attempt stopped at the existing 85°C thermal guard; the subsequent 800 µs campaign completed all 30 trials with a maximum package temperature of 77°C. The next experiment compares active 1,000 and 800 µs requests around the measured C10 latency. QoS request lifecycle, analysis and failure-status handling are unit-tested. The default `observer` mode remains available.
