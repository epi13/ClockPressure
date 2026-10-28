import unittest

from analysis.analyze_timerlat_campaign import build_report
from experiments.run_timerlat_campaign import _empty_trace, _option_enabled


class TestTimerlatCampaignAnalysis(unittest.TestCase):
    def test_pairs_probe_and_timerlat_metrics_by_arm_and_replicate(self):
        campaign = {
            "campaign_id": "fixture-campaign",
            "status": "complete",
            "trials": [
                {
                    "replicate": 1,
                    "arm": "timerlat_user",
                    "condition": "baseline",
                    "timerlat_trace": "baseline.trace",
                    "timerlat_trace_sha256": "abc",
                }
            ],
        }
        probe = {}
        for arm in ("timerlat_disabled", "timerlat_user"):
            for replicate in (1, 2):
                baseline = 100 if arm == "timerlat_disabled" else 110
                for condition, delta in (
                    ("baseline", 0),
                    ("cpu_pressure", -2 if arm == "timerlat_disabled" else -4),
                    ("recovery", 0),
                ):
                    probe[(arm, replicate, condition)] = {
                        "run_id": f"{arm}-{replicate}-{condition}",
                        "samples": 100,
                        "wakeup_lateness_ns": {"p99": baseline + delta},
                        "integrity": {"probe.jsonl": "ok"},
                    }
        timerlat = {}
        for replicate in (1, 2):
            for condition, irq in (("baseline", 100), ("cpu_pressure", 140), ("recovery", 105)):
                timerlat[(replicate, condition)] = {
                    "irq": {"p99": irq},
                    "thread": {"p99": irq + 10},
                    "user_return": {"p99": irq + 20},
                }

        report = build_report(campaign, probe, timerlat)
        contrasts = {
            (item.get("arm"), item["contrast"], item["metric"]): item
            for item in report["paired_contrasts"]
        }
        self.assertEqual(
            contrasts[("timerlat_disabled", "pressure_minus_baseline", "clockpressure_wakeup_p99")][
                "paired_difference"]["median"
            ],
            -2,
        )
        self.assertEqual(
            contrasts[("timerlat_user", "pressure_minus_baseline", "timerlat_irq_p99")][
                "paired_difference"]["median"
            ],
            40,
        )
        self.assertEqual(
            report["observer_effects"][0]["paired_difference"]["median"],
            10,
        )
        self.assertEqual(report["per_trial"][0]["timerlat_trace_sha256"], "abc")


class TestTracefsHelpers(unittest.TestCase):
    def test_trace_empty_requires_zero_entries_written(self):
        self.assertTrue(_empty_trace("# entries-in-buffer/entries-written: 0/0 #P:8\n"))
        self.assertFalse(_empty_trace("# entries-in-buffer/entries-written: 0/4 #P:8\n"))
        self.assertFalse(_empty_trace("trace has no recognizable buffer summary"))

    def test_option_state_respects_negative_token(self):
        self.assertTrue(_option_enabled("DEFAULTS OSNOISE_WORKLOAD", "OSNOISE_WORKLOAD"))
        self.assertFalse(_option_enabled("DEFAULTS NO_OSNOISE_WORKLOAD", "OSNOISE_WORKLOAD"))
        self.assertFalse(_option_enabled("DEFAULTS NO_OSNOISE_WORKLOAD OSNOISE_WORKLOAD", "OSNOISE_WORKLOAD"))


if __name__ == "__main__":
    unittest.main()
