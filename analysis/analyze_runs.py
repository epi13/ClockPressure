"""Reproducibly summarize ClockPressure raw run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable


def _quantiles(values: Iterable[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "min": None, "median": None, "p95": None, "p99": None, "max": None}

    def nearest_rank(p: float) -> float:
        return ordered[max(0, math.ceil(p * len(ordered)) - 1)]

    return {
        "n": len(ordered),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": nearest_rank(0.95),
        "p99": nearest_rank(0.99),
        "max": ordered[-1],
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return records


def _rate_comparison(start: dict[str, Any], end: dict[str, Any], clock: str) -> dict[str, float] | None:
    raw_start = start.get("monotonic_raw_ns")
    raw_end = end.get("monotonic_raw_ns")
    other_start = start.get(clock)
    other_end = end.get(clock)
    if None in (raw_start, raw_end, other_start, other_end):
        return None
    raw_interval = raw_end - raw_start
    other_interval = other_end - other_start
    if raw_interval <= 0:
        return None
    # The bracket spans sequential reads at both boundaries; it bounds their
    # unknown alignment conservatively but is not a calibration uncertainty.
    boundary_bracket = start.get("read_bracket_ns", 0) + end.get("read_bracket_ns", 0)
    return {
        "raw_interval_ns": raw_interval,
        "clock_interval_ns": other_interval,
        "difference_ppm_vs_raw": (other_interval - raw_interval) / raw_interval * 1_000_000,
        "endpoint_read_bracket_bound_ppm": boundary_bracket / raw_interval * 1_000_000,
    }


def _period_errors(samples: list[dict[str, Any]], period_ns: int, clock: str) -> list[float]:
    ordered = sorted(samples, key=lambda sample: sample["seq"])
    errors = []
    for earlier, later in zip(ordered, ordered[1:]):
        sequence_delta = later["seq"] - earlier["seq"]
        if sequence_delta <= 0 or earlier.get(clock) is None or later.get(clock) is None:
            continue
        expected = sequence_delta * period_ns
        observed = later[clock] - earlier[clock]
        if expected > 0:
            errors.append((observed - expected) / expected * 1_000_000)
    return errors


def _robust_outlier_count(values: list[float]) -> int:
    if len(values) < 5:
        return 0
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    threshold = median + 6 * mad if mad else median + 1_000
    return sum(value > threshold for value in values)


def _bootstrap_mean_interval(values: list[float], seed: int) -> dict[str, float] | None:
    """A descriptive CI across independent run-pair summaries, never samples."""
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(10000):
        resample = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(statistics.mean(resample))
    estimates.sort()
    return {
        "lower_2_5_percent": estimates[249],
        "upper_97_5_percent": estimates[9749],
    }


def _read_scheduler(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {"event_count": 0, "runnable_latency_ns": _quantiles([])}, None
    latencies = []
    malformed = 0
    for line in path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if event.get("kind") == "sched_runnable_to_run":
            latencies.append(event["runnable_latency_ns"])
    return (
        {
            "event_count": len(latencies),
            "malformed_line_count": malformed,
            "runnable_latency_ns": _quantiles(latencies),
        },
        None,
    )


def _checksum_status(run_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    status = {}
    for filename, expected in manifest.get("artifacts", {}).items():
        path = run_dir / filename
        if not path.is_file():
            status[filename] = "missing"
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        status[filename] = "ok" if digest == expected.get("sha256") else "mismatch"
    return status


def summarize_run(run_dir: Path) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    records = _load_jsonl(run_dir / "probe.jsonl")
    start = next((record for record in records if record.get("kind") == "start"), None)
    end = next((record for record in reversed(records) if record.get("kind") == "end"), None)
    samples = [record for record in records if record.get("kind") == "sample"]
    if start is None or end is None:
        raise ValueError(f"{run_dir}: missing start/end markers")

    lateness = [sample["wakeup_lateness_ns"] for sample in samples]
    cpu_ids = [sample.get("cpu_after") for sample in samples]
    migrations = sum(a != b for a, b in zip(cpu_ids, cpu_ids[1:]) if None not in (a, b))
    tsc_aux = [sample.get("tsc_aux") for sample in samples]
    tsc_aux_migrations = sum(a != b for a, b in zip(tsc_aux, tsc_aux[1:]) if None not in (a, b))
    period_ns = int(manifest["workload"]["period_us"]) * 1_000
    mono_period_error = _period_errors(samples, period_ns, "monotonic_ns")
    raw_period_error = _period_errors(samples, period_ns, "monotonic_raw_ns")
    scheduler, _ = _read_scheduler(run_dir / "scheduler.jsonl")
    integrity = _checksum_status(run_dir, manifest)

    return {
        "run_id": manifest["run_id"],
        "status": manifest["status"],
        "campaign_id": manifest.get("campaign_id"),
        "condition": manifest["condition"],
        "observer": manifest["workload"]["observer"],
        "replicate": manifest.get("replicate"),
        "campaign_role": manifest.get("campaign_role"),
        "code_revision": manifest.get("code_revision"),
        "host_alias": manifest["host"].get("host_alias"),
        "duration_sec_requested": manifest["workload"]["duration_sec"],
        "samples": len(samples),
        "endpoint_intervals_ns": {
            clock: end.get(clock) - start.get(clock)
            for clock in ("monotonic_ns", "monotonic_raw_ns", "boottime_ns", "ptp_ns")
            if end.get(clock) is not None and start.get(clock) is not None
        },
        "internal_rate_comparisons": {
            label: _rate_comparison(start, end, clock)
            for label, clock in (
                ("monotonic_vs_raw", "monotonic_ns"),
                ("boottime_vs_raw", "boottime_ns"),
                ("realtime_vs_raw", "realtime_ns"),
                ("tai_vs_raw", "tai_ns"),
                ("ptp_vs_raw", "ptp_ns"),
            )
        },
        "wakeup_lateness_ns": _quantiles(lateness),
        "wakeup_lateness_exploratory_outliers": _robust_outlier_count(lateness),
        "sample_period_error_ppm_vs_requested_period": {
            "monotonic": _quantiles(mono_period_error),
            "monotonic_raw": _quantiles(raw_period_error),
        },
        "sample_cpu_distribution": {
            str(cpu): cpu_ids.count(cpu) for cpu in sorted({cpu for cpu in cpu_ids if cpu is not None})
        },
        "sample_cpu_migrations_between_adjacent_samples": migrations,
        "tsc_aux_changes_between_adjacent_samples": tsc_aux_migrations,
        "scheduler_witness": scheduler,
        "timestamp_overhead": json.loads((run_dir / "overhead.json").read_text())
        if (run_dir / "overhead.json").exists()
        else None,
        "telemetry_sample_count": len(_load_jsonl(run_dir / "telemetry.jsonl"))
        if (run_dir / "telemetry.jsonl").exists()
        else 0,
        "integrity": integrity,
        "evidence_scope": manifest["measurement_semantics"]["evidence_scope"],
        "reference_status": "no independent external elapsed-time reference was acquired",
    }


def _group_summaries(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs:
        grouped.setdefault((run["condition"], run["observer"]), []).append(run)
    summaries = []
    for (condition, observer), members in sorted(grouped.items()):
        wake_p99 = [run["wakeup_lateness_ns"].get("p99") for run in members]
        mono_rates = [
            run["internal_rate_comparisons"]["monotonic_vs_raw"]["difference_ppm_vs_raw"]
            for run in members
            if run["internal_rate_comparisons"].get("monotonic_vs_raw")
        ]
        ptp_rates = [
            run["internal_rate_comparisons"]["ptp_vs_raw"]["difference_ppm_vs_raw"]
            for run in members
            if run["internal_rate_comparisons"].get("ptp_vs_raw")
        ]
        summaries.append(
            {
                "condition": condition,
                "observer": observer,
                "run_count": len(members),
                "run_p99_wakeup_lateness_ns": _quantiles(
                    [value for value in wake_p99 if value is not None]
                ),
                "run_monotonic_minus_raw_ppm": _quantiles(mono_rates),
                "run_ptp_minus_raw_ppm": _quantiles(ptp_rates),
            }
        )
    return summaries


def _paired_contrasts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare run-level outcomes by campaign replicate; never resample events."""
    indexed = {}
    for run in runs:
        if run.get("campaign_id") is None or run.get("replicate") is None:
            continue
        key = (run["campaign_id"], run["replicate"], run["condition"], run["observer"])
        indexed[key] = run

    campaigns = sorted({run["campaign_id"] for run in runs if run.get("campaign_id")})
    contrasts = []
    for campaign_id in campaigns:
        pressure_differences: dict[str, list[float]] = {"none": [], "sched_bpf": []}
        observer_differences: dict[str, list[float]] = {
            "baseline": [], "cpu_pressure": [], "recovery": []
        }
        replicates = {
            run.get("replicate")
            for run in runs
            if run.get("campaign_id") == campaign_id and run.get("replicate") is not None
        }
        for replicate in replicates:
            for observer in ("none", "sched_bpf"):
                baseline = indexed.get((campaign_id, replicate, "baseline", observer))
                pressure = indexed.get((campaign_id, replicate, "cpu_pressure", observer))
                if baseline and pressure:
                    before = baseline["wakeup_lateness_ns"].get("p99")
                    after = pressure["wakeup_lateness_ns"].get("p99")
                    if before is not None and after is not None:
                        pressure_differences[observer].append(after - before)
            for condition in ("baseline", "cpu_pressure", "recovery"):
                unobserved = indexed.get((campaign_id, replicate, condition, "none"))
                observed = indexed.get((campaign_id, replicate, condition, "sched_bpf"))
                if unobserved and observed:
                    before = unobserved["wakeup_lateness_ns"].get("p99")
                    after = observed["wakeup_lateness_ns"].get("p99")
                    if before is not None and after is not None:
                        observer_differences[condition].append(after - before)
        seed_base = int(hashlib.sha256(campaign_id.encode()).hexdigest()[:8], 16)
        for observer, differences in pressure_differences.items():
            if differences:
                contrasts.append(
                    {
                        "campaign_id": campaign_id,
                        "contrast": "cpu_pressure_minus_baseline",
                        "stratum": f"observer={observer}",
                        "metric": "run_p99_wakeup_lateness_ns",
                        "paired_difference_n": len(differences),
                        "paired_difference_ns": _quantiles(differences),
                        "paired_mean_difference_bootstrap_95_percent_interval_ns": _bootstrap_mean_interval(
                            differences, seed_base + (observer == "sched_bpf")
                        ),
                        "interval_note": "descriptive paired-run resampling only; unavailable below three run pairs",
                    }
                )
        for condition, differences in observer_differences.items():
            if differences:
                contrasts.append(
                    {
                        "campaign_id": campaign_id,
                        "contrast": "sched_bpf_minus_no_observer",
                        "stratum": f"condition={condition}",
                        "metric": "run_p99_wakeup_lateness_ns",
                        "paired_difference_n": len(differences),
                        "paired_difference_ns": _quantiles(differences),
                        "paired_mean_difference_bootstrap_95_percent_interval_ns": _bootstrap_mean_interval(
                            differences, seed_base + 2 + len(contrasts)
                        ),
                        "interval_note": "descriptive paired-run resampling only; unavailable below three run pairs",
                    }
                )
    return contrasts


