import json
import subprocess
import sys
import unittest
from pathlib import Path


class TestContractPositiveControl(unittest.TestCase):
    def test_software_timer_positive_control_has_a_false_pass(self):
        script = Path(__file__).resolve().parents[1] / "demos" / "timing_contract_positive_control.py"
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertTrue(report["weak_evaluator_pass"])
        self.assertFalse(report["strong_evaluator_pass"])
        self.assertLessEqual(report["weak_evaluator_reported_elapsed_ns"], report["contract"]["deadline_ns"])
        self.assertGreater(report["strong_evaluator_elapsed_ns"], report["contract"]["deadline_ns"])
