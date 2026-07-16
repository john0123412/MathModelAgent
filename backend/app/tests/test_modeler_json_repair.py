"""Regression tests for bounded Modeler JSON repair."""

import json
import unittest

from app.core.agents.modeler_agent import repair_json


class ModelerJsonRepairTest(unittest.TestCase):
    def test_repairs_bare_quotes_embedded_in_chinese_prose(self):
        raw = (
            '```json\n{"schema_version":"mathmodel.model-plan.v1",'
            '"method":"滤波后得到"纯"双光束干涉光谱，再计算厚度",'
            '"items":["附件3","附件4"]}\n```'
        )

        repaired = repair_json(raw)

        self.assertIsNotNone(repaired)
        self.assertEqual(
            repaired["method"],
            '滤波后得到"纯"双光束干涉光谱，再计算厚度',
        )
        self.assertEqual(repaired["items"], ["附件3", "附件4"])

    def test_preserves_valid_structural_and_escaped_quotes(self):
        payload = {
            "method": '保留已转义的"术语"',
            "flags": [True, False, None, 3],
            "nested": {"status": "ok"},
        }
        raw = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(repair_json(raw), payload)

    def test_repairs_inner_quote_before_ascii_comma_in_object_prose(self):
        raw = '{"method":"call it "clean", then fit", "status":"ok"}'

        repaired = repair_json(raw)

        self.assertIsNotNone(repaired)
        self.assertEqual(repaired["method"], 'call it "clean", then fit')
        self.assertEqual(repaired["status"], "ok")


if __name__ == "__main__":
    unittest.main()
