"""Analyze one timerlat-enabled/disabled controlled ClockPressure campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from analysis.analyze_runs import _bootstrap_mean_interval, _quantiles, analyze


def _metric_record(values: list[float], seed: int, unit: str) -> dict[str, Any]:
    return {
        "paired_difference_n": len(values),
        "paired_difference": _quantiles(values),
        "unit": unit,
        "mean_bootstrap_95_percent_interval": _bootstrap_mean_interval(values, seed),
        "interval_note": "descriptive paired-run resampling; samples within a run are not independent replicates",
    }


def _probe_value(run: dict[str, Any], metric: str) -> float | None:
    if metric == "clockpressure_wakeup_p99":
        return run.get("wakeup_lateness_ns", {}).get("p99")
    return None


def build_report(
    campaign: dict[str, Any],
    probe_summaries: dict[tuple[str, int, str], dict[str, Any]],
    timerlat_summaries: dict[tuple[int, str], dict[str, Any]],
) -> dict[str, Any]:
    campaign_id = campaign["campaign_id"]
    metrics: dict[str, list[tuple[str, int, float, str]]] = {}

    for (arm, replicate, condition), run in probe_summaries.items():
        value = _probe_value(run, "clockpressure_wakeup_p99")
        if value is not None:
            metrics.setdefault("clockpressure_wakeup_p99", []).append(
                (arm, replicate, float(value), condition)
            )
        if arm == "timerlat_user":
            summary = timerlat_summaries.get((replicate, condition), {})
            for kind, statistic in summary.items():
                p99 = statistic.get("p99")
                if p99 is not None:
                    metrics.setdefault(f"timerlat_{kind}_p99", []).append(
                        (arm, replicate, float(p99), condition)
                    )

    contrasts: list[dict[str, Any]] = []
    contrast_specs = (
        ("cpu_pressure", "pressure_minus_baseline"),
        ("recovery", "recovery_minus_baseline"),
    )
    probe_map = {
        (arm, replicate, condition): value
        for arm, replicate, value, condition in metrics.get("clockpressure_wakeup_p99", [])
    }
    all_replicates = sorted({replicate for _, replicate, _ in probe_map})
    arms = ("timerlat_disabled", "timerlat_user")
    seed_base = sum(campaign_id.encode())

    for arm_index, arm in enumerate(arms):
        for condition, label in contrast_specs:
            for metric_name, unit in (
                ("clockpressure_wakeup_p99", "ns"),
                ("timerlat_irq_p99", "ns"),
                ("timerlat_thread_p99", "ns"),
                ("timerlat_user_return_p99", "ns"),
            ):
                if metric_name.startswith("timerlat_") and arm != "timerlat_user":
                    continue
                values: list[float] = []
                for replicate in all_replicates:
                    base = probe_map.get((arm, replicate, "baseline")) if metric_name == "clockpressure_wakeup_p99" else None
                    after = probe_map.get((arm, replicate, condition)) if metric_name == "clockpressure_wakeup_p99" else None
                    if metric_name.startswith("timerlat_"):
                        kind = metric_name.removeprefix("timerlat_").removesuffix("_p99")
                        base_summary = timerlat_summaries.get((replicate, "baseline"), {})
                        after_summary = timerlat_summaries.get((replicate, condition), {})
                        base = base_summary.get(kind, {}).get("p99")
                        after = after_summary.get(kind, {}).get("p99")
                    if base is not None and after is not None:
                        values.append(float(after) - float(base))
                if values:
                    contrasts.append(
                        {
                            "arm": arm,
                            "contrast": label,
                            "metric": metric_name,
                            **_metric_record(values, seed_base + arm_index * 31 + len(contrasts), unit),
                        }
                    )

    observer_effects = []
    for condition in ("baseline", "cpu_pressure", "recovery"):
        differences = []
        for replicate in all_replicates:
            disabled = probe_map.get(("timerlat_disabled", replicate, condition))
            enabled = probe_map.get(("timerlat_user", replicate, condition))
            if disabled is not None and enabled is not None:
                differences.append(enabled - disabled)
        if differences:
            observer_effects.append(
                {
                    "condition": condition,
                    "contrast": "timerlat_user_minus_tracer_disabled",
                    "metric": "clockpressure_wakeup_p99",
                    **_metric_record(differences, seed_base + 500 + len(observer_effects), "ns"),
                }
            )

    per_trial = []
    for trial in campaign.get("trials", []):
        arm = trial["arm"]
        replicate = trial["replicate"]
        condition = trial["condition"]
        run = probe_summaries.get((arm, replicate, condition), {})
        timer = timerlat_summaries.get((replicate, condition), {}) if arm == "timerlat_user" else {}
        per_trial.append(
            {
                "replicate": replicate,
                "arm": arm,
                "condition": condition,
                "run_id": run.get("run_id"),
                "probe_samples": run.get("samples"),
                "clockpressure_wakeup_p99_ns": run.get("wakeup_lateness_ns", {}).get("p99"),
                "timerlat_p99_ns": {kind: data.get("p99") for kind, data in timer.items()},
                "run_integrity": run.get("integrity", {}),
                "timerlat_trace": trial.get("timerlat_trace"),
                "timerlat_trace_sha256": trial.get("timerlat_trace_sha256"),
            }
        )

    return {
        "schema": "clockpressure.timerlat-campaign-analysis.v1",
        "campaign_id": campaign_id,
        "campaign_status": campaign.get("status"),
        "external_elapsed_time_reference": None,
        "clockrate_claim_allowed": False,
        "observer_effects": observer_effects,
        "paired_contrasts": contrasts,
        "per_trial": per_trial,
        "interpretation_limits": [
            "timerlat reports Linux interrupt, thread, and return-to-userspace latency; it is not an independent clock",
            "the pinned timerlat reader and FIFO scheduling policy add an observer workload on its selected CPU",
            "CLOCK_MONOTONIC wake lateness measures timer delivery and execution delay, not elapsed-time rate error",
            "bootstrap intervals resample paired run summaries and do not account for calibration uncertainty or campaign-to-campaign variation",
            "no calibrated independent elapsed-time reference is acquired by this campaign",
        ],
    }


def analyze_campaign(campaign_path: Path) -> dict[str, Any]:
    campaign_path = campaign_path.expanduser().resolve()
    campaign = json.loads(campaign_path.read_text())
    root = campaign_path.parent
    if campaign.get("schema") != "clockpressure.timerlat-campaign.v1":
        raise ValueError(f"unsupported campaign schema in {campaign_path}")

    probe_summaries: dict[tuple[str, int, str], dict[str, Any]] = {}
    for arm in ("timerlat_disabled", "timerlat_user"):
        run_root = root / "runs" / arm
        if not run_root.is_dir():
            continue
        report = analyze(run_root)
        (root / f"analysis-{arm}.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        )
        for run in report["runs"]:
            replicate = run.get("replicate")
            condition = run.get("condition")
            if replicate is not None and condition is not None:
                probe_summaries[(arm, int(replicate), str(condition))] = run

    timerlat_summaries: dict[tuple[int, str], dict[str, Any]] = {}
    for trial in campaign.get("trials", []):
        if trial.get("arm") != "timerlat_user":
            continue
        key = (int(trial["replicate"]), str(trial["condition"]))
        timerlat_summaries[key] = trial.get("timerlat_analysis_summary", {})

    report = build_report(campaign, probe_summaries, timerlat_summaries)
    (root / "timerlat-campaign-analysis.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (root / "timerlat-campaign-analysis.md").write_text(_markdown(report))
    return report


def _format(value: Any) -> str:
    return "—" if value is None else f"{value:.6g}" if isinstance(value, (int, float)) else str(value)


def _markdown(report: dict[str, Any]) -> str:
    rows = []
    for trial in report["per_trial"]:
        timer = trial["timerlat_p99_ns"]
        rows.append(
            "| {replicate} | {arm} | {condition} | {samples} | {probe} | {irq} | {thread} | {user} |".format(
                replicate=trial["replicate"],
                arm=trial["arm"],
                condition=trial["condition"],
                samples=trial["probe_samples"] or "—",
                probe=_format(trial["clockpressure_wakeup_p99_ns"]),
                irq=_format(timer.get("irq")),
                thread=_format(timer.get("thread")),
                user=_format(timer.get("user_return")),
            )
        )
    contrast_rows = [
        "| {arm} | {condition} | {metric} | {n} | {median} | {interval} |".format(
            arm=contrast.get("arm", "both arms"),
            condition=contrast.get("contrast", contrast.get("condition")),
            metric=contrast["metric"],
            n=contrast["paired_difference_n"],
            median=_format(contrast["paired_difference"].get("median")),
            interval=(
                f"{_format(contrast['mean_bootstrap_95_percent_interval'].get('lower_2_5_percent'))} to "
                f"{_format(contrast['mean_bootstrap_95_percent_interval'].get('upper_97_5_percent'))} {contrast['unit']}"
                if contrast.get("mean_bootstrap_95_percent_interval")
                else "not estimable (<3 pairs)"
            ),
        )
        for contrast in [*report["paired_contrasts"], *report["observer_effects"]]
    ]
    return "\n".join(
        [
            "# Timerlat controlled campaign analysis",
            "",
            f"Campaign: `{report['campaign_id']}` ({report['campaign_status']})",
            "",
            "All latency values are nanoseconds. Timerlat is a latency tracer, not an elapsed-time reference.",
            "",
            "## Per-trial outcomes",
            "",
            "| Replicate | Arm | Condition | Probe samples | ClockPressure wake P99 | Timerlat IRQ P99 | Thread P99 | User-return P99 |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            "## Paired contrasts",
            "",
            "| Arm | Contrast | Metric | Matched runs | Median paired change | Descriptive 95% mean interval |",
            "| --- | --- | --- | ---: | ---: | ---: |",
            *contrast_rows,
            "",
            "## Interpretation limits",
            "",
            *[f"- {item}" for item in report["interpretation_limits"]],
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    report = analyze_campaign(args.campaign)
    print(
        f"analyzed campaign {report['campaign_id']} with {len(report['per_trial'])} completed records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
