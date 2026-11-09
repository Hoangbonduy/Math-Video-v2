"""Data handoff checks only; no visual-policy verdict before code."""
import copy
import pytest
from src.scene_design import plan_validation as gate
from src.shared._workflow_store import WorkflowError
from tests.test_scene_code_pipeline import visual_plan

def context():
    p=visual_plan()
    return dict(scene=dict(scene_id=p['scene_id'],narration=p['narration']),target_seconds=p['duration'])

def test_minimal_plan_has_no_execution_policy():
    plan=gate.prepare(visual_plan(),context())
    assert gate.validate(plan,context())==plan
    assert set(plan)==set(gate.PLAN_SCHEMA['properties'])
    assert 'conflict_reason' not in plan and 'geometry_checkpoints' not in plan

@pytest.mark.parametrize('change',[
    lambda p:p.update(duration=2),
    lambda p:p['objects'].append(copy.deepcopy(p['objects'][0])),
    lambda p:p['groups'].append(dict(id='assembly',members=['missing'])),
    lambda p:p['beats'][0].update(end=20)])
def test_broken_handoff_is_rejected(change):
    plan=visual_plan();change(plan)
    with pytest.raises(WorkflowError):gate.validate(plan,context())

def test_uncertainty_is_ordinary_plan_text():
    plan=visual_plan();plan['visual_strategy']='Uncertain cutting geometry; try a construction and inspect the rendered draft.'
    assert gate.prepare(plan,context())['visual_strategy']==plan['visual_strategy']
