"""Analyze one timerlat-enabled/disabled controlled ClockPressure campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from analysis.analyze_runs import _bootstrap_mean_interval, _quantiles, analyze
from analysis.analyze_timerlat import analyze_trace

_PROBE_METRICS = {
    "clockpressure_wakeup_p99": "ns",
    "clockpressure_crossstamp_fit_rate": "ppm",
    "clockpressure_monotonic_vs_raw_rate": "ppm",
    "cpu_c10_aggregate_residency": "percentage_points",
    "probe_cpu_c10_residency": "percentage_points",
    "timerlat_cpu_c10_residency": "percentage_points",
    "probe_adjacent_sample_migrations": "count",
}
_TIMERLAT_KINDS = ("irq", "thread", "user_return")


def _metric_record(values: list[float], seed: int, unit: str) -> dict[str, Any]:
    return {
        "paired_difference_n": len(values),
        "paired_difference": _quantiles(values),
        "unit": unit,
        "mean_bootstrap_95_percent_interval": _bootstrap_mean_interval(values, seed),
        "interval_note": "descriptive paired-run resampling; samples within a run are not independent replicates",
    }


def _resolve_artifact(root: Path, value: str) -> Path | None:
    recorded = Path(value)
    if not recorded.is_absolute():
        candidate = root / recorded
        return candidate if candidate.is_file() else None
    if recorded.is_file():
        return recorded
    parts = recorded.parts
    if "timerlat" in parts:
        candidate = root.joinpath(*parts[parts.index("timerlat") :])
        if candidate.is_file():
            return candidate
    matches = list(root.rglob(recorded.name))
    return matches[0] if len(matches) == 1 else None


def _parse_trace_buffer_stats(value: str | None) -> dict[str, int]:
    stats: dict[str, int] = {}
    for line in (value or "").splitlines():
        key, separator, raw = line.partition(":")
        if not separator:
            continue
        try:
            number = int(raw.strip())
        except ValueError:
            continue
        stats[key.strip().lower().replace(" ", "_")] = number
    return stats


def _probe_value(
    run: dict[str, Any], metric: str, probe_cpu: int, timerlat_cpu: int
) -> float | None:
    if metric == "clockpressure_wakeup_p99":
        return run.get("wakeup_lateness_ns", {}).get("p99")
    if metric == "clockpressure_crossstamp_fit_rate":
        return (run.get("paired_crossstamp_dynamics") or {}).get("least_squares_rate_difference_ppm")
    if metric == "clockpressure_monotonic_vs_raw_rate":
        return (run.get("internal_rate_comparisons", {}).get("monotonic_vs_raw") or {}).get(
            "difference_ppm_vs_raw"
        )
    if metric == "cpu_c10_aggregate_residency":
        return (
            run.get("environment_telemetry", {})
            .get("cpu_idle_residency_pct_of_cpu_capacity_by_state_name", {})
            .get("C10")
        )
    if metric in ("probe_cpu_c10_residency", "timerlat_cpu_c10_residency"):
        cpu = probe_cpu if metric == "probe_cpu_c10_residency" else timerlat_cpu
        return (
            run.get("environment_telemetry", {})
            .get("cpu_idle_residency_pct_by_cpu_state_name", {})
            .get(f"cpu{cpu}", {})
            .get("C10")
        )
    if metric == "probe_adjacent_sample_migrations":
        return run.get("sample_cpu_migrations_between_adjacent_samples")
    return None


def build_report(
    campaign: dict[str, Any],
    probe_summaries: dict[tuple[str, int, str], dict[str, Any]],
    timerlat_summaries: dict[tuple[str, int, str], dict[str, Any]],
) -> dict[str, Any]:
    campaign_id = campaign["campaign_id"]
    design = campaign.get("design", {})
    probe_cpu = int(design.get("probe_cpu", 6))
    timerlat_cpu = int(design.get("timerlat_cpu", 7))
    probe_values: dict[str, dict[tuple[str, int, str], float]] = {
        metric: {} for metric in _PROBE_METRICS
    }
    for key, run in probe_summaries.items():
        for metric in _PROBE_METRICS:
            value = _probe_value(run, metric, probe_cpu, timerlat_cpu)
            if value is not None:
                probe_values[metric][key] = float(value)

    contrasts: list[dict[str, Any]] = []
    contrast_specs = (
        ("cpu_pressure", "pressure_minus_baseline"),
        ("recovery", "recovery_minus_baseline"),
    )
    probe_map = probe_values["clockpressure_wakeup_p99"]
    all_replicates = sorted({replicate for _, replicate, _ in probe_map})
    design = campaign.get("design", {})
    arms = tuple(design.get("arms") or ("timerlat_disabled", "timerlat_user"))
    configured_timerlat_arms = design.get("timerlat_arms")
    if not configured_timerlat_arms or "timerlat_disabled" in configured_timerlat_arms:
        timerlat_arms = {arm for arm in arms if arm.startswith("timerlat_user")}
    else:
        timerlat_arms = set(configured_timerlat_arms)
    seed_base = sum(campaign_id.encode())

    for arm_index, arm in enumerate(arms):
        for condition, label in contrast_specs:
            metric_specs = list(_PROBE_METRICS.items())
            if arm in timerlat_arms:
                metric_specs.extend((f"timerlat_{kind}_p99", "ns") for kind in _TIMERLAT_KINDS)
            for metric_name, unit in metric_specs:
                values: list[float] = []
                if metric_name.startswith("timerlat_") and metric_name.endswith("_p99"):
                    kind = metric_name.removeprefix("timerlat_").removesuffix("_p99")
                    for replicate in all_replicates:
                        base_summary = timerlat_summaries.get((arm, replicate, "baseline"), {})
                        after_summary = timerlat_summaries.get((arm, replicate, condition), {})
                        base = base_summary.get(kind, {}).get("p99")
                        after = after_summary.get(kind, {}).get("p99")
                        if base is not None and after is not None:
                            values.append(float(after) - float(base))
                else:
                    value_map = probe_values[metric_name]
                    for replicate in all_replicates:
                        base = value_map.get((arm, replicate, "baseline"))
                        after = value_map.get((arm, replicate, condition))
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
    if "timerlat_disabled" in arms and "timerlat_user" in arms:
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

    intervention_effects = []
    intervention = design.get("cpu_dma_latency_intervention")
    if intervention:
        default_arm = "timerlat_user_default"
        intervention_arm = str(intervention.get("arm", "timerlat_user_pm_qos"))
        for condition in ("baseline", "cpu_pressure", "recovery"):
            for metric_name, unit in (
                *list(_PROBE_METRICS.items()),
                *((f"timerlat_{kind}_p99", "ns") for kind in _TIMERLAT_KINDS),
            ):
                values = []
                for replicate in all_replicates:
                    if metric_name.startswith("timerlat_") and metric_name.endswith("_p99"):
                        kind = metric_name.removeprefix("timerlat_").removesuffix("_p99")
                        default = timerlat_summaries.get((default_arm, replicate, condition), {}).get(
                            kind, {}
                        ).get("p99")
                        treated = timerlat_summaries.get((intervention_arm, replicate, condition), {}).get(
                            kind, {}
                        ).get("p99")
                    else:
                        default = probe_values[metric_name].get((default_arm, replicate, condition))
                        treated = probe_values[metric_name].get((intervention_arm, replicate, condition))
                    if default is not None and treated is not None:
                        values.append(float(treated) - float(default))
                if values:
                    intervention_effects.append(
                        {
                            "condition": condition,
                            "control_arm": default_arm,
                            "intervention_arm": intervention_arm,
                            "contrast": "cpu_dma_latency_intervention_minus_default",
                            "metric": metric_name,
                            **_metric_record(
                                values,
                                seed_base + 700 + len(intervention_effects),
                                unit,
                            ),
                        }
                    )

    per_trial = []
    for trial in campaign.get("trials", []):
        arm = trial["arm"]
        replicate = trial["replicate"]
        condition = trial["condition"]
        run = probe_summaries.get((arm, replicate, condition), {})
        timer = timerlat_summaries.get((arm, replicate, condition), {}) if arm in timerlat_arms else {}
        probe_metrics = {
            metric: _probe_value(run, metric, probe_cpu, timerlat_cpu)
            for metric in _PROBE_METRICS
        }
        per_trial.append(
            {
                "replicate": replicate,
                "arm": arm,
                "condition": condition,
                "trial_status": trial.get("status"),
                "trial_error": trial.get("error"),
                "run_id": run.get("run_id"),
                "probe_samples": run.get("samples"),
                "clockpressure_metrics": probe_metrics,
                "clockpressure_wakeup_p99_ns": probe_metrics["clockpressure_wakeup_p99"],
                "clockpressure_crossstamp_fit_rate_ppm": probe_metrics[
                    "clockpressure_crossstamp_fit_rate"
                ],
                "clockpressure_monotonic_vs_raw_rate_ppm": probe_metrics[
                    "clockpressure_monotonic_vs_raw_rate"
                ],
                "cpu_c10_aggregate_residency_pct": probe_metrics[
                    "cpu_c10_aggregate_residency"
                ],
                "probe_cpu_c10_residency_pct": probe_metrics[
                    "probe_cpu_c10_residency"
                ],
                "timerlat_cpu_c10_residency_pct": probe_metrics[
                    "timerlat_cpu_c10_residency"
                ],
                "probe_adjacent_sample_migrations": probe_metrics[
                    "probe_adjacent_sample_migrations"
                ],
                "timerlat_p99_ns": {kind: data.get("p99") for kind, data in timer.items()},
                "run_integrity": run.get("integrity", {}),
                "timerlat_trace": trial.get("timerlat_trace"),
                "timerlat_trace_sha256": trial.get("timerlat_trace_sha256"),
                "timerlat_trace_integrity": trial.get("timerlat_trace_integrity"),
                "timerlat_activation_integrity": trial.get("timerlat_activation_integrity"),
                "timerlat_buffer_stats": _parse_trace_buffer_stats(
                    trial.get("tracefs_restoration", {}).get("cpu_buffer_stats")
                ) if arm in timerlat_arms else None,
                "timerlat_user_worker": trial.get("timerlat_user_worker") if arm in timerlat_arms else None,
                "cpu_dma_latency_request": trial.get("cpu_dma_latency_request"),
            }
        )

    timerlat_trials = [trial for trial in per_trial if trial["arm"] in timerlat_arms]
    trace_integrity_counts = {
        state: sum(trial.get("timerlat_trace_integrity") == state for trial in timerlat_trials)
        for state in ("ok", "mismatch", "missing")
    }
    timerlat_integrity = {
        "trace_integrity_counts": trace_integrity_counts,
        "matched_irq_thread_activations": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "matched_irq_thread_activations", 0
            )
            for trial in timerlat_trials
        ),
        "incomplete_irq_thread_activations": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "incomplete_irq_thread_activations", 0
            )
            for trial in timerlat_trials
        ),
        "duplicate_activation_events": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "duplicate_activation_events", 0
            )
            for trial in timerlat_trials
        ),
        "malformed_latency_lines": sum(
            (trial.get("timerlat_activation_integrity") or {}).get(
                "malformed_latency_lines", 0
            )
            for trial in timerlat_trials
        ),
        "trace_buffer_overrun": sum(
            (trial.get("timerlat_buffer_stats") or {}).get("overrun", 0)
            for trial in timerlat_trials
        ),
        "trace_buffer_commit_overrun": sum(
            (trial.get("timerlat_buffer_stats") or {}).get("commit_overrun", 0)
            for trial in timerlat_trials
        ),
        "trace_buffer_dropped_events": sum(
            (trial.get("timerlat_buffer_stats") or {}).get("dropped_events", 0)
            for trial in timerlat_trials
        ),
    }

    return {
        "schema": "clockpressure.timerlat-campaign-analysis.v1",
        "campaign_id": campaign_id,
        "campaign_status": campaign.get("analysis_status", campaign.get("status")),
        "campaign_recorded_status": campaign.get("status"),
        "campaign_status_note": campaign.get("analysis_status_note"),
        "external_elapsed_time_reference": None,
        "clockrate_claim_allowed": False,
        "observer_effects": observer_effects,
        "intervention_effects": intervention_effects,
        "timerlat_integrity": timerlat_integrity,
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
    incomplete_trials = [
        trial for trial in campaign.get("trials", []) if trial.get("status") != "complete"
    ]
    if campaign.get("status") == "complete" and incomplete_trials:
        campaign["analysis_status"] = "failed"
        campaign["analysis_status_note"] = (
            "one or more trial records are not complete even though the stored campaign status is complete; "
            "the analyzer treats this campaign as failed"
        )

    probe_summaries: dict[tuple[str, int, str], dict[str, Any]] = {}
    arms = campaign.get("design", {}).get("arms") or ("timerlat_disabled", "timerlat_user")
    configured_timerlat_arms = campaign.get("design", {}).get("timerlat_arms")
    if not configured_timerlat_arms or "timerlat_disabled" in configured_timerlat_arms:
        timerlat_arms = {arm for arm in arms if arm.startswith("timerlat_user")}
    else:
        timerlat_arms = set(configured_timerlat_arms)
    for arm in arms:
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

    timerlat_summaries: dict[tuple[str, int, str], dict[str, Any]] = {}
    for trial in campaign.get("trials", []):
        arm = str(trial.get("arm"))
        if arm not in timerlat_arms:
            continue
        key = (arm, int(trial["replicate"]), str(trial["condition"]))
        recorded_trace = trial.get("timerlat_trace")
        trace_path = _resolve_artifact(root, recorded_trace) if recorded_trace else None
        if trace_path is None:
            trial["timerlat_trace_integrity"] = "missing"
            if trial.get("status") == "complete":
                raise ValueError(f"completed timerlat trial is missing its trace: {recorded_trace}")
            continue
        digest = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        if digest != trial.get("timerlat_trace_sha256"):
            trial["timerlat_trace_integrity"] = "mismatch"
            raise ValueError(f"timerlat trace checksum mismatch: {trace_path}")
        trial["timerlat_trace_integrity"] = "ok"
        trial["timerlat_trace"] = trace_path.relative_to(root).as_posix()
        parsed = analyze_trace(trace_path)
        trial["timerlat_analysis_summary"] = parsed["latency_ns"]
        trial["timerlat_activation_integrity"] = {
            "matched_irq_thread_activations": parsed["matched_irq_thread_activation_count"],
            "incomplete_irq_thread_activations": parsed["incomplete_irq_thread_activation_count"],
            "duplicate_activation_events": parsed["duplicate_activation_event_count"],
            "malformed_latency_lines": parsed["malformed_latency_line_count"],
        }
        timerlat_summaries[key] = parsed["latency_ns"]

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
            "| {replicate} | {arm} | {condition} | {samples} | {probe} | {irq} | {thread} | {user} | {crossstamp} | {mono_raw} | {c10} | {probe_c10} | {timerlat_c10} | {migrations} |".format(
                replicate=trial["replicate"],
                arm=trial["arm"],
                condition=trial["condition"],
                samples=trial["probe_samples"] or "—",
                probe=_format(trial["clockpressure_wakeup_p99_ns"]),
                irq=_format(timer.get("irq")),
                thread=_format(timer.get("thread")),
                user=_format(timer.get("user_return")),
                crossstamp=_format(trial["clockpressure_crossstamp_fit_rate_ppm"]),
                mono_raw=_format(trial["clockpressure_monotonic_vs_raw_rate_ppm"]),
                c10=_format(trial["cpu_c10_aggregate_residency_pct"]),
                probe_c10=_format(trial["probe_cpu_c10_residency_pct"]),
                timerlat_c10=_format(trial["timerlat_cpu_c10_residency_pct"]),
                migrations=_format(trial["probe_adjacent_sample_migrations"]),
            )
        )
    contrast_rows = [
        "| {arm} | {condition} | {metric} | {n} | {median} | {interval} |".format(
            arm=contrast.get(
                "arm",
                f"{contrast['control_arm']}→{contrast['intervention_arm']}"
                if "control_arm" in contrast
                else "both arms",
            ),
            condition=contrast.get("condition", contrast.get("contrast")),
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
        for contrast in [
            *report["paired_contrasts"],
            *report["observer_effects"],
            *report["intervention_effects"],
        ]
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
            "| Replicate | Arm | Condition | Probe samples | ClockPressure wake P99 (ns) | Timerlat IRQ P99 (ns) | Thread P99 (ns) | User-return P99 (ns) | PHC/MONORAW fit (ppm) | MONOTONIC/RAW (ppm) | Aggregate C10 (%) | Probe CPU C10 (%) | Timerlat CPU C10 (%) | Probe migrations |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
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
        f"analyzed campaign {report['campaign_id']} with {len(report['per_trial'])} trial records "
        f"(status: {report['campaign_status']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
