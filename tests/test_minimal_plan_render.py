"""Real Manim drafts, fake model calls; no subscription inference."""
import json
import pytest
from src.shared import _workflow_store as store
from tests.test_scene_code_pipeline import CodeRouter, SOURCE, run_pipeline, visual_plan


def test_hud_words_and_group_checkpoint_reach_safe_real_render(tmp_path):
    plan = visual_plan()
    plan["timeline"].append(dict(id="hud_pulse", object_ids=["title"], start=0, end=3,
        phase="counter", region="hud", operation="update", parameters="Shake or rotate for emphasis"))
    plan["groups"] = [dict(id="bar", members=["point"])]
    plan["geometry_checkpoints"] = [dict(object_id="bar", time=2.5,
        box=[.92, 1.08, -.08, .08], tolerance=.01)]
    (path, extra), session, context, vision = run_pipeline(tmp_path, CodeRouter(plan=plan), repairs=0)
    assert extra["quality_passed"]
    assert (path.parent / "round_00" / "draft.json").exists()
    assert any(call["phase"] == "v3_code_0" for call in session.job["calls"])
    assert len(vision.requests) == 1


def test_layout_error_is_reported_after_video_and_draft_exist(tmp_path):
    bad = SOURCE.replace(".move_to([0,5,0])", ".move_to([4.4,5,0])")
    with pytest.raises(store.WorkflowError, match="SCENE_QUALITY_FAILED"):
        run_pipeline(tmp_path, CodeRouter([bad]), repairs=0)
    work = tmp_path / "generation/direct/round_00"
    result = store.read_json(work / "result.json")
    assert result["draft_saved"]
    assert result["issues"]
    draft = store.read_json(work / "draft.json")
    assert (tmp_path / draft["reference"]["path"]).is_file()
    metadata = store.read_json(tmp_path / draft["reference"]["metadata_path"])
    assert metadata["status"] == "success"
    assert store.read_json(work / "motion_checks.json")["passed"] is False
    job = store.read_json(tmp_path / "generation/direct/job.json")
    assert job["draft"]["review"]["vision_status"] == "completed"
    assert job["draft"]["review"]["passed"] is False
    assert any(c["phase"] == "v3_visual_review_0" and c["status"] == "complete" for c in job["calls"])
    assert (work / "visual_review.json").exists()
    assert not store.read_json(work / "visual_review.json")["passed"]


def test_metadata_quality_error_is_deferred_until_after_real_render(tmp_path):
    plan = visual_plan()
    plan["hud_region"] = []
    with pytest.raises(store.WorkflowError, match="SCENE_QUALITY_FAILED"):
        run_pipeline(tmp_path, CodeRouter(plan=plan), repairs=0)
    work = tmp_path / "generation/direct/round_00"
    result = store.read_json(work / "result.json")
    assert any(issue["code"] == "HUD_METADATA" for issue in result["issues"])
    assert (work / "draft.json").is_file()
    assert store.read_json(work / "code_render.json")["status"] == "success"



def test_reveal_issue_from_visual_reviewer_keeps_draft_unpassed(tmp_path):
    from unittest.mock import patch
    from tests.scene_v2_support import VisionRouter
    issue=dict(category="meaning",beat_id="approach",object_ids=["point"],time=1.5,
        problem="A loss band is visible before the approved reveal.",
        fix="Preserve the approved reveal order.")
    vision=VisionRouter([[issue]])
    with patch("tests.test_scene_code_pipeline.VisionRouter", return_value=vision):
        (path, extra), session, context, _ = run_pipeline(tmp_path, repairs=0)
    assert extra["quality_passed"] is False
    quality=store.read_json(path.parent/"quality.json")
    assert quality["passed"] is False
    assert quality["issues"][0]["problem"] == issue["problem"]
    assert (path.parent/"round_00"/"draft.json").is_file()
    assert "loss band" in vision.requests[0]["messages"][0]["content"]
    assert "approved visual_handoff" in vision.requests[0]["messages"][0]["content"]



def test_invalid_visual_review_keeps_automatic_warnings_and_draft(tmp_path):
    from unittest.mock import patch
    bad = SOURCE.replace(".move_to([0,5,0])", ".move_to([4.4,5,0])")
    with patch("src.scene_design.scene_pipeline._review",
               side_effect=store.WorkflowError("INVALID_VISUAL_REVIEW", "bad reviewer output")):
        with pytest.raises(store.WorkflowError, match="SCENE_QUALITY_FAILED"):
            run_pipeline(tmp_path, CodeRouter([bad]), repairs=0)
    work = tmp_path / "generation/direct/round_00"
    result = store.read_json(work / "result.json")
    assert result["draft_saved"]
    assert any(issue.get("code") == "HUD_ANCHOR" for issue in result["issues"])
    assert any(issue.get("owner") == "vision_reviewer" for issue in result["issues"])
    assert (work / "draft.json").exists()
