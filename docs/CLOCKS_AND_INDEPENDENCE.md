# Clocks, timers and independence

## Separate time from delivery

A **clocksource** is the time base from which elapsed time is determined. A **clock-event device** schedules an interrupt at a desired point. Scheduler and user-space event delivery may be late even if the clocksource advanced accurately. Linux distinguishes these abstractions explicitly: [kernel timekeeping documentation](https://docs.kernel.org/timers/timekeeping.html).

A loop that increments `ticks += 1` after each delayed sleep is **not** an accurate elapsed-time reference. Conversely, reading a modern monotonic counter before and after a delay normally includes that delay.

## Linux interfaces

| Interface | What it represents | Caveat |
| --- | --- | --- |
| `CLOCK_MONOTONIC` | Monotonic elapsed time, excludes suspend | Can be gradually frequency-disciplined; no abrupt wall-clock steps |
| `CLOCK_MONOTONIC_RAW` | Raw monotonic hardware-based time | Excludes suspend; shares hardware provenance with kernel timekeeping; not external truth |
| `CLOCK_BOOTTIME` | Monotonic elapsed time including suspend | Different suspend semantics; not a second independent oscillator |
| `CLOCK_REALTIME` | Civil / wall-clock time | Can jump due to adjustments; unsuitable alone for strict elapsed-time proofs |
| `CLOCK_PROCESS_CPUTIME_ID` | CPU execution time charged to process | Excludes periods waiting / descheduled; not wall elapsed time |
| `bpf_ktime_get_ns()` | BPF monotonic kernel timestamp | Observer shares kernel timekeeping; not independent proof |
| TSC / HPET / ACPI PM timer | Candidate hardware counter families | Availability and independence vary by platform and configuration |

Definitions: [clock_gettime(2)](https://man7.org/linux/man-pages/man2/clock_gettime.2.html), [kernel ktime accessors](https://docs.kernel.org/core-api/timekeeping.html).

## Independence is a dependency graph, not a clock-name count

Before describing two readings as independent, establish:

- **Physical source**: separate oscillators / clock domains, or a shared underlying reference?
- **Readout path**: independent hardware latching, driver, CPU, and timestamp mechanism?
- **Correction path**: shared NTP / PTP, host virtual clock, device driver or calibration?
- **Error modes**: shared temperature, power, timing skew, suspend, IRQ or process delay?
- **External traceability**: reference calibration uncertainty and source provenance?

Two clock APIs on the same host can be valuable *diagnostics* but are not automatically independent standards. A clock disciplined by network time still receives timestamps through a path that may have uncertainty and common dependencies. Network time by itself is not a sufficiently documented external validator.

A stronger external reference might use a physically separate oscillator / disciplined instrument with hardware timestamps or a captured external PPS signal. Every proposed arrangement must document the entire measurement chain, host capture latency and calibration; even a separate board can share power, temperature, or acquisition latency.

## Timing-error vocabulary

- **Offset**: the clocks disagree on epoch; unrelated to their elapsed-time rate.
- **Drift / rate discrepancy**: elapsed-time differences grow with observation duration.
- **Jitter**: short-term variation in time or in delivery / timestamp latency; identify which.
- **Lost ticks**: software misses intended timer updates; not necessarily lost hardware clock cycles.
- **Read latency**: taking a timestamp is delayed, giving a misleading event boundary.
- **Suspension semantics**: clocks may intentionally stop or continue across suspend.
- **Uncertainty**: bounds / distribution of reference and measurement-chain errors.

## Error calculation

For the same two event boundaries (not merely two unrelated reads):

```text
T_ref = ref_end - ref_start
T_dut = dut_end - dut_start
rate_error = (T_dut - T_ref) / T_ref
rate_error_ppm = 1e6 * rate_error
```

Do not infer physical clock drift from raw absolute timestamp subtraction across incompatible epochs. A 1% rate error means 10,000 ppm—far greater than normal well-behaved timing hardware should exhibit. Report resolution, calibration, event alignment, and confidence intervals before interpreting smaller effects.

## Observability caveat

eBPF can observe sched switches, wakeups, selected timer events, and kernel timestamp fields with low overhead in many environments. It **cannot** provide a separate reference merely by attaching to a different probe. Use lost-event counters and sampling budgets to assess observer effects.

## worker-03 dependency map

The current worker has a Dell/Intel platform with Linux clocksource `tsc` selected, `acpi_pm` available as a secondary clocksource, and per-CPU `lapic-deadline` clock-event devices. HPET is advertised by firmware but explicitly disabled by the kernel due to PC10 behavior and missing ACPI `_CRS` resources; `/dev/hpet` alone does not make it usable. The CPU exposes `constant_tsc`, `nonstop_tsc`, `rdtscp` and `tsc_deadline_timer` and Linux refined TSC frequency to about 3.0 GHz at boot. These facts identify the internal path; they do not certify its absolute accuracy.

For this host, monotonic APIs and `bpf_ktime_get_ns()` must be treated as a related family. `CLOCK_MONOTONIC_RAW` is not a different oscillator. The Intel I219-LM `e1000e` driver exposes an IEEE-1588 PHC with hardware RX/TX timestamps and a “Precise” provider label; ClockPressure can read it by opening `/dev/ptp0` and converting its file descriptor to a dynamic clock ID. On worker-03, `PTP_SYS_OFFSET_PRECISE` also succeeds. This ioctl returns a PHC timestamp paired by the driver with system `CLOCK_MONOTONIC_RAW` and realtime timestamps. The upstream PTP UAPI defines those fields, and the e1000e PCH driver implements its cross-timestamp through the NIC clock and Intel ART system counter ([PTP UAPI](https://github.com/torvalds/linux/blob/v6.17/include/uapi/linux/ptp_clock.h), [e1000e PTP driver](https://github.com/torvalds/linux/blob/v6.17/drivers/net/ethernet/intel/e1000e/ptp.c)).

The paired ioctl reduces userspace read-order ambiguity compared with separate `clock_gettime` calls. It does **not** establish oscillator independence, absolute calibration, external traceability or a complete capture-uncertainty budget. The system side of this cross-timestamp is another representation of the host timekeeping domain; ART/TSC and the NIC PHC may share hardware or environmental dependencies. A standalone worker-03 smoke test completed 10,000 precise cross-timestamp reads: the outer RAW-clock bracket had a 24.9 µs median and 50.7 µs p99, while the observed PHC-minus-paired-MONORAW offset spanned 161 ns. This rapid-read offset range is an exploratory consistency observation, not a calibration or drift bound; the raw pairs should be collected in a formal trial before it is treated as a finding.

Chrony/NTP state can explain host frequency discipline but the sampled host clocks still use the kernel timekeeping path. The one-second RTC and currently unusable HPET are not substitutes for an independent high-resolution reference.

The hardware details are an observed snapshot; see [worker-03 inventory](WORKER_03.md). Every run manifest stores only a pseudonymized host name and omits machine serials, UUIDs and network addresses.

## Further reading

- [Linux clocksource / clockevents](https://docs.kernel.org/timers/timekeeping.html)
- [Linux high-resolution timer design](https://docs.kernel.org/timers/highres.html)
- [Linux timekeeping in virtualization](https://docs.kernel.org/virt/kvm/x86/timekeeping.html)
- [clock_gettime](https://man7.org/linux/man-pages/man2/clock_gettime.2.html)
