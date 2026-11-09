"""Hash-bound implementation plans for later scenes, separate from frame evidence."""
from pathlib import Path

from src.shared import _workflow_store as store
from src.shared.ai_utils import response_text
from src.idea.content import parse_object
from src.scene_design import system_contract as system


def references(root, jobs, script, script_sha256, bundle, config):
    """Use the first construction and nearest available predecessor, even after a render failure."""
    from src.scene_design.scene_code_pipeline import validate_plan
    result = {}
    scenes = {s['scene_id']: s for s in script['scenes']}
    for job in reversed(jobs):
        inputs = job.get('input', {})
        sid = inputs.get('scene_id')
        if (sid not in scenes or sid in result or job.get('status') == 'cancelled'
                or inputs.get('stage') != 'scene_design'
                or inputs.get('script_sha256') != script_sha256
                or inputs.get('config') != config
                or inputs.get('contract_sha256') != bundle['sha256']):
            continue
        directory = store.project_path(root, 'generation/checkpoint_5/' + job['job_id'])
        for path in sorted(directory.glob('round_*/storyboard.json'), reverse=True):
            try:
                plan = store.read_json(path)
                validate_plan(plan, dict(script=script, scene=scenes[sid],
                    target_seconds=plan['duration'], system_contract=bundle))
                # A plan file is eligible only if an intact completed model response
                # establishes its provenance, including rounds reusing an earlier plan.
                response_path = None
                for call in reversed(job.get('calls', [])):
                    if call.get('status') != 'complete' or not call['phase'].startswith('v3_plan_'):
                        continue
                    candidate = directory/'calls'/(call['call_id'] + '.json')
                    if call.get('response_sha256') != store.digest(candidate):
                        continue
                    response_plan=parse_object(response_text(store.read_json(candidate)))
                    if plan.get('planning_policy_version'):
                        from src.scene_design.plan_validation import prepare
                        response_plan=prepare(response_plan,dict(script=script,scene=scenes[sid],
                            target_seconds=plan['duration'],system_contract=bundle))
                    if response_plan == plan:
                        response_path = candidate
                        break
                if response_path is None:
                    continue
                ref = dict(scene_id=sid, job_id=job['job_id'], status='implementation_only',
                    path=str(path.relative_to(root)), sha256=store.digest(path),
                    response_path=str(response_path.relative_to(root)),
                    response_sha256=store.digest(response_path), **system.reference(bundle))
                if plan.get('planning_policy_version'):
                    ref['prepared_plan_sha256']=ref['sha256']
                result[sid] = ref
                break
            except (OSError, KeyError, ValueError, store.WorkflowError):
                continue
    return result


def for_scene(refs, script, scene_id):
    prior = [refs[s['scene_id']] for s in script['scenes'][:
        next(i for i, s in enumerate(script['scenes']) if s['scene_id'] == scene_id)]
        if s['scene_id'] in refs]
    return [prior[0], prior[-1]] if len(prior) > 1 else prior


def load(root, refs, bundle):
    result = []
    for ref in refs:
        system.assert_reference(ref, bundle)
        for key, digest in [('path', 'sha256'), ('response_path', 'response_sha256')]:
            if store.digest(store.project_path(root, ref[key])) != ref[digest]:
                raise store.WorkflowError('ARTIFACT_CHANGED', 'Previous implementation plan changed')
        plan = store.read_json(store.project_path(root, ref['path']))
        system.assert_reference(plan, bundle)
        response = store.read_json(store.project_path(root, ref['response_path']))
        response_plan=parse_object(response_text(response))
        if plan.get('planning_policy_version'):
            # references() already verified the deterministic projection from raw
            # response to saved plan. Bind that verified projection separately.
            if ref.get('prepared_plan_sha256') != store.digest(store.project_path(root,ref['path'])):
                raise store.WorkflowError('ARTIFACT_CHANGED','Prepared plan projection changed')
        elif response_plan != plan:
            raise store.WorkflowError('ARTIFACT_CHANGED', 'Previous implementation plan content changed')
        if plan['scene_id'] != ref['scene_id']:
            raise store.WorkflowError('ARTIFACT_CHANGED', 'Previous implementation plan identity changed')
        result.append(dict(ref, visual_plan=plan))
    return result
