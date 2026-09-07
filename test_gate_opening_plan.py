import sys
import types
import unittest

requests = types.ModuleType("requests")
requests.Session = object
requests.Response = object
requests.adapters = types.SimpleNamespace(HTTPAdapter=object)
sys.modules.setdefault("requests", requests)

from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from intent_api_server import (  # noqa: E402
    calculate_gate_opening_scenarios,
    format_gate_opening_analysis_process,
)


class GateOpeningPlanTests(unittest.TestCase):
    def test_chaobaihe_estimate_plan_contains_seven_sections_for_300_flow(self):
        calculation = calculate_gate_opening_scenarios(target_flow=300)

        output = format_gate_opening_analysis_process(calculation)

        self.assertEqual(calculation["mode"], "estimate")
        self.assertEqual(calculation["parameters"]["gate_count"], 9)
        self.assertEqual(calculation["parameters"]["gate_width"], 35)
        self.assertEqual(calculation["recommended"]["gate_count"], 9)
        self.assertTrue(0.30 <= calculation["recommended"]["equivalent_opening"] <= 0.45)
        for section in (
        "【1、已知条件和数据】",
        "【2、推荐的估算方案】",
        "【3、估算推理过程】",
        "【4、建议采用的开度估算档位】",
        "【5、优先推荐方案的原因】",
        "【6、现场调度步骤】",
        "【7、最终估算结论】",
    ):
            self.assertIn(section, output)


    def test_exact_calculation_still_uses_supplied_parameters(self):
        calculation = calculate_gate_opening_scenarios(
            target_flow=300,
            flow_coefficient=0.65,
            gate_width=35,
            head=1.5,
            gate_height=5,
    )

        self.assertEqual(calculation["mode"], "calculated")
        self.assertEqual(calculation["parameters"]["gate_width"], 35)
        self.assertGreater(calculation["scenarios"]["目标"]["opening"], 0)


    def test_common_overflow_wording_extracts_300_cubic_meter_target(self):
        from intent_api_server import extract_gate_plan_parameters

        params = extract_gate_plan_parameters("现在过流 300m³/s，请给我推广闸门调度方案")

        self.assertEqual(params["target_flow"], 300)
        self.assertIsNone(params["gate_width"])
        self.assertIsNone(params["head"])

    def test_gate_plan_route_does_not_require_monitoring_database(self):
        import ast

        source = Path(__file__).parent / "main/xiaozhi-server/core/handle/intentHandler.py"
        tree = ast.parse(source.read_text())
        handle = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_user_intent"
        )
        gate_if = next(
            node for node in handle.body
            if isinstance(node, ast.If)
            and any(
                isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_is_gate_opening_plan_query"
                for n in ast.walk(node.test)
            )
        )
        assert "_chaobaihe_db_engine" not in ast.unparse(gate_if.test)

    def test_gate_plan_query_detects_common_dispatch_wording(self):
        from intent_api_server import is_gate_opening_plan_query

        self.assertTrue(is_gate_opening_plan_query("现在过流 300m³/s，请给我推广闸门调度方案"))
        self.assertTrue(is_gate_opening_plan_query("兴各庄闸开度方案"))
        self.assertFalse(is_gate_opening_plan_query("查询当前水位"))

    def test_monitoring_context_marks_sample_records_as_generic(self):
        from intent_api_server import DataQueryEngine, build_gate_dispatch_monitoring_context

        engine = DataQueryEngine(str(Path(__file__).parent / "data/monitoring_standard.sql"))
        context = build_gate_dispatch_monitoring_context(engine)

        self.assertEqual(context["data_scope"], "generic_monitoring_data")
        self.assertIn("9孔当前开度", context["missing_data"])
        self.assertIn("闸门设备状态", context["missing_data"])
        self.assertTrue(context["latest_records"])

    def test_llm_gate_prompt_requires_sections_and_manual_review(self):
        from intent_api_server import (
            build_gate_dispatch_monitoring_context,
            build_llm_gate_dispatch_prompt,
        )

        context = {
            "data_scope": "generic_monitoring_data",
            "latest_records": [],
            "missing_data": ["上游/下游明确点位水位"],
        }
        system_prompt, user_prompt = build_llm_gate_dispatch_prompt(
            "现在过流 300m³/s，请给我推广闸门调度方案",
            {"target_flow": 300},
            context,
        )

        self.assertIn("【1、已知条件和数据】", system_prompt)
        self.assertIn("【7、最终估算结论】", system_prompt)
        self.assertIn("需人工复核", system_prompt)
        self.assertIn("不得虚构", system_prompt)
        self.assertIn("generic_monitoring_data", user_prompt)

    def test_llm_empty_response_raises_visible_error(self):
        from unittest.mock import patch
        from intent_api_server import call_llm_sync

        class Response:
            status_code = 200

            def json(self):
                return {
                    "choices": [{
                        "message": {"content": "", "reasoning_content": "内部推理，不可展示"},
                    }],
                }

        with patch("intent_api_server._post_llm_with_retry", return_value=Response()):
            with self.assertRaisesRegex(RuntimeError, "未生成可展示文本"):
                call_llm_sync("system", "user")
