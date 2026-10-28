# worker-03 preparation and boundary

# worker-03: observed environment and operational boundary

**Inventory date:** 2026-10-28 UTC. Access was verified over passwordless SSH. This is an observed snapshot, not a claim that every device or setting is stable across boots. The inventory omits hardware serials, UUIDs and network addresses.

## Observed software and hardware

| Area | Observed state |
| --- | --- |
| OS / kernel | Fedora Linux 43, x86-64, kernel `6.17.1-300.fc43.x86_64`; `PREEMPT_DYNAMIC` |
| Platform | Dell Precision Tower 3431, BIOS `1.24.0` (2023-12-13), bare metal (`systemd-detect-virt` reports `none`) |
| CPU | Intel Core i7-9700, family 6/model 158/stepping 13, 8 cores/8 online CPUs, no SMT; microcode `0x104` |
| TSC | CPU advertises `constant_tsc`, `nonstop_tsc`, `rdtscp`, `tsc_deadline_timer` and `art`; boot log refines the TSC to 2,999.999 MHz. The Linux-selected TSC source remains an internal host reference. |
| Kernel clocksource | Current `tsc`; available list `tsc acpi_pm`. `CLOCK_MONOTONIC`, `CLOCK_MONOTONIC_RAW`, `CLOCK_BOOTTIME`, `CLOCK_REALTIME`, TAI and BPF time remain within Linux's timekeeping dependency graph. |
| Clock-event devices | The eight online CPUs report `lapic-deadline`; local APIC timer interrupt counters are present. TSC-deadline support is advertised. |
| ACPI PM timer | Registered by the kernel as a secondary 24-bit source. Its different hardware counter path has not been calibrated against an external reference. |
| HPET | ACPI reports HPET at `0xfed00000`, and `/dev/hpet` exists. Boot logs say it is dysfunctional in PC10 and then report no address/interrupt resources in `_CRS`; it is not in the available clocksource list. Do not infer that the device node is a usable reference. |
| RTC | `/dev/rtc0`, driver/name `rtc_cmos`; calendar-clock resolution is unsuitable for small drift measurements. |
| NIC PHC | Intel I219-LM, driver `e1000e`, exposes `/dev/ptp0`. `ethtool -T eno1` reports hardware raw clock, RX/TX timestamp modes and IEEE-1588 “Precise” provider quality. No `ptp4l` or `phc2sys` process was observed. This is a **candidate** distinct hardware clock, not yet a calibrated independent reference. |
| CPU power | `intel_pstate` active with `powersave` governor; observed policy limits 800–4,700 MHz, base 3,000 MHz. HWP is advertised. `intel_idle`/`menu` exposes enabled POLL through C10 states. No system-wide power policy was changed for the inventory. |
| Temperature / voltage | ACPI, PCH, Dell SMM, NVIDIA GPU and CPU package/core temperature telemetry are visible. The initial snapshot was about 27–46°C depending on sensor. No voltage telemetry or powercap/RAPL file was found in the inspected sysfs paths. The pilot stops if CPU package temperature reaches 85°C. |
| Interrupts / scheduling | Eight CPUs, IO-APIC and MSI/MSI-X sources; APIC local timer and reschedule counts are visible in `/proc/interrupts`. Scheduler, migration, IRQ, softirq, hrtimer, timer and CPU idle/frequency tracepoints exist. |
| Network time | `chronyd` reports synchronized system time from network NTP, with roughly 11 ms reported root dispersion at inventory time. This disciplines host time and shares the host readout path; it is contextual telemetry, not the experiment's independent timer. |
| eBPF / tracing | `/sys/kernel/btf/vmlinux` is present (about 6.7 MB); tracefs and debugfs are mounted; `bpftool 7.6.0`, `bpftrace 0.24.2`, clang 21.1.8 and GCC 15.3.1 are available. `bpftool feature probe` succeeded as root. `clang -target bpf` compiles a smoke object. `perf` and `pahole` are not installed; libbpf headers/libraries were not found in standard include/library paths. |
| Permissions | `worker-03` is an unprivileged account with passwordless sudo. `perf_event_paranoid=2`; the PHC and RTC are owned by `root:clock` and require elevated access for this account. No sysctl/clocksource setting was changed. |
| Data storage | `/home` is a persistent Btrfs subvolume on `/dev/sda3`, mounted read/write with compression. The intended external result directory under the worker account's home survives a normal reboot. |

