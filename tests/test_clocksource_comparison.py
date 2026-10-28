import json
import tempfile
import unittest
from pathlib import Path

from analysis.analyze_clocksource_comparison import analyze_comparison, markdown
from experiments.clocksource_selection import ClocksourceSelection


class TestClocksourceSelection(unittest.TestCase):
    def make_sysfs(self, root: Path) -> None:
        root.mkdir()
        (root / "current_clocksource").write_text("tsc\n")
        (root / "available_clocksource").write_text("tsc acpi_pm\n")

    def test_switches_to_requested_source_and_restores_previous_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "clocksource"
            self.make_sysfs(root)
            selection = ClocksourceSelection("acpi_pm", clocksource_root=root)

            with selection:
                self.assertEqual((root / "current_clocksource").read_text().strip(), "acpi_pm")
                self.assertEqual(selection.record["before"], "tsc")
                self.assertEqual(selection.record["active"], "acpi_pm")

            self.assertEqual((root / "current_clocksource").read_text().strip(), "tsc")
            self.assertTrue(selection.record["restored"])
            self.assertEqual(selection.record["after_restore"], "tsc")

    def test_restores_previous_source_when_experiment_raises(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "clocksource"
            self.make_sysfs(root)
            selection = ClocksourceSelection("acpi_pm", clocksource_root=root)

            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with selection:
                    raise RuntimeError("synthetic failure")

            self.assertEqual((root / "current_clocksource").read_text().strip(), "tsc")
            self.assertTrue(selection.record["restored"])

    def test_unavailable_source_is_rejected_without_changing_current_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "clocksource"
            self.make_sysfs(root)
            selection = ClocksourceSelection("hpet", clocksource_root=root)

            with self.assertRaisesRegex(ValueError, "unavailable"):
                with selection:
                    pass

            self.assertEqual((root / "current_clocksource").read_text().strip(), "tsc")


class TestClocksourceComparisonAnalysis(unittest.TestCase):
    def test_pairs_source_specific_pressure_effects_without_clockrate_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {
                "schema": "clockpressure.clocksource-comparison.v1",
                "comparison_id": "fixture",
                "status": "complete",
                "clocksource": {"requested_sources": ["tsc", "acpi_pm"]},
                "design": {"pairs": 3, "seed": 19},
                "runs": [],
            }
            for pair in range(1, 4):
                for source, wake, irq in (
                    ("tsc", -200.0 - pair, -150.0 - pair),
                    ("acpi_pm", -100.0 - pair, -120.0 - pair),
                ):
                    report_path = root / f"pair-{pair}-{source}.json"
                    report_path.write_text(
                        json.dumps(
                            {
                                "campaign_status": "complete",
                                "timerlat_integrity": {"integrity_status": "ok"},
                                "paired_contrasts": [
                                    {
                                        "arm": "timerlat_user",
                                        "contrast": "pressure_minus_baseline",
                                        "metric": "clockpressure_wakeup_p99",
                                        "paired_difference": {"median": wake},
                                    },
                                    {
                                        "arm": "timerlat_user",
                                        "contrast": "pressure_minus_baseline",
                                        "metric": "timerlat_irq_p99",
                                        "paired_difference": {"median": irq},
                                    },
                                ],
                            }
                        )
                    )
                    manifest["runs"].append(
                        {
                            "pair": pair,
                            "clocksource": source,
                            "status": "complete",
                            "campaign_status": "complete",
                            "analysis_path": report_path.name,
                        }
                    )
            manifest_path = root / "comparison.json"
            manifest_path.write_text(json.dumps(manifest))

            report = analyze_comparison(manifest_path)
            rendered = markdown(report)

        wake = next(
            item
            for item in report["paired_summary"]
            if item["metric"] == "clockpressure_wakeup_p99"
        )
        self.assertEqual(report["complete_source_pair_count"], 3)
        self.assertEqual(wake["paired_difference_n"], 3)
        self.assertEqual(wake["intervention_minus_control"]["median"], 100.0)
        self.assertIsNotNone(wake["mean_bootstrap_95_percent_interval"])
        self.assertFalse(report["clockrate_claim_allowed"])
        self.assertIn("not an independent reference", " ".join(report["interpretation_limits"]))
        self.assertIn("intervention-minus-control", rendered)


if __name__ == "__main__":
    unittest.main()
