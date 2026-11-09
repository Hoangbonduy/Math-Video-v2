"""Regression checks for the three-group planning policy."""
import copy
import unittest
from src.scene_design import plan_validation as gate, system_contract as system
from src.scene_design import scene_code_pipeline as pipeline
from src.shared._workflow_store import WorkflowError
from tests.system_contract_support import visual_plan


class MinimalPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = visual_plan()
        self.context = dict(scene=dict(scene_id=self.plan["scene_id"], narration=self.plan["narration"]),
            target_seconds=self.plan["duration"], system_contract=system.load())

    def rejected(self, plan, context=None):
        with self.assertRaises(WorkflowError):
            pipeline.validate_plan(plan, context or self.context)

    def test_three_groups_keep_invalid_input_blocked(self):
        for field, value in [("scene_id", "wrong"), ("narration", "changed"), ("duration", 9),
                             ("contract_sha256", "0" * 64), ("contract_conflict", True)]:
            plan = copy.deepcopy(self.plan)
            plan[field] = value
            self.rejected(plan)
        for update in [dict(required_apis=["os.system"]), dict(recipe_ids=["missing"]),
                       dict(objects=self.plan["objects"] * 2)]:
            self.rejected(dict(self.plan, **update))
        for key, value in [("object_ids", ["undefined"]), ("end", 30)]:
            plan = copy.deepcopy(self.plan)
            plan["timeline"][0][key] = value
            self.rejected(plan)
        self.rejected(dict(self.plan, beats=None))

    def test_minimal_schema_asks_neither_boxes_nor_review_metadata(self):
        schema = gate.planner_schema(system.load())
        for key in ("geometry_checkpoints", "reveal_checks", "illusion_spec", "criterion_rules"):
            self.assertNotIn(key, schema["properties"])
        beat = schema["properties"]["beats"]["items"]["properties"]
        self.assertNotIn("criteria", beat)
        self.assertNotIn("required_capabilities", beat)

    def test_python_copies_approved_criteria_and_generates_complete_rules(self):
        plan = copy.deepcopy(self.plan)
        for key in ("geometry_checkpoints", "reveal_checks", "criterion_rules", "illusion_spec"):
            plan.pop(key)
        for beat in plan["beats"]:
            beat.pop("criteria")
            beat.pop("required_capabilities")
        context = dict(self.context, visual_handoff=dict(previous_scene=dict(scene_id="previous"),
            scene=dict(acceptance_criteria=["Approved requirement A.", "Approved requirement B."])))
        original = copy.deepcopy(plan)
        result = gate.prepare(plan, context)
        self.assertEqual(plan, original)
        criteria = {c for b in result["beats"] for c in b["criteria"]}
        self.assertTrue({"Approved requirement A.", "Approved requirement B.",
            gate.INITIAL, gate.END, gate.CONTINUITY} <= criteria)
        pairs = [(b["id"], c) for b in result["beats"] for c in b["criteria"]]
        rules = result["criterion_rules"]
        self.assertCountEqual(pairs, [(r["beat_id"], r["criterion"]) for r in rules])
        self.assertEqual(next(r for r in rules if r["criterion"] == gate.CONTINUITY)["condition"],
                         "verified_previous_frame")

    def test_hud_prose_and_layout_metadata_are_not_planning_gates(self):
        plan = copy.deepcopy(self.plan)
        plan["objects"][0]["anchor"] = [100, 100]
        plan["hud_region"] = []
        plan["timeline"][0].update(object_ids=["title"], parameters="Shake and rotate the HUD")
        plan["reveal_checks"] = [dict(policy_quote="not copied", visible_steps="", withheld_information="", status="conflict")]
        pipeline.validate_plan(plan, self.context)
        prepared = gate.prepare(plan, self.context)
        findings = gate.post_render_checks(prepared, system.load())
        self.assertTrue(any(issue["code"] == "HUD_METADATA" for issue in findings))

    def test_group_checkpoint_is_allowed_and_no_box_semantics_block_plan(self):
        plan = copy.deepcopy(self.plan)
        plan["groups"] = [dict(id="bar", members=["point"])]
        plan["geometry_checkpoints"] = [dict(object_id="bar", time=2.5, box=[4, -4, 2, -2], tolerance=2)]
        pipeline.validate_plan(plan, self.context)
        self.assertTrue(gate.post_render_checks(gate.prepare(plan, self.context), system.load()))


    def test_bad_ai_rule_mapping_is_replaced_instead_of_blocking(self):
        plan = copy.deepcopy(self.plan)
        plan["criterion_rules"] = [{"malformed": "AI mapping is not authoritative"}]
        result = gate.prepare(plan, self.context)
        self.assertTrue(result["criterion_rules"])
        self.assertTrue(all("beat_id" in row for row in result["criterion_rules"]))

    def test_prepared_plan_remains_a_verifiable_implementation_reference(self):
        import json
        import tempfile
        from pathlib import Path
        from src.shared import _workflow_store as store
        from src.scene_design import scene_plan_handoff
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "generation/checkpoint_5/job"
            (directory / "round_00").mkdir(parents=True)
            (directory / "calls").mkdir()
            script = dict(scenes=[self.context["scene"]])
            prepared = gate.prepare(self.plan, dict(self.context, script=script))
            store.atomic_write(directory / "round_00/storyboard.json", prepared)
            from src.shared.ai_config import get_model
            response = dict(model=get_model(), choices=[dict(message=dict(content=json.dumps(self.plan)))])
            response_path = directory / "calls/response.json"
            store.atomic_write(response_path, response)
            bundle = system.load()
            job = dict(job_id="job", status="complete",
                input=dict(scene_id=self.plan["scene_id"], stage="scene_design",
                    script_sha256="approved", config={}, contract_sha256=bundle["sha256"]),
                calls=[dict(call_id="response", phase="v3_plan_0", status="complete",
                    response_sha256=store.digest(response_path))])
            refs = scene_plan_handoff.references(root, [job], script, "approved", bundle, {})
            self.assertIn(self.plan["scene_id"], refs)
            loaded = scene_plan_handoff.load(root, list(refs.values()), bundle)
            self.assertEqual(loaded[0]["visual_plan"], prepared)


    def test_non_hud_initial_coordinates_are_not_quality_errors(self):
        plan = copy.deepcopy(self.plan)
        point = next(o for o in plan["objects"] if o["id"] == "point")
        point["anchor"] = [1.5, -1.2]
        prepared = gate.prepare(plan, self.context)
        findings = gate.post_render_checks(prepared, system.load())
        self.assertFalse(any(issue["code"] == "NON_HUD_ANCHOR" for issue in findings))


if __name__ == "__main__":
    unittest.main()
