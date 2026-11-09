"""Measure actual Manim leaves without treating a moving assembly as one piece."""
from manim import Scene, VGroup, Rectangle, Line, tempconfig
from src.scene_design import system_contract as system
from src.scene_design.manim_kit import track
from src.scene_design.scene_telemetry import LayoutTelemetry
from tests.system_contract_support import visual_plan


def scene_fixture(tmp_path):
    plan=visual_plan()
    scene=Scene()
    scene.system_contract=system.load()
    scene.layout_plan=plan
    left=Rectangle(width=.6,height=.6,fill_opacity=1).shift([-1,0,0])
    right=Rectangle(width=.6,height=.6,fill_opacity=1).shift([1,0,0])
    seam=Line([-1,-.5,0],[1,-.5,0],stroke_width=2)
    group=track(scene,"point",VGroup(left,right,seam),kind="shape",layout_role="focal")
    scene.add(group)
    return scene,left,right,seam,LayoutTelemetry(scene,30)


def test_separate_rigid_translations_and_stretched_grid_are_not_material_deformation(tmp_path):
    with tempconfig(dict(media_dir=str(tmp_path),frame_width=9,frame_height=16)):
        scene,left,right,seam,t=scene_fixture(tmp_path)
        t.capture()
        left.shift([-.5,0,0])
        right.shift([.5,0,0])
        seam.stretch(1.4,0)
        t.frame=1
        t.capture()
        assert not any(i.get("code")=="RIGID_PIECE_CHANGED" for i in t.issues)
        snapshot=t.snapshot()["point"]
        assert len(snapshot["rigid_parts"])==2
        assert any("verify which paths" in c["problem"] for c in t.candidates)


def test_actual_material_stretch_is_detected_and_reports_one_piece(tmp_path):
    with tempconfig(dict(media_dir=str(tmp_path),frame_width=9,frame_height=16)):
        scene,left,right,seam,t=scene_fixture(tmp_path)
        t.capture()
        left.stretch(1.4,0)
        t.frame=1
        t.capture()
        errors=[i for i in t.issues if i.get("code")=="RIGID_PIECE_CHANGED"]
        assert len(errors)==1
        assert "part_" in errors[0]["problem"]


def test_missing_material_does_not_claim_its_rigidity(tmp_path):
    with tempconfig(dict(media_dir=str(tmp_path),frame_width=9,frame_height=16)):
        scene,left,right,seam,t=scene_fixture(tmp_path)
        t.capture()
        left.set_opacity(0)
        t.frame=1
        t.capture()
        assert any("membership changed" in c["problem"] for c in t.candidates)
