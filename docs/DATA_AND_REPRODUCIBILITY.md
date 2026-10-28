# Data and reproducibility contract

## Principle

Raw measurements are the evidence. Derived summaries, charts and agent explanations are projections that should be reproducible from recorded inputs and versioned analysis code.

## Recommended layout (when implementation begins)

```text
data/
  README.md                   # storage, privacy, sharing policy
  examples/                   # small synthetic fixtures only
experiments/
  <protocol-version>/         # scripts/configuration
results/
  <run-id>/                   # local or external artifacts; not committed by default
```

Large or privacy-sensitive raw traces should stay outside normal Git history and be referenced with checksums and access-controlled storage where needed. Do not commit private worker-03 details. Synthetic fixtures must be explicitly marked.

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
