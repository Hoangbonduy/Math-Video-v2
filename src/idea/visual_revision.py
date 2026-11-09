"""Stage a local visual-only script revision; never approve or call a model."""
import copy
import hashlib
import json
from pathlib import Path

from src.shared import _workflow_store as store,workflow as wf
from src.shared._workflow_store import WorkflowError
from src.shared.job_session import _job_lock
from src.idea.content import VISUAL_SCRIPT_SCHEMA,check_schema,validate_script,markdown
from src.idea.narration import validate_editorial
from src.idea.visuals import validate_visuals,require_visual_readiness


def stage(project_dir,candidate,expected_sha256):
    """Create a pending version while preserving every approved spoken character."""
    root=Path(project_dir).resolve()
    with _job_lock(root),store.locked_project(root):
        project,reviews=wf._load(root)
        if project['stage'] not in ('script','scene_design'):
            raise WorkflowError('WRONG_STAGE','Visual revision requires script or scene_design stage')
        base=wf._latest(project,'script',None)
        if not base:
            raise WorkflowError('STRUCTURED_SCRIPT_REQUIRED','No structured script to revise')
        wf._verify(root,base)
        payload=store.read_json(store.project_path(root,base['bundle']['script.json']['path']))
        if base['sha256']!=expected_sha256:
            if (base.get('revision_base_sha256')==expected_sha256
                    and payload['script']==candidate and base.get('revision_origin')=='local_visual_repair'):
                return dict(version=base['version'],sha256=base['sha256'],status='pending')
            raise WorkflowError('STALE_REVIEW','The current script has changed')
        original=payload['script']
        for field in ('title','main_idea','claims'):
            if candidate.get(field)!=original.get(field):
                raise WorkflowError('VISUAL_REVISION_SCOPE','Visual repair cannot change '+field)
        old=[(s['scene_id'],s['narration'],s['claim_refs']) for s in original['scenes']]
        new=[(s['scene_id'],s['narration'],s['claim_refs']) for s in candidate.get('scenes',[])]
        if new!=old:
            raise WorkflowError('VISUAL_REVISION_SCOPE','Keep scene IDs, narration and claim references exactly')
        check_schema(candidate,VISUAL_SCRIPT_SCHEMA)
        validate_visuals(candidate)
        require_visual_readiness(candidate)
        research=store.read_json(store.project_path(root,base['bundle']['research.json']['path']))
        brief=payload.get('brief',project.get('brief',{}))
        duration=validate_script(candidate,research['sources'],brief)
        validate_editorial(candidate,' '.join(s['narration'] for s in original['scenes']),brief)
        for artifact in project['artifacts']:
            if artifact['stage']!='script' and not artifact.get('invalidated'):
                raise WorkflowError('VISUAL_REVISION_SCOPE',
                    'Existing downstream artifacts need an explicit revision workflow; none will be invalidated silently')
        version=wf._next_version(project,'script',None)
        checksum=hashlib.sha256(json.dumps(candidate,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        relative='generation/visual_revision_'+version+'_'+checksum[:16]
        directory=store.project_path(root,relative)
        directory.mkdir(parents=True,exist_ok=True)
        revised=copy.deepcopy(payload)
        revised['script']=copy.deepcopy(candidate)
        revised['duration_estimate']=duration
        def materialize(name,value):
            data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
            store.materialize(directory,name,content=data)
            path=directory/name
            return dict(path=str(path.relative_to(root)),sha256=store.digest(path))
        script_ref=materialize('script.json',revised)
        generation_ref=materialize('generation.json',dict(
            origin='local_visual_repair',base_version=base['version'],base_sha256=base['sha256'],
            calls=[],model=None,billing_source='not_applicable',narration_changed=False))
        source=directory/'script.md'
        store.materialize(directory,source.name,
            content=markdown(candidate,research['sources'],duration).encode())
        project['stage']='script'
        wf._submit(root,project,reviews,'script',version,source,None,
                   [s['scene_id'] for s in candidate['scenes']])
        artifact=wf._latest(project,'script',None)
        # The original narration remains AI-authored; retain the existing read-
        # duration approval gate while recording the local origin of this revision.
        artifact.update(origin=base.get('origin','ai'),revision_origin='local_visual_repair',
            revision_base_sha256=base['sha256'],revision_base_version=base['version'],
            duration_estimate=duration,job_id=directory.name,
            bundle={'script.json':script_ref,
                    'research.json':copy.deepcopy(base['bundle']['research.json']),
                    'generation.json':generation_ref})
        wf._save(root,project,reviews)
        return dict(version=version,sha256=artifact['sha256'],status='pending',
                    path=str(root/artifact['path']))
