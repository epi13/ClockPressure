# worker-03 preparation and boundary

worker-03 is the **intended** Linux experiment host and was used previously for SenseTrace. This document is a preparation checklist, **not a verified host inventory**. No connection, kernel version, CPU model, hardware clocks, or available eBPF features are assumed here.

## Prerequisites

- Authorized access to worker-03 and explicit permission for CPU / memory / I/O pressure tests.
- Confirmation that concurrent SenseTrace or other agents and jobs will not be disrupted.
- Agreed resource ceiling, observation window, and abort / recovery owner.
- A copy of the node baseline and configuration provenance with no sensitive credentials.

## Read-only inspection checklist

Record each item in the run manifest:

| Category | Suggested read-only source | Why |
| --- | --- | --- |
| OS / kernel / architecture | `uname -a`, `cat /etc/os-release` | Hook and clock API support |
| CPU / topology | `lscpu` | TSC / affinity / virtualization clues |
| Selected / available clocksource | `cat /sys/devices/system/clocksource/clocksource0/current_clocksource` and `available_clocksource` if present | Identify kernel time base |
| CPU clocks / governor | `/sys/devices/system/cpu/` read-only files where available | Frequency and power-mode context |
| Time discipline | `timedatectl status`, `adjtimex --print` if available | NTP / slew confounder |
| eBPF support | `bpftool feature probe` when permitted; enumerate tracepoints read-only | Check probe feasibility |
| Tracing mount / kernel facilities | `/sys/kernel/tracing/available_events` if accessible | Identify probes without assuming names |
| Kernel state / thermal | Read-only `/sys/class/thermal/`, kernel logs when permitted | Baseline and stop conditions |
| Time / reference hardware | Vendor data sheets, oscillator paths, PTP devices, external instrument metadata | Independence assessment |
| Virtualization | `systemd-detect-virt`, platform inventory | Host / guest semantics |

These commands are **examples**, not requirements to install utilities or elevate privileges. Some features or paths may be absent.

## Operational guardrails

- Start with read-only probes and minimal sampling, not global kernel tracing at full rate.
- Prefer per-process workloads and bounded stressors. Do not modify the system clock, select another clocksource, set kernel flags, reload firmware, change BIOS settings, or overclock without a separately reviewed plan.
- Keep process priority normal unless there is an explicit reason and approval.
- Do not use unbounded resource consumers or write-heavy storage tests.
- Avoid publicizing host identifiers, exact addresses, credentials, other project workloads, or unrelated process traces.
- Preserve a pre-run system snapshot and post-run confirmation of recovery.

## Readiness decision

A measurement run is eligible only when all of the following are recorded: device clock and timing semantics, measurement boundaries, workload / limits, eBPF permissions / overhead budget, reference plan, ambient jobs, provenance, and a recovery path.

A run without an external reference may still establish *scheduler jitter* or *internal clock disagreement*, but cannot by itself establish true elapsed-time drift.
