"""Small data checks for the planner/code handoff; visual judgment follows render."""
import copy
from src.idea.content import _object
from src.scene_design import scene_contract as data, scene_references

S,N=data.S,data.N
BEAT=_object(dict(id=data.IDENTIFIER,start=N,end=N,narration_excerpt=S,show=S,motion=S,
    understand=S,criteria=data.array(S,1,8)))
PLAN_SCHEMA=_object(dict(scene_id=S,narration=S,duration=N,goal=S,visual_strategy=S,
    beats=data.array(BEAT,1,8),
    objects=data.array(_object(dict(id=data.IDENTIFIER,
        kind=data.enum('text','formula','shape','background'))),1,60),
    groups=data.array(_object(dict(id=data.IDENTIFIER,members=data.array(S,1,60))),0,20),
    required_apis=data.array(S,1,16),recipe_ids=data.array(data.enum(*scene_references.RECIPES),1,5)))


def planner_schema():
    return copy.deepcopy(PLAN_SCHEMA)


def validate(plan,context):
    data.structure(plan,PLAN_SCHEMA,'visual_plan')
    if (plan['scene_id']!=context['scene']['scene_id']
        or plan['narration']!=context['scene']['narration']
        or abs(plan['duration']-context['target_seconds'])>1e-6):
        data.fail('Keep the approved scene, narration and duration')
    if plan['duration']<=0:data.fail('Duration must be positive')
    ids=[o['id'] for o in plan['objects']]+[g['id'] for g in plan['groups']]
    beats=[b['id'] for b in plan['beats']]
    if len(set(ids))!=len(ids) or len(set(beats))!=len(beats):
        data.fail('Object, group and beat IDs must be unique')
    objects={o['id'] for o in plan['objects']}
    for group in plan['groups']:
        if not set(group['members'])<=objects:data.fail('Unknown group member')
    for beat in plan['beats']:
        if not 0<=beat['start']<beat['end']<=plan['duration']+1e-6:
            data.fail('Beat time is outside the scene')
    parts=' '.join(b['narration_excerpt'] for b in plan['beats'])
    if ' '.join(parts.split())!=' '.join(plan['narration'].split()):
        data.fail('Beat excerpts must preserve approved narration')
    scene_references.validate_request(plan['required_apis'],plan['recipe_ids'])
    return plan


def prepare(plan,context):
    validate(plan,context)
    result=copy.deepcopy(plan)
    from src.scene_design.script_visuals import with_visual_handoff
    handoff=with_visual_handoff(context).get('visual_handoff')
    if handoff:
        beat=result['beats'][-1]
        beat['criteria']=list(dict.fromkeys(beat['criteria']+handoff['scene']['acceptance_criteria']))
    return result
