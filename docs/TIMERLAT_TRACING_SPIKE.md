# worker-03 timerlat tracer smoke

**Observation date:** 2026-10-28 UTC
**Trace:** `20261028T042630Z-timerlat-smoke`
**Kernel:** Fedora 43, Linux `6.17.1-300.fc43.x86_64`

## Purpose

The three ClockPressure campaigns consistently changed end-to-end userspace timer wake lateness, but the current probe cannot separate hardware timer/interrupt delay from post-interrupt scheduling. worker-03 exposes Linux's built-in `timerlat` tracer. The kernel documentation describes it as a per-CPU real-time thread that records one timer latency at hard-IRQ context and another when the thread runs; the activation IDs pair those records ([Linux 6.17 timerlat documentation](https://docs.kernel.org/6.17/trace/timerlat-tracer.html)). This is a possible diagnostic for the next controlled experiment, not an external clock.

## Smoke procedure and integrity

With no active trace events, `current_tracer=nop`, and an empty trace buffer, the smoke enabled `timerlat` for two seconds on CPUs 0–7 at a 10 ms period. The per-CPU trace buffer was temporarily increased from 7 KB to 256 KB. The original tracer, period, buffer size and tracing state were restored in a `finally` path; before and after values match. No trace events were enabled before or after, and the trace buffer was returned to its initially empty state. `rtla` was not installed; tracefs exposed the built-in tracer directly.

The run retained 1,600 paired activations: 200 IRQ and 200 thread records per CPU, with no malformed, incomplete or duplicate activations. The raw trace, JSON settings manifest and generated analysis are retained under:

- Worker: `/home/worker-03/clockpressure-data/diagnostics-v2/timerlat/`
- Local copy: `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/diagnostics-v2/timerlat/`

Regenerate the per-CPU summary with:

```sh
python3 -m analysis.analyze_timerlat /path/to/20261028T042630Z-timerlat-smoke.trace
```

## Observations

| Timerlat outcome | Samples | Median | P95 | P99 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| IRQ-context timer latency | 1,600 | 63.890 µs | 344.217 µs | 353.970 µs | 396.884 µs |
| Timerlat-thread latency | 1,600 | 83.334 µs | 373.563 µs | 380.495 µs | 442.696 µs |

Per-CPU median IRQ/thread latencies were:

| CPU | IRQ median | Thread median |
| ---: | ---: | ---: |
| 0 | 341.895 µs | 371.062 µs |
| 1 | 331.786 µs | 361.407 µs |
| 2 | 232.173 µs | 261.836 µs |
| 3 | 156.113 µs | 185.610 µs |
| 4 | 91.003 µs | 120.702 µs |
| 5 | 42.818 µs | 65.035 µs |
| 6 | 45.890 µs | 68.705 µs |
| 7 | 43.389 µs | 65.312 µs |

The large CPU-to-CPU differences are the main reason to follow up. They could reflect interrupt, housekeeping, idle-state or other per-CPU conditions; this two-second trace cannot distinguish those explanations. The tracer also runs high-priority kernel threads on every selected CPU, so these values are not a passive or workload-free baseline. They were not acquired alongside a ClockPressure timer probe or under randomized pressure conditions.

## Pinned userspace timerlat interface

The documented per-CPU `timerlat_fd` interface was also exercised on CPU 7. With the timerlat tracer active and `OSNOISE_WORKLOAD` temporarily disabled, a CPU-7-pinned process performed 51 reads at a 10 ms period. Each read returned zero bytes; the kernel wrote the latency records to tracefs. The run retained 51 IRQ and 51 thread events plus 50 `user-ret` events. The first activation has no preceding userspace return to record, which explains the one fewer `user-ret` event. All 51 IRQ/thread activation pairs matched; there were no malformed or duplicate events.

| Pinned userspace timerlat outcome | Samples | Median | P95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| IRQ-context timer latency | 51 | 315.628 µs | 360.840 µs | 363.754 µs |
| Timerlat-thread latency | 51 | 356.198 µs | 375.774 µs | 378.851 µs |
| Return-to-userspace latency | 50 | 418.117 µs | 426.463 µs | 437.095 µs |

The pinned userspace smoke and the all-CPU kernel-thread smoke are not a controlled comparison: they activate different workloads and run at different times. On CPU 7, the all-CPU kernel-thread smoke had 43.389 µs median IRQ latency and 65.312 µs median thread latency, while the userspace interface produced 315.628 µs and 356.198 µs. This difference is a lead for controlled work, not a demonstrated power-state or scheduling effect.

The user-interface run temporarily changed the timerlat period, trace buffer, tracer and `OSNOISE_WORKLOAD` option. It restored each original setting; before and after settings match, and no trace events remained enabled. Its raw trace, settings manifest and parser output are retained under:

- Worker: `/home/worker-03/clockpressure-data/diagnostics-v2/timerlat-user/`
- Local copy: `/home/epi13/Documents/Projects/.clockpressure-data/worker-03/diagnostics-v2/timerlat-user/`

`analysis/analyze_timerlat.py` parses IRQ, thread and `user-ret` records and checks IRQ/thread activation pairing. The kernel documentation explains that the next read records return-to-userspace latency from the preceding activation ([timerlat user-space interface](https://docs.kernel.org/6.17/trace/timerlat-tracer.html#user-space-interface)).

## Interpretation limits and next step

Timerlat's IRQ/thread/userspace split is a useful diagnostic of the kernel's timer-latency path, but it is not a reference clock and its periodic workload perturbs the system. A follow-up should collect paired baseline, CPU-pressure and recovery runs with the same pinned-user interface and compare trace-enabled against trace-disabled controls. It should retain the ClockPressure end-to-end timer result and report IRQ, thread and userspace-return outcomes separately.

The userspace file interface requires an active timerlat tracer, `NO_OSNOISE_WORKLOAD`, a pinned task and exclusive access to that CPU's file descriptor. It returned no payload bytes on this kernel and emitted its results through tracefs. The smoke confirms that data path; its observer effect and relationship to the normal ClockPressure absolute-sleep probe still need controlled measurement.
