# TSC and ACPI PM clocksource comparison

## Purpose

Worker-03 reports `tsc` as its current Linux clocksource and `acpi_pm` as another available source. This pilot asks whether the timerlat and ClockPressure pressure contrasts change when Linux uses the ACPI PM timer as its system timekeeping source. It investigates source-dependent software behavior; it does not measure elapsed time independently.

## Runner and protocol

`experiments.run_clocksource_comparison` runs randomized TSC/ACPI PM source order in paired blocks. Within each source setting it launches the existing controlled timerlat experiment with timerlat disabled and enabled arms, and baseline, CPU-pressure, and recovery conditions. Each subcampaign records its selected source in the read-only environment snapshot; the outer manifest records the requested source, observed selection, prior source, restoration result, commands, status, and file digests. The runner restores the source after each subcampaign, even when the child process fails, and verifies the original source again at exit.

The analyzer compares each subcampaign's timerlat-enabled pressure-minus-baseline change, then compares those changes within randomized source pairs. Bootstrap intervals are descriptive across pair summaries. With the default three pairs, the pilot can identify a large source dependence but is not a high-precision calibration study.

On worker-03, launch it from the checked-out ClockPressure revision:

```sh
sudo -n python3 -m experiments.run_clocksource_comparison \
  --sources tsc,acpi_pm --pairs 3 --duration-sec 10 --period-us 10000 \
  --seed 20261039 --source-settle-sec 10 --cooldown-sec 15 \
  --warmup-sec 5 --recovery-seconds 5 \
  --probe-cpu 6 --timerlat-cpu 7 --load-cpus 1,2,3,4 \
  --data-dir /home/worker-03/clockpressure-data/clocksource-tsc-acpi-pilot-20261028
```

The wrapper creates one campaign per clocksource per pair under the selected data directory, runs the ordinary campaign analyzer for each, and writes `clocksource-comparison-analysis.json` and `.md` when all subcampaigns complete. It captures CPU idle transitions but does not start turbostat, whose collector returns to the CPU it samples and would add a known observer condition.

## Executed pilot

The three-pair exploratory pilot completed on 2026-10-28. Six of six subcampaigns completed; each run recorded its active source, restored the prior TSC source, and the wrapper verified TSC at exit. The raw results and generated analysis are in the [findings report](ACPI_PM_CLOCKSOURCE_FINDINGS.md). That report records the source-specific PTP precise-crossstamp result and the unresolved timerlat source contrast.

## Measurement limits

- Switching the Linux clocksource changes the input used by kernel timekeeping. `CLOCK_MONOTONIC`, `CLOCK_MONOTONIC_RAW`, timerlat trace timestamps, and other system interfaces are related to that source; agreement among them is not independent validation.
- The PHC cross-stamp is a same-host comparison. Its calibration and capture uncertainty have not been established, so it cannot serve as a calibrated external elapsed-time reference here.
- A timerlat latency change is a delivery or scheduling outcome, not clock-rate error. A source-specific PHC/MONORAW fit change is still an internal comparison and does not establish physical oscillator drift.
- Process-level cleanup records and attempts to restore the original clocksource after errors and interrupts. A power loss or kernel crash can bypass that cleanup; inspect `current_clocksource` before restarting a partial experiment.
- The pilot established that the e1000e `PTP_SYS_OFFSET_PRECISE` interface was available under TSC and returned `ENODEV` under ACPI PM. This changes measurement capability; do not describe it as a clock-rate error or a fault in ACPI PM. The source-level explanation and measured counts are in the [findings report](ACPI_PM_CLOCKSOURCE_FINDINGS.md).

The pilot should be treated as exploratory evidence. Preserve the outer manifest, each nested campaign, all traces, and generated reports together. Do not state a physical elapsed-time or timing-contract discrepancy without an independently calibrated reference.
