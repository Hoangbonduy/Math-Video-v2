"""Read the approved idea visual handoff without inventing legacy state."""

import copy
import re

from src.idea.content import GLOBAL_VISUALS_SCHEMA, check_schema
from src.idea.visuals import scene_sections, validate_visuals, timeline_cells, _field
from src.shared._workflow_store import WorkflowError

VERSION = 2
INSTRUCTIONS = (
    ' APPROVED VISUAL HANDOFF: visual_handoff contains the approved global declarations '
    'and the three-part visual brief for this scene. Follow global_visuals for object identities, '
    'construction, counts, dimensions, initial state, layout/style, coordinates/units, math and invariants. '
    'Initialize s1 from those declarations; later scenes start from previous_scene.end_state and '
    'scene.inherited. Apply only scene.changes; a replay/reset must be explicitly declared there. '
    'These are approved intended states, not measurements of a previously rendered clip. '
    'Map every scene.timeline event to this scene in order: cue, target, action with parameters/destination, '
    'verbatim on-screen text and simultaneous emphasis, then result. '
    'Times are LOCAL seconds starting at zero, never offsets from the entire video. '
    'Resolve narration/event cues within [0,target_seconds]; preserve order and reveal timing. '
    'Keep narration and target duration immutable; report conflicting requirements rather than dropping them. '
    'End at scene.end_state. Python copies scene.acceptance_criteria and generates initial/end/continuity '
    'checks after planning. Code generation and visual review must preserve all approved criteria. '
    'If contract_binding is present, its active contract_version/contract_sha256 identifies the job snapshot. '
    'script_authoring_reference is historical provenance of the approved script, not a requirement to run that old snapshot. '
    'Do not report a contract conflict merely because those two metadata references differ. '
    'All actual content/geometry/timing/reveal requirements still apply and must be checked against the active snapshot. '
    'Presentation coordinates may be mapped into renderer coordinates while preserving the declared '
    'mathematical dimensions and relationships. Keep required captions/numbers verbatim.'
)


def visual_handoff(script, scene_id):
    if 'global_visuals' not in script:
        return None
    check_schema(script['global_visuals'], GLOBAL_VISUALS_SCHEMA, 'global_visuals')
    validate_visuals(script)
    scenes = script['scenes']
    index = next((i for i, scene in enumerate(scenes) if scene['scene_id'] == scene_id), None)
    if index is None:
        raise WorkflowError('INVALID_SCRIPT', 'Không tìm thấy cảnh trong khai báo hình ảnh: ' + scene_id)
    inheritance, timeline, criteria = scene_sections(scenes[index]['visual_intent'])
    events = []
    for line in timeline.splitlines():
        if not line.strip() or line.startswith('Kết cảnh:'):
            continue
        cells = timeline_cells(line)
        events.append(dict(zip(('cue', 'target', 'action', 'text_and_emphasis', 'result'), cells)))
    previous = None
    if index:
        previous_timeline = scene_sections(scenes[index - 1]['visual_intent'])[1]
        previous = dict(scene_id=scenes[index - 1]['scene_id'],
                        end_state=_field(previous_timeline, 'Kết cảnh'))
    return dict(schema_version=VERSION, global_visuals=copy.deepcopy(script['global_visuals']),
                previous_scene=previous,
                scene=dict(scene_id=scene_id, inherited=_field(inheritance, 'Kế thừa'),
                           changes=_field(inheritance, 'Thay đổi'), timeline=events,
                           end_state=_field(timeline, 'Kết cảnh'),
                           acceptance_criteria=[line[2:].strip() for line in criteria.splitlines()
                                                if line.startswith('- ')]))


# A legacy Slicer wrote this descriptive authoring stamp into creative prose.
# Only this exact leading stamp is metadata; never strip arbitrary hashes or
# explicit requirements elsewhere in approved content.
_AUTHORING_STAMP = re.compile(
    r"^\s*Hợp đồng phiên bản\s+(?P<version>\d+\.\d+\.\d+)\s*,\s*"
    r"SHA-256\s+(?P<sha256>[0-9a-fA-F]{64})\.\s*")


def bind_execution_contract(handoff, bundle):
    """Project legacy authoring metadata without changing approved content."""
    if handoff is None:
        return None
    from src.scene_design import system_contract as system
    system.verify(bundle)
    result=copy.deepcopy(handoff)
    binding=result.get('contract_binding')
    if binding is not None:
        # A projection belongs to one job snapshot. Reusing it under a different
        # snapshot is still a real mismatch; fresh jobs start from approved source.
        system.assert_reference(binding,bundle)
        return result
    continuity=result.get('global_visuals',{}).get('continuity','')
    stamp=_AUTHORING_STAMP.match(continuity)
    if stamp:
        result['global_visuals']['continuity']=continuity[stamp.end():]
        result['contract_binding']=dict(
            **system.reference(bundle),policy='job_snapshot_authoritative',
            script_authoring_reference=dict(contract_version=stamp['version'],
                contract_sha256=stamp['sha256'].lower()),
            source_field='script.global_visuals.continuity',
            scope='Only the leading authoring stamp is provenance; all remaining approved requirements are unchanged')
    return result


def with_visual_handoff(context):
    script = context.get('script') or {}
    if 'global_visuals' in script:
        handoff=visual_handoff(script,context['scene']['scene_id'])
        existing=context.get('visual_handoff') or {}
        if 'contract_binding' in existing and not _AUTHORING_STAMP.match(script['global_visuals']['continuity']):
            handoff['contract_binding']=copy.deepcopy(existing['contract_binding'])
    else:
        handoff=context.get('visual_handoff')
    if handoff is None:
        return context
    bundle=context.get('system_contract')
    if bundle:
        handoff=bind_execution_contract(handoff,bundle)
        if 'global_visuals' in script and handoff['global_visuals']!=script['global_visuals']:
            script=copy.deepcopy(script)
            script['global_visuals']=copy.deepcopy(handoff['global_visuals'])
            return dict(context,script=script,visual_handoff=handoff)
    return dict(context,visual_handoff=handoff)


def messages(instruction, context):
    context = with_visual_handoff(context)
    if context.get('visual_handoff'):
        instruction += INSTRUCTIONS
    return instruction, context


def validate_plan_criteria(plan, context):
    handoff = with_visual_handoff(context).get('visual_handoff')
    if handoff:
        actual = {criterion for beat in plan['beats'] for criterion in beat['criteria']}
        missing = set(handoff['scene']['acceptance_criteria']) - actual
        if missing:
            raise WorkflowError('INVALID_SCENE_DESIGN',
                                'Storyboard bỏ tiêu chí hình ảnh đã duyệt: ' + '; '.join(sorted(missing)))
    return plan
