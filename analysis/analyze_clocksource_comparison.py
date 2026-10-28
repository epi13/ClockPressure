"""Compare paired timerlat pressure contrasts across Linux clocksources."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from analysis.analyze_runs import _bootstrap_mean_interval, _quantiles


_FOCUS_METRICS = {
    "clockpressure_wakeup_p99": "ns",
    "timerlat_irq_p99": "ns",
    "timerlat_thread_p99": "ns",
    "timerlat_user_return_p99": "ns",
    "clockpressure_crossstamp_fit_rate": "ppm",
    "clockpressure_monotonic_vs_raw_rate": "ppm",
}


def _resolve(root: Path, relative: str) -> Path:
    path = Path(relative)
    return path if path.is_absolute() else root / path


def _ptp_capability(campaign_dir: Path) -> dict[str, Any]:
    """Count PTP open and precise-crossstamp results from native probe metadata."""
    probe_files = 0
    metadata_records = 0
    open_counts: Counter[str] = Counter()
    precise_counts: Counter[str] = Counter()
    errno_counts: Counter[str] = Counter()
    for path in sorted(campaign_dir.rglob("probe.jsonl")):
        probe_files += 1
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
                if record.get("kind") != "metadata":
                    continue
                metadata_records += 1
                open_counts[str(record.get("ptp_open", "missing"))] += 1
                precise_counts[
                    str(record.get("ptp_precise_crossstamp_available", "missing"))
                ] += 1
                if record.get("ptp_precise_probe_errno") is not None:
                    errno_counts[str(record["ptp_precise_probe_errno"])] += 1
    return {
        "probe_file_count": probe_files,
        "metadata_record_count": metadata_records,
        "ptp_open": dict(sorted(open_counts.items())),
        "precise_crossstamp_available": dict(sorted(precise_counts.items())),
        "precise_probe_errno_counts": dict(
            sorted(errno_counts.items(), key=lambda item: int(item[0]))
        ),
    }


def analyze_comparison(manifest_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "clockpressure.clocksource-comparison.v1":
        raise ValueError(f"unsupported clocksource comparison manifest: {manifest_path}")

    sources = list(manifest.get("clocksource", {}).get("requested_sources", []))
    design = manifest.get("design", {})
    seed = int(design.get("seed", 0))
    by_pair: dict[int, dict[str, dict[str, float]]] = {}
    by_source: dict[str, dict[str, list[float]]] = {}
    ptp_by_source: dict[str, dict[str, Any]] = {}
    run_summaries: list[dict[str, Any]] = []
    for run in manifest.get("runs", []):
        analysis_path = _resolve(root, str(run.get("analysis_path", "")))
        campaign_path = _resolve(root, str(run.get("campaign_path", "")))
        campaign_dir = campaign_path.parent if campaign_path.is_file() else analysis_path.parent
        source = str(run.get("clocksource", "unknown"))
        ptp = _ptp_capability(campaign_dir)
        source_ptp = ptp_by_source.setdefault(
            source,
            {
                "probe_file_count": 0,
                "metadata_record_count": 0,
                "ptp_open": Counter(),
                "precise_crossstamp_available": Counter(),
                "precise_probe_errno_counts": Counter(),
            },
        )
        source_ptp["probe_file_count"] += ptp["probe_file_count"]
        source_ptp["metadata_record_count"] += ptp["metadata_record_count"]
        for key in ("ptp_open", "precise_crossstamp_available", "precise_probe_errno_counts"):
            source_ptp[key].update(ptp[key])
        summary: dict[str, Any] = {
            "pair": run.get("pair"),
            "clocksource": source,
            "status": run.get("status"),
            "campaign_status": run.get("campaign_status"),
            "analysis_path": str(analysis_path.relative_to(root))
            if analysis_path.is_relative_to(root)
            else str(analysis_path),
            "analysis_sha256": run.get("analysis_sha256"),
            "pressure_contrasts": {},
            "ptp_capability": ptp,
        }
        if not analysis_path.is_file():
            summary["analysis_error"] = "analysis report is missing"
            run_summaries.append(summary)
            continue
        report = json.loads(analysis_path.read_text())
        if report.get("campaign_status") != "complete":
            summary["analysis_error"] = "underlying timerlat campaign did not complete"
            run_summaries.append(summary)
            continue
        for contrast in report.get("paired_contrasts", []):
            if contrast.get("arm") != "timerlat_user":
                continue
            if contrast.get("contrast") != "pressure_minus_baseline":
                continue
            metric = contrast.get("metric")
            if metric not in _FOCUS_METRICS:
                continue
            value = contrast.get("paired_difference", {}).get("median")
            if isinstance(value, (int, float)):
                summary["pressure_contrasts"][metric] = float(value)
                pair = int(run["pair"])
                by_pair.setdefault(pair, {}).setdefault(source, {})[metric] = float(value)
                by_source.setdefault(source, {}).setdefault(metric, []).append(float(value))
        summary["timerlat_integrity"] = report.get("timerlat_integrity")
        run_summaries.append(summary)

    pair_contrasts = []
    metric_differences: dict[str, list[float]] = {metric: [] for metric in _FOCUS_METRICS}
    if len(sources) >= 2:
        control_source, intervention_source = sources[0], sources[1]
        for pair, source_values in sorted(by_pair.items()):
            for metric, unit in _FOCUS_METRICS.items():
                control = source_values.get(control_source, {}).get(metric)
                intervention = source_values.get(intervention_source, {}).get(metric)
                if control is None or intervention is None:
                    continue
                difference = intervention - control
                metric_differences[metric].append(difference)
                pair_contrasts.append(
                    {
                        "pair": pair,
                        "control_clocksource": control_source,
                        "intervention_clocksource": intervention_source,
                        "metric": metric,
                        "control_pressure_minus_baseline": control,
                        "intervention_pressure_minus_baseline": intervention,
                        "intervention_minus_control": difference,
                        "unit": unit,
                    }
                )

    paired_summaries = []
    for metric_index, (metric, unit) in enumerate(_FOCUS_METRICS.items()):
        values = metric_differences[metric]
        paired_summaries.append(
            {
                "metric": metric,
                "unit": unit,
                "paired_difference_n": len(values),
                "intervention_minus_control": _quantiles(values),
                "mean_bootstrap_95_percent_interval": _bootstrap_mean_interval(
                    values, seed + metric_index
                ),
                "interval_note": (
                    "descriptive bootstrap across randomized source-pair pressure contrasts; "
                    "not a calibration uncertainty budget"
                ),
            }
        )

    source_pressure_summaries = []
    for source in sources:
        for metric, unit in _FOCUS_METRICS.items():
            values = by_source.get(source, {}).get(metric, [])
            source_pressure_summaries.append(
                {
                    "clocksource": source,
                    "metric": metric,
                    "unit": unit,
                    "pressure_effect_n": len(values),
                    "pressure_minus_baseline": _quantiles(values),
                }
            )

    ptp_capability_by_clocksource = []
    for source in sources:
        counts = ptp_by_source.get(source, {})
        ptp_capability_by_clocksource.append(
            {
                "clocksource": source,
                "probe_file_count": counts.get("probe_file_count", 0),
                "metadata_record_count": counts.get("metadata_record_count", 0),
                "ptp_open": dict(sorted(counts.get("ptp_open", {}).items())),
                "precise_crossstamp_available": dict(
                    sorted(counts.get("precise_crossstamp_available", {}).items())
                ),
                "precise_probe_errno_counts": dict(
                    sorted(
                        counts.get("precise_probe_errno_counts", {}).items(),
                        key=lambda item: int(item[0]),
                    )
                ),
            }
        )

    complete_pair_count = len(
        {
            pair
            for pair, source_values in by_pair.items()
            if len(sources) >= 2 and all(source in source_values for source in sources[:2])
        }
    )
    return {
        "schema": "clockpressure.clocksource-comparison-analysis.v1",
        "comparison_id": manifest.get("comparison_id"),
        "comparison_status": manifest.get("status"),
        "campaign_data_dir": str(root),
        "clocksource_order": sources,
        "design": design,
        "clockrate_claim_allowed": False,
        "external_elapsed_time_reference": None,
        "complete_source_pair_count": complete_pair_count,
        "per_run": run_summaries,
        "per_clocksource_pressure_effects": source_pressure_summaries,
        "ptp_capability_by_clocksource": ptp_capability_by_clocksource,
        "paired_pressure_contrasts": pair_contrasts,
        "paired_summary": paired_summaries,
        "interpretation_limits": [
            "Clocksource comparisons change Linux system timekeeping, not an independent reference.",
            "CLOCK_MONOTONIC, CLOCK_MONOTONIC_RAW and timerlat trace timestamps are not independent of the selected kernel timekeeping source.",
            "The PHC cross-stamp is a same-host comparison with unverified calibration and capture uncertainty.",
            "PTP_SYS_OFFSET_PRECISE availability is a capability result; losing this ioctl under a selected source does not show that the PHC or clocksource rate changed.",
            "Intervals resample randomized source-pair summaries and do not include serial correlation or source-switch calibration uncertainty.",
            "Timer and clock-interface changes cannot establish actual elapsed-time error without an independent calibrated reference.",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    sources = report["clocksource_order"]
    if len(sources) >= 2:
        control, intervention = sources[:2]
    else:
        control, intervention = "control", "intervention"
    summary_rows = []
    for item in report["paired_summary"]:
        values = item["intervention_minus_control"]
        interval = item["mean_bootstrap_95_percent_interval"]
        if item["paired_difference_n"] == 0:
            summary_rows.append(
                f"| {item['metric']} | 0 | — | not estimable | {item['unit']} |"
            )
        else:
            estimate = values.get("median")
            if interval is None:
                interval_text = "not estimable (<3 pairs)"
            else:
                interval_text = (
                    f"{interval['lower_2_5_percent']:.6g} to "
                    f"{interval['upper_97_5_percent']:.6g}"
                )
            summary_rows.append(
                f"| {item['metric']} | {item['paired_difference_n']} | {estimate:.6g} | "
                f"{interval_text} | {item['unit']} |"
            )
    pair_rows = [
        f"| {item['pair']} | {item['metric']} | {item['control_pressure_minus_baseline']:.6g} | "
        f"{item['intervention_pressure_minus_baseline']:.6g} | "
        f"{item['intervention_minus_control']:.6g} | {item['unit']} |"
        for item in report["paired_pressure_contrasts"]
    ]
    source_pressure_rows = []
    for item in report["per_clocksource_pressure_effects"]:
        values = item["pressure_minus_baseline"]
        median = "—" if item["pressure_effect_n"] == 0 else f"{values['median']:.6g}"
        source_pressure_rows.append(
            f"| {item['clocksource']} | {item['metric']} | {item['pressure_effect_n']} | "
            f"{median} | {item['unit']} |"
        )
    ptp_rows = []
    for item in report["ptp_capability_by_clocksource"]:
        opened = item["ptp_open"].get("True", 0)
        precise = item["precise_crossstamp_available"].get("True", 0)
        precise_failed = item["precise_crossstamp_available"].get("False", 0)
        errno_counts = ", ".join(
            f"{code}: {count}" for code, count in item["precise_probe_errno_counts"].items()
        ) or "—"
        ptp_rows.append(
            f"| {item['clocksource']} | {item['metadata_record_count']} | {opened} | "
            f"{precise} | {precise_failed} | {errno_counts} |"
        )
    return "\n".join(
        [
            "# Linux clocksource comparison analysis",
            "",
            f"Comparison: `{report['comparison_id']}` ({report['comparison_status']})",
            f"Clocksource contrast: `{control}` to `{intervention}`; complete source pairs: {report['complete_source_pair_count']}.",
            "",
            "The outcome is the timerlat-enabled arm's pressure-minus-baseline change. The final column compares that change under the second source with the first source.",
            "",
            "## Paired source effect",
            "",
            "| Metric | Source pairs | Median intervention-minus-control | Descriptive 95% mean interval | Unit |",
            "| --- | ---: | ---: | ---: | --- |",
            *summary_rows,
            "",
            "## Pressure effects by selected source",
            "",
            "These are within-source timerlat-enabled pressure-minus-baseline contrasts. They describe timer delivery/latency and are not rate estimates.",
            "",
            "| Clocksource | Metric | Runs | Median pressure effect | Unit |",
            "| --- | --- | ---: | ---: | --- |",
            *source_pressure_rows,
            "",
            "## PTP precise crossstamp availability",
            "",
            "The probe opens `/dev/ptp0`, then attempts `PTP_SYS_OFFSET_PRECISE`. This table reports interface capability, not measurement accuracy.",
            "",
            "| Clocksource | Metadata samples | PTP opens | Precise success | Precise failure | Errno counts |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
            *ptp_rows,
            "",
            "## Per-pair pressure contrasts",
            "",
            f"| Pair | Metric | {control} pressure effect | {intervention} pressure effect | Difference | Unit |",
            "| ---: | --- | ---: | ---: | ---: | --- |",
            *pair_rows,
            "",
            "## Interpretation limits",
            "",
            *[f"- {limit}" for limit in report["interpretation_limits"]],
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path)
    args = parser.parse_args()
    report = analyze_comparison(args.comparison)
    root = args.comparison.resolve().parent
    json_path = root / "clocksource-comparison-analysis.json"
    markdown_path = root / "clocksource-comparison-analysis.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown_path.write_text(markdown(report))
    print(f"analyzed clocksource comparison {report['comparison_id']}; pairs={report['complete_source_pair_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
