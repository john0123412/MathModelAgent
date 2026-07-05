"""Human modeling gate tests."""

import json
import os
import tempfile
import unittest

from app.core.workflow import MathModelWorkFlow
from app.schemas.A2A import ModelerToCoder
from app.schemas.enums import CompTemplate, ExportProfile, FormatOutPut
from app.schemas.request import Problem


class TestHumanModelingGateArtifacts(unittest.TestCase):
    def test_write_modeling_decision_files(self):
        with tempfile.TemporaryDirectory() as work_dir:
            workflow = MathModelWorkFlow()
            workflow.task_id = "unit-task"
            workflow.work_dir = work_dir
            workflow.questions = {"ques1": "求最优生产方案"}
            workflow.ques_count = 1
            problem = Problem(
                task_id="unit-task",
                ques_all="题面",
                comp_template=CompTemplate.CHINA,
                format_output=FormatOutPut.Markdown,
                export_profile=ExportProfile.CUMCM2026,
            )
            modeler_response = ModelerToCoder(
                questions_solution={"ques1": "建立线性规划模型并做敏感性分析。"}
            )

            workflow._write_modeling_decision(problem, modeler_response)

            decision_json_path = os.path.join(work_dir, "modeling_decision.json")
            decision_md_path = os.path.join(work_dir, "modeling_decision.md")
            self.assertTrue(os.path.exists(decision_json_path))
            self.assertTrue(os.path.exists(decision_md_path))
            with open(decision_json_path, encoding="utf-8") as f:
                decision = json.load(f)
            self.assertEqual(decision["status"], "waiting_review")
            self.assertEqual(decision["export_profile"], "cumcm2026")
            self.assertFalse(decision["review"]["approved"])
            with open(decision_md_path, encoding="utf-8") as f:
                decision_md = f.read()
            self.assertIn("建模方案人工确认", decision_md)
            self.assertIn("/modeling/unit-task/approve-modeling", decision_md)


if __name__ == "__main__":
    unittest.main()