def _markdown(report: dict[str, Any]) -> str:
    rows = []
    for run in report["runs"]:
        raw = run.get("internal_rate_comparisons", {}).get("monotonic_vs_raw") or {}
        ptp = run.get("internal_rate_comparisons", {}).get("ptp_vs_raw") or {}
        latency = run["wakeup_lateness_ns"]
        sched = run["scheduler_witness"]["runnable_latency_ns"]
        rows.append(
            "| {id} | {condition} | {observer} | {n} | {wake_p99} | {mono_ppm} | {ptp_ppm} | {sched_p99} |".format(
                id=run["run_id"],
                condition=run["condition"],
                observer=run["observer"],
                n=run["samples"],
                wake_p99=_fmt(latency.get("p99")),
                mono_ppm=_fmt(raw.get("difference_ppm_vs_raw")),
                ptp_ppm=_fmt(ptp.get("difference_ppm_vs_raw")),
                sched_p99=_fmt(sched.get("p99")),
            )
        )
    return "\n".join(
        [
            "# ClockPressure initial pilot analysis",
            "",
            f"Runs analyzed: {len(report['runs'])}",
            "",
            "| Run | Condition | eBPF | Samples | Wake late p99 (ns) | MONOTONIC vs RAW (ppm) | NIC PHC vs RAW (ppm) | eBPF runnable latency p99 (ns) |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            "## Paired within-campaign contrasts",
            "",
            "| Campaign | Contrast | Stratum | Matched replicates | Difference median (ns) | Descriptive 95% interval (ns) |",
            "| --- | --- | --- | ---: | ---: | ---: |",
            *[
                "| {campaign} | {contrast} | {stratum} | {n} | {median} | {ci} |".format(
                    campaign=contrast["campaign_id"],
                    contrast=contrast["contrast"],
                    stratum=contrast["stratum"],
                    n=contrast["paired_difference_n"],
                    median=_fmt(contrast["paired_difference_ns"].get("median")),
                    ci=(
                        "{lo} to {hi}".format(
                            lo=_fmt(
                                contrast["paired_mean_difference_bootstrap_95_percent_interval_ns"].get(
                                    "lower_2_5_percent"
                                )
                            ),
                            hi=_fmt(
                                contrast["paired_mean_difference_bootstrap_95_percent_interval_ns"].get(
                                    "upper_97_5_percent"
                                )
                            ),
                        )
                        if contrast["paired_mean_difference_bootstrap_95_percent_interval_ns"]
                        else "not estimable (<3 pairs)"
                    ),
                )
                for contrast in report["paired_contrasts"]
            ],
            "",
            "## Interpretation limits",
            "",
            "- Wakeup lateness is event-delivery delay measured against `CLOCK_MONOTONIC`; it does not establish clock-rate error.",
            "- `CLOCK_MONOTONIC`, `CLOCK_MONOTONIC_RAW`, `CLOCK_BOOTTIME`, and eBPF `bpf_ktime_get_ns()` share the kernel timekeeping path or related hardware. Their differences are internal diagnostics.",
            "- The Intel e1000e PHC is a candidate separate hardware clock. This pilot does not establish oscillator independence, calibration uncertainty, or independent capture of the exact endpoints.",
            "- Endpoint read brackets are reported as conservative acquisition bounds; they are not calibration certificates or a complete uncertainty budget.",
            "- No external elapsed-time reference was acquired, so these data cannot establish physical clock drift or a hardware-caused false pass.",
            "- Raw JSONL, the per-run manifests, source revision and checksums are retained beside this analysis.",
            "",
        ]
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.3f}" if isinstance(value, (float, int)) else str(value)


def analyze(data_dir: Path) -> dict[str, Any]:
    run_root = data_dir / "runs" if (data_dir / "runs").exists() else data_dir
    runs = []
    for run_dir in sorted(run_root.iterdir()):
        if not run_dir.is_dir() or run_dir.name.endswith(".in-progress"):
            continue
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("status") == "complete":
            runs.append(summarize_run(run_dir))
    return {
        "schema": "clockpressure.analysis.v1",
        "analysis_code": "analysis/analyze_runs.py",
        "runs": runs,
        "group_summaries": _group_summaries(runs),
        "paired_contrasts": _paired_contrasts(runs),
        "limits": {
            "external_reference": False,
            "physical_clock_drift_claim_allowed": False,
            "bpf_clock_independent": False,
            "ptp_independence_verified": False,
            "bootstrap_unit": "run-level paired summaries; timer samples are not treated as independent replicates",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    report = analyze(args.data_dir.expanduser().resolve())
    out_dir = args.data_dir.expanduser().resolve()
    (out_dir / "analysis.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out_dir / "analysis.md").write_text(_markdown(report))
    print(f"analyzed {len(report['runs'])} runs in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