`/proc/timer_list` exists but returns an empty read in this kernel configuration. An `adjtimex` command is not installed. `timedatectl` and `chronyc tracking` supplied time-discipline state. Exact NTP server addresses, hardware serials and machine UUIDs are intentionally excluded from experiment manifests.

## Relationship and independence assessment

1. The kernel selects invariant/nonstop TSC as its active clocksource. Ordinary monotonic clock APIs and `bpf_ktime_get_ns()` therefore do not provide an independent witness merely because they have different names or run in different contexts.
2. `CLOCK_MONOTONIC` may receive frequency discipline; `CLOCK_MONOTONIC_RAW` avoids that discipline but still follows the host clocksource. Comparing them is an internal diagnostic.
3. ACPI PM and the NIC PHC are separate counter/readout candidates. The PM timer's performance and dependency path are uncharacterized. The NIC PHC may use its own hardware clock, but no calibration, independent endpoint latching or oscillator/environment analysis exists yet.
4. NTP is an external network source with millisecond-scale dispersion in the observed chrony report; timestamp boundaries still pass through the host. The RTC is low resolution. Neither currently qualifies as a trustworthy high-resolution elapsed-time reference.
5. The pilot can therefore establish timer delivery/scheduler behavior and internal clock agreement only. It cannot presently establish absolute elapsed-time error.

## Existing SenseTrace activity and reusable work

SenseTrace is separate prior research, not ClockPressure evidence. A read-only inspection found an unattended `sensetrace.service` running with 15 threads, no child process, about 79 seconds of lifetime CPU time and 318 MB memory after roughly 31 days. Its CPU usage and cgroup CPU counters did not increase over a five-second observation window. The service was not stopped, reconfigured or otherwise altered. The ClockPressure run records its cgroup CPU/memory counters and system CPU PSI as ambient context; CPU workers run at nice `+10` and are pinned to CPUs `1–4` to reduce interference with other services.

SenseTrace has a mature native C timing path and a temporary bpftrace witness backend. Its September 2026 worker-03 eBPF pilot verified scheduler, page-fault, allocation and memory-management tracepoint attachment on this kernel. That evidence supports host capability and provides a prior on tracepoint operation, but the SenseTrace probes target memory-measurement context, use separate event schemas and do not measure elapsed-time accuracy. ClockPressure keeps its own single-purpose timestamp, timer-lateness and scheduler-latency stream. The shared design lesson is to retain raw events, target PID/TID, clock-domain identity and observer-overhead controls rather than treating eBPF as a reference clock.

## Readiness and limits

- SSH is working and can recover the headless machine. Passwordless sudo is verified.
- The first pilot changes no clocksource, system clock, CPU frequency limits, firmware or boot parameters. CPU pressure is bounded by four pinned lower-priority workers, a per-run duration, temperature monitoring and a recovery observation.
- The SenseTrace service remains untouched. A measured “baseline” means **no ClockPressure-generated load**; it does not claim that all host services are physically idle.
- Experiment data is written under the worker account's home directory, outside the Git checkout, on the observed persistent Btrfs `/home` subvolume. Checksum and local-copy policy are described in [data and reproducibility](DATA_AND_REPRODUCIBILITY.md).
- Tracepoint program attachment must be exercised by ClockPressure itself. The prior SenseTrace pilot is not substituted for this new probe's own load/loss checks.

A run without an external reference may still establish *scheduler jitter* or *internal clock disagreement*, but cannot by itself establish true elapsed-time drift.
