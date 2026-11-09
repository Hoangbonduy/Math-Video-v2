"""Contract-bound fake plans; no API calls or video rendering."""
import copy
from src.scene_design import system_contract as system


def bind_plan(plan, hud_ids=()):
    plan = copy.deepcopy(plan)
    duration = plan['duration']
    for obj in plan['objects']:
        kind = obj.pop('role', obj.get('kind', 'shape'))
        hud = obj['id'] in hud_ids
        obj.update(kind=kind, layout_role='hud' if hud else 'focal',
            anchor=[0,5] if hud else [],
            observation_intervals=[] if hud else [dict(start=0,end=duration)])
    plan.update(system.reference(system.load()), contract_conflict=False, conflict_reason='', hud_region=[-3.95,3.95,4,7.45] if hud_ids else [],
        geometry_checkpoints=[],reveal_checks=[],groups=[], timeline=[dict(id='motion',object_ids=[o['id'] for o in plan['objects'] if o['id'] not in hud_ids],
            start=0,end=duration,phase='geometry',region='center',operation='move',parameters='Approved rigid motion')],
        crop_intervals=[], intentional_overlaps=[], math_mode='strict',
        illusion_spec=dict(object_ids=[],start=0,end=0,expected_discrepancy='',preserved_invariants=[],reveal_policy='',approval_quote=''))
    first=plan['beats'][0]
    initial='Initial state matches the approved inherited state.'
    if initial not in first['criteria']:
        first['criteria'].append(initial)
    plan['criterion_rules']=[dict(beat_id=b['id'],criterion=c,
        check='initial_state' if c==initial else 'content',condition='always')
        for b in plan['beats'] for c in b['criteria']]
    return plan


def visual_plan():
    return bind_plan(dict(scene_id='s1',narration='A point moves.',duration=3,
        goal='Track a point',visual_strategy='Fixed title, moving point',
        beats=[dict(id='beat_01',start=0,end=3,narration_excerpt='A point moves.',
            show='Title and point',motion='Point slides',understand='Track displacement',
            criteria=['Point moves right while remaining visible.'],required_capabilities=[])],
        objects=[dict(id='title',role='text'),dict(id='point',role='shape')],
        recipe_ids=['explanatory_motion'],required_apis=['Dot','Text']),hud_ids=['title'])


def add_continuity(plan):
    criterion='Rendered previous last frame matches current first frame.'
    beat=plan['beats'][0]
    beat['criteria'].append(criterion)
    plan['criterion_rules'].append(dict(beat_id=beat['id'],criterion=criterion,
        check='cross_scene_continuity',condition='verified_previous_frame'))
    return plan
