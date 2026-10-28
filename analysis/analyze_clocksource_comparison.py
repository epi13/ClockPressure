"""Compare paired timerlat pressure contrasts across Linux clocksources."""

from __future__ import annotations

import argparse
import json
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
    run_summaries: list[dict[str, Any]] = []
    for run in manifest.get("runs", []):
        analysis_path = _resolve(root, str(run.get("analysis_path", "")))
        summary: dict[str, Any] = {
            "pair": run.get("pair"),
            "clocksource": run.get("clocksource"),
            "status": run.get("status"),
            "campaign_status": run.get("campaign_status"),
            "analysis_path": str(analysis_path.relative_to(root))
            if analysis_path.is_relative_to(root)
            else str(analysis_path),
            "analysis_sha256": run.get("analysis_sha256"),
            "pressure_contrasts": {},
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
                source = str(run["clocksource"])
                by_pair.setdefault(pair, {}).setdefault(source, {})[metric] = float(value)
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
        "paired_pressure_contrasts": pair_contrasts,
        "paired_summary": paired_summaries,
        "interpretation_limits": [
            "Clocksource comparisons change Linux system timekeeping, not an independent reference.",
            "CLOCK_MONOTONIC, CLOCK_MONOTONIC_RAW and timerlat trace timestamps are not independent of the selected kernel timekeeping source.",
            "The PHC cross-stamp is a same-host comparison with unverified calibration and capture uncertainty.",
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
