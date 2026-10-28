# TSC and ACPI PM clocksource pilot findings

## Run and provenance

- Worker: `worker-03`, Fedora Linux 43, kernel `6.17.1-300.fc43.x86_64`, bare-metal Intel Core i7-9700; e1000e PHC `/dev/ptp0` (PCI ID `0x15bb`).
- ClockPressure revision: `9fe9e94ec1e0b4219bd8b62b6323657d6176b2b0`.
- Comparison: `20261028T081208Z-clocksource-df8833f7`, three paired blocks. Each source subcampaign had timerlat-disabled and timerlat-userspace arms and baseline, four-core pressure, and recovery conditions; observations were 10 seconds at 100 Hz. The probe ran on CPU 6, timerlat on CPU 7, and pressure workers on CPUs 1–4.
- Source order was ACPI PM then TSC in pair 1 and TSC then ACPI PM in pairs 2 and 3. The source return value was checked after every subcampaign and the original TSC source was restored at completion.
- The local raw archive is [`clocksource-tsc-acpi-pilot-20261028`](../../.clockpressure-data/worker-03/clocksource-tsc-acpi-pilot-20261028/); the worker copy is `/home/worker-03/clockpressure-data/clocksource-tsc-acpi-pilot-20261028/`. The outer `comparison.json` SHA-256 is `1af5d94343a388d96c01c431fd536f1364e9c9645ca935632540ff1174a46083`. The 42 MB archive retains all six nested manifests, probes, timerlat traces, logs and analysis. Each nested campaign was reanalyzed from the local raw copy: all 18 of 18 timerlat trace digests matched; 18,000 IRQ/thread activations matched, with zero incomplete or duplicate activations, malformed latency records, or trace-buffer overrun, commit-overrun, or dropped events.

## Timing and latency results

Four-core pressure reduced the timerlat-enabled P99 latency measures under both clocksource selections:

| Metric | TSC: median pressure minus baseline | ACPI PM: median pressure minus baseline |
| --- | ---: | ---: |
| ClockPressure wake lateness | −332.847 µs | −339.037 µs |
| timerlat IRQ latency | −323.994 µs | −301.516 µs |
| timerlat thread latency | −336.942 µs | −307.102 µs |
| timerlat userspace return latency | −374.235 µs | −391.367 µs |

These are delivery-latency outcomes; they do not estimate clock rate. The paired source effect is ACPI PM's pressure response minus TSC's response. With only three pairs, the descriptive 95% bootstrap intervals for wake lateness (−28.300 to +42.628 µs), timerlat IRQ (−6.797 to +41.271 µs), thread (−22.939 to +49.145 µs), and userspace return (−32.487 to +43.648 µs) include zero. The source contrast is therefore unresolved. These intervals are not a calibration uncertainty budget.

The paired `CLOCK_MONOTONIC`-versus-`CLOCK_MONOTONIC_RAW` pressure contrast was −0.2219 ppm at the median (descriptive interval −0.3029 to +0.0188 ppm), which includes zero. It is an internal same-host comparison. A PHC precise-crossstamp fit could not be formed for ACPI PM, so no paired result exists for that metric.

## Clocksource-dependent measurement capability

The native probe opened `/dev/ptp0` in all 36 trial metadata records. The precise ioctl result was completely separated by selected Linux clocksource:

| Selected source | PTP opened | `PTP_SYS_OFFSET_PRECISE` success | Failure | Error |
| --- | ---: | ---: | ---: | --- |
| `tsc` | 18/18 | 18/18 | 0/18 | — |
| `acpi_pm` | 18/18 | 0/18 | 18/18 | `ENODEV` (19) |

This is a verified source-dependent change in whether the kernel can provide this particular hardware-assisted cross-timestamp. It does not mean the PHC stopped, that `acpi_pm` reported time incorrectly, or that elapsed time diverged. The device clock remained openable under both sources; the failed operation is the precise pairing with the selected system timekeeper.

## Mechanism supported by source inspection

The observed error is consistent with a concrete upstream Linux v6.17 path:

1. The e1000e precise-crosstimestamp callback reads the NIC PHC together with an Intel ART counter and labels that system counter `CSID_X86_ART` ([e1000e PTP callback](https://github.com/torvalds/linux/blob/v6.17/drivers/net/ethernet/intel/e1000e/ptp.c#L1024-L1136)).
2. Linux timekeeping accepts a device-provided ART value when it is already the selected clocksource, or when the selected clocksource declares a convertible base. If conversion fails, `get_device_system_crosststamp()` returns `-ENODEV` ([timekeeping conversion](https://github.com/torvalds/linux/blob/v6.17/kernel/time/timekeeping.c#L1203-L1341)). The TSC clocksource registers ART as its base when ART support is available ([TSC base setup](https://github.com/torvalds/linux/blob/v6.17/arch/x86/kernel/tsc.c#L1395-L1405)); the ACPI PM clocksource is a separate PM-timer reader and does not declare that base ([ACPI PM source](https://github.com/torvalds/linux/blob/v6.17/drivers/clocksource/acpi_pm.c#L91-L104)). The PTP ioctl propagates the driver's cross-timestamp error ([PTP ioctl path](https://github.com/torvalds/linux/blob/v6.17/drivers/ptp/ptp_chardev.c#L288-L300)).

The worker runs Fedora's `6.17.1-300.fc43` kernel. This source inspection is against upstream v6.17, not the Fedora source package or binary. The 18/18 versus 0/18 observations and `ENODEV` result are direct measurements; attribution to this exact code path is a strong, testable explanation rather than a binary-level verification.

## Interpretation and follow-up

- **Supports:** the selected Linux clocksource can change the availability of an ostensibly hardware-assisted measurement witness. The availability must be recorded with every measurement; missing cross-stamps under ACPI PM cannot be treated as random missing data.
- **Does not support:** physical clock drift, a timing-contract false pass, intentional evaluation manipulation, or a workload-induced effect on the measurement authority. The source was an explicit experimental configuration change.
- **Unresolved:** whether the source-specific pressure-latency contrasts are nonzero; whether this finding extends beyond worker-03's e1000e/ART combination; and the calibration and independence of the PHC itself.
- **Next:** inspect the Fedora kernel source package for the exact running build; characterize alternate PTP ioctl capture modes under both sources; and pursue an external reference such as calibrated PPS or a separately characterized timing host. Keep clocksource changes and workload pressure as distinct interventions.

Generated pair and source summaries are in [`clocksource-comparison-analysis.md`](../../.clockpressure-data/worker-03/clocksource-tsc-acpi-pilot-20261028/clocksource-comparison-analysis.md) and the machine-readable JSON beside it.
