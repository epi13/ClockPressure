# Data and reproducibility contract

## Principle

Raw measurements are the evidence. Derived summaries, charts and agent explanations are projections that should be reproducible from recorded inputs and versioned analysis code.

## Implemented output layout

```text
~/clockpressure-data/
  campaigns/<campaign-id>.json
  runs/<run-id>/
    manifest.json             # environment, conditions, revision and hashes
    probe.jsonl                # native sample / endpoint events
    scheduler.jsonl            # optional target-TID eBPF events
    scheduler.stderr           # attach, diagnostics and loss messages
    overhead.json              # clock inter-read and PHC cross-timestamp brackets
    telemetry.jsonl            # temperature/frequency/PSI/cpuidle context, about 1 Hz
    workload.jsonl             # pressure start/stop and CPU affinity
    *.stderr                   # process diagnostics
  analysis.json
  analysis.md
```

Raw observations are generated outside the checkout under `~/clockpressure-data/`, with directory permissions restricted to the worker account. Each completed run has checksums for every raw artifact; incomplete data remains in a `.in-progress` directory. Keep worker identifiers pseudonymized. Do not commit raw worker data, exact serials, UUIDs, network addresses, credentials or unrelated application content. Synthetic demonstrations are labeled and never enter hardware run storage.

## Per-run manifest

Minimum fields:

| Group | Fields |
| --- | --- |
| Identity | `run_id`, `protocol_version`, UTC recording date, operator / agent role, code revision SHA |
| Platform | pseudonymized host ID, kernel build, arch / CPU, microcode if permissible, bare metal / guest, current clocksource |
| Conditions | stressor type, parameters / ceilings, duration, affinity, randomization order, ambient load |
| Timing | DUT clock API, reference source / chain, timestamp boundaries, resolution, calibration, uncertainty, suspend / NTP state |
| Instrumentation | eBPF program / version, hooks, sampling, dropped events, trace overhead / budget |
| Data | raw artifact path / URI, SHA-256 checksum, units / schema version |
| Outcome | completion / abort reason, exclusions, anomalies, recovery state |

The implementation records a clock snapshot/environment on both sides of the trial, the native probe's actual UID/EUID and clock resolutions, campaign ID/replicate/role, start/end intervals by available clock, artifact checksums, periodic CPU frequency/temperature/per-CPU cpuidle counters, Linux pressure-stall information, memory availability and SenseTrace service-cgroup resource counters. When a PTP driver supports `PTP_SYS_OFFSET_PRECISE`, the native probe retains matched device, MONORAW and REALTIME timestamps and records whether the ioctl was available or failed. It deliberately omits DMI serials/UUIDs, upstream NTP host/IP and process command lines.

## Sample event schema (design only)

Each measurement stream should identify its own clock domain:

```text
run_id,stream_id,event_id,seq,clock_id,timestamp_ns,
cpu_id,event_type,condition_id,value,unit,flags
```

- `timestamp_ns` is meaningful **only with its clock ID**, not as a universal epoch.
- `event_id` is used to align independently observed occurrences where physically justified.
- `flags` can document missing / deferred / inferred timestamps or errors.
- Record aggregation granularity and sample loss; absence of events is not evidence of no activity.
- Do not convert one timing source into another silently.

## Analysis output

Publish for each condition: raw count, exclusions, uncertainty, event-loss rate, baseline / pressure / recovery distributions, latency quantiles, estimated rate discrepancy (signed ppm), confidence / sensitivity analyses, and exact test version. Keep exploratory findings separate from preregistered hypotheses.

A genuine externally validated drift claim requires a description of the independent reference *and how boundaries are latched*, not just a plot of two host clocks.

The current analysis estimates monotonic/RAW and optional sequential PHC rates across the same process start/end sequence and reports the sum of their endpoint read brackets in ppm. That bracket is an acquisition-alignment bound only; it is not oscillator calibration uncertainty. It separately computes endpoint and time-series PHC rates from driver-paired `PTP_SYS_OFFSET_PRECISE` device/system timestamps when present; the paired rate and fit reduce userspace read-order ambiguity but have unquantified driver/hardware capture uncertainty and are not external validation. The time-series fit has no confidence interval because its points are serially correlated. Pairwise bootstrap intervals use replicate-level P99-lateness differences and are marked unavailable when fewer than three run pairs exist. They describe between-run variation within one campaign; they are not external-clock confidence bounds and should not be inferred from per-sample independent resampling.

## Reproduction checklist

1. Same source revision, configuration and protocol.
2. Permission to use equivalent resources and an identical timer definition.
3. Calibration and independent-reference uncertainty documented.
4. At least one negative control and one recovery measurement.
5. Raw data / checksums and analysis sufficient to regenerate figures.
6. Replication across independent runs, noting hardware differences.
7. Any deviations, unsuccessful trials, abandoned leads and negative results included.

## Public results

Use cautious language: *observed correlation*, *constructed measurement defect*, *independently validated elapsed-time discrepancy*, or *verified contract false pass*. An experimental result is not automatically a general platform vulnerability.
