# Controlled timerlat observer campaign

## Research question

The earlier worker-03 campaigns found a pressure-associated change in end-to-end timer wake lateness, while same-host PHC/MONORAW comparisons resolved no pressure-related rate change. The existing `timerlat_fd` smoke established that Linux can report IRQ-context, timerlat-thread, and return-to-userspace latency, but the smoke was not a controlled workload comparison.

This campaign compares randomized baseline, CPU-pressure, and recovery observations with the pinned userspace timerlat reader disabled and enabled. ClockPressure continues to collect its end-to-end absolute-sleep outcome in both arms. The timerlat trace splits latency along its instrumented path; it is not a clock-rate or independent elapsed-time measurement.

## Placement and workload

- ClockPressure probe: pinned to CPU 6.
- Timerlat userspace reader: pinned to CPU 7 and scheduled `SCHED_FIFO` priority 90.
- CPU-pressure workers: four bounded, lower-priority CPU workers pinned to CPUs 1–4.
- Default observation: 30 seconds at a 10 ms period; five randomized replicates per arm.
- Each replicate randomizes the order of the tracer-disabled and timerlat-user arms and the baseline/pressure condition order. A recovery observation follows each pressure observation after the configured settling wait.
- Timerlat uses only its userspace `timerlat_fd` activation on CPU 7, period 10 ms, and the kernel's `NO_OSNOISE_WORKLOAD` option. ClockPressure uses its normal sampler and internal PHC cross-stamp when the device is available.
- The trace buffer is enlarged for retained events. Each trial stores the trace, parser output, trace-buffer statistics, user-reader summary, full tracefs before/after settings and checksums.

The timerlat interface requires an active tracer, the workload option disabled, a thread pinned to one CPU, and exclusive use of that CPU's file descriptor. A read arms the next interval; the IRQ, thread, and following user-return events are written to tracefs ([Linux 6.17 timerlat documentation](https://docs.kernel.org/6.17/trace/timerlat-tracer.html#user-space-interface)). The reader is a deliberate observer workload. Its scheduling policy and placement are fixed and recorded so its effect can be compared with the tracer-disabled arm.

## Tracefs state protection

The runner requires root to configure tracefs. It refuses to start if another tracer is active, if trace events are enabled, if the trace buffer contains retained events, or if timerlat is unavailable. It records the original tracer, tracing state, buffer size, timerlat period, CPU selection and `OSNOISE_WORKLOAD` state. It restores those settings after every enabled trial, verifies the result and fails the campaign if restoration is incomplete. The worker's initial global trace buffer was empty with `current_tracer=nop`; the diagnostic smoke also confirmed the configured tracer/options are restored.

An interrupted run still attempts tracefs restoration and leaves its raw, checksummed partial trial directory. A crash or power loss remains outside the process-level cleanup guarantee; the machine's recovery state must be inspected before reusing tracefs.

## Run and analyze

From the recorded repository revision on worker-03:

```sh
make
sudo -n python3 -m experiments.run_timerlat_campaign \
  --duration-sec 30 --period-us 10000 --repeats 5 --seed 20261031 \
  --probe-cpu 6 --timerlat-cpu 7 --load-cpus 1,2,3,4 \
  --data-dir /home/worker-03/clockpressure-data/timerlat-controlled-20261031
sudo -n python3 -m analysis.analyze_timerlat_campaign \
  /home/worker-03/clockpressure-data/timerlat-controlled-20261031/campaign.json
sudo -n chown -R worker-03:worker-03 \
  /home/worker-03/clockpressure-data/timerlat-controlled-20261031
```

The analyzer reports per-trial P99 outcomes, paired pressure/recovery contrasts, and the paired ClockPressure-probe difference between timerlat enabled and disabled. Its bootstrap intervals resample run-level paired summaries. They are descriptive, not a calibration uncertainty budget. Verify every per-run checksum and timerlat activation count before interpreting effects.

The dataset remains local to the experimental worker and the designated hidden research-data archive; raw traces and timing samples do not belong in git. Report timerlat IRQ/thread/user-return changes separately from ClockPressure end-to-end wake lateness. Do not infer clock-rate error or contract failure from either latency measure. No calibrated external elapsed-time reference is collected by this design.

## Status

Implementation and worker smoke validation are pending. This document describes the specified comparison before campaign data collection, not an observed result.
