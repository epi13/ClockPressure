import unittest

from analysis.analyze_runs import (
    _bootstrap_mean_interval,
    _group_summaries,
    _period_errors,
    _quantiles,
    _rate_comparison,
)


class TestAnalysis(unittest.TestCase):
    def test_quantiles_use_nearest_rank_and_report_count(self):
        self.assertEqual(
            _quantiles([4, 1, 3, 2]),
            {"n": 4, "min": 1, "median": 2.5, "p95": 4, "p99": 4, "max": 4},
        )

    def test_internal_rate_comparison_keeps_endpoint_bracket_bound(self):
        start = {"monotonic_raw_ns": 10_000, "monotonic_ns": 10_100, "read_bracket_ns": 30}
        end = {"monotonic_raw_ns": 1_010_000, "monotonic_ns": 1_010_105, "read_bracket_ns": 40}
        result = _rate_comparison(start, end, "monotonic_ns")
        self.assertIsNotNone(result)
        self.assertEqual(result["difference_ppm_vs_raw"], 5)
        self.assertEqual(result["endpoint_read_bracket_bound_ppm"], 70)

    def test_sample_period_error_uses_skipped_sequence_delta(self):
        samples = [
            {"seq": 0, "monotonic_ns": 100_000},
            {"seq": 1, "monotonic_ns": 110_100},
            {"seq": 3, "monotonic_ns": 130_200},
        ]
        self.assertEqual(_period_errors(samples, 10_000, "monotonic_ns"), [10_000, 5_000])

    def test_bootstrap_interval_requires_independent_run_pairs(self):
        self.assertIsNone(_bootstrap_mean_interval([1, 2], 42))
        interval = _bootstrap_mean_interval([1, 2, 3], 42)
        self.assertIsNotNone(interval)
        self.assertLessEqual(interval["lower_2_5_percent"], 2)
        self.assertGreaterEqual(interval["upper_97_5_percent"], 2)
        self.assertEqual(interval, _bootstrap_mean_interval([1, 2, 3], 42))

    def test_group_summary_reads_named_internal_rate_comparisons(self):
        summary = _group_summaries(
            [
                {
                    "condition": "baseline",
                    "observer": "none",
                    "wakeup_lateness_ns": {"p99": 500},
                    "internal_rate_comparisons": {
                        "monotonic_vs_raw": {"difference_ppm_vs_raw": 4.5},
                        "ptp_vs_raw": {"difference_ppm_vs_raw": -12.0},
                    },
                }
            ]
        )
        self.assertEqual(summary[0]["run_monotonic_minus_raw_ppm"]["median"], 4.5)
        self.assertEqual(summary[0]["run_ptp_minus_raw_ppm"]["median"], -12.0)
