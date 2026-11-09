"""Inspectable rendered drafts and recovery into pending human review."""
from pathlib import Path
from src.shared import _workflow_store as store
from src.shared._workflow_store import WorkflowError


def publish(root, work, session, reference, *, evidence_work=None):
    root,work=Path(root),Path(work)
    evidence_work=Path(evidence_work or work)
    checks=store.read_json(evidence_work/'render_checks.json')
    motion=store.read_json(evidence_work/'motion_checks.json')
    design=store.read_json(work/'design.json')
    deferred=bool(design.get('layout_plan',{}).get('planning_policy_version'))
    if not checks['passed'] or (not motion['passed'] and not deferred):
        raise WorkflowError('DRAFT_INVALID','Bản nháp cần qua kiểm tra chuyển động và render.')
    for key,digest in [('path','sha256'),('code_path','code_sha256')]:
        if reference.get(digest) and store.digest(store.project_path(root,reference[key]))!=reference[digest]:
            raise WorkflowError('ARTIFACT_CHANGED','Video hoặc mã render đã thay đổi.')
    paths=[work/n for n in ('design.json','storyboard.json')]
    paths += [evidence_work/n for n in ('render_checks.json','motion_checks.json','evidence.json')]
    manifest=store.read_json(evidence_work/'evidence.json')
    if manifest.get('binding'):
        anchor=store.project_path(root,manifest['binding']['path'])
        paths.append(anchor)
        paths += [store.project_path(root,item['path']) for item in store.read_json(anchor)['artifacts']]
    paths += [store.project_path(root,item['path']) for item in manifest.get('frames',[])]
    paths += [store.project_path(root,reference[k]) for k in ('path','code_path','log_path','metadata_path')]
    paths += list(evidence_work.glob('contact_sheet*.jpg'))
    paths += [work/n for n in ('local_layout_changes.json','source.json') if (work/n).exists()]
    files=[dict(path=str(p.relative_to(root)),sha256=store.digest(p)) for p in paths]
    record=dict(job_id=session.job['job_id'],input=session.job.get('input',{}),reference=reference,files=files,
                design_path=str((work/'design.json').relative_to(root)),storyboard_path=str((work/'storyboard.json').relative_to(root)),
                render_checks_path=str((evidence_work/'render_checks.json').relative_to(root)),motion_checks_path=str((evidence_work/'motion_checks.json').relative_to(root)))
    path=evidence_work/'draft.json'
    if path.exists():
        if store.read_json(path)!=record:raise WorkflowError('CACHE_CORRUPT','Bằng chứng bản nháp đã thay đổi.')
    else:store.atomic_write(path,record)
    previous=session.job.get('draft',{})
    new=dict(path=str(path.relative_to(root)),sha256=store.digest(path),review=None)
    if previous.get('path')==new['path'] and previous.get('sha256')==new['sha256']:
        new['review']=previous.get('review')
    elif previous:
        history=session.job.setdefault('draft_history',[])
        if previous not in history:history.append(previous)
    session.job['draft']=new
    session.save()
    return record


def current(root):
    root=Path(root);project=store.read_json(root/'project.json')
    script=next((a for a in reversed(project['artifacts']) if a['stage']=='script' and not a.get('invalidated')),None)
    index=root/'generation/checkpoint_5/ledger.json'
    if not script or not index.exists():return {}
    from src.shared.ai_config import get_model,get_backend
    result={}
    for path in store.read_json(index)['jobs']:
        job=store.read_json(store.project_path(root,path));i=job['input'];ref=job.get('draft')
        if not ref or i.get('stage')!='scene_design' or i.get('script_sha256')!=script['sha256'] or i.get('model')!=get_model() or i.get('ai_backend')!=get_backend():continue
        try:
            record_path=store.project_path(root,ref['path'])
            if record_path.is_symlink() or store.digest(record_path)!=ref['sha256']:continue
            record=store.read_json(record_path)
            if record['job_id']!=job['job_id'] or record['input']!=i:continue
            result[i['scene_id']]=dict(record,record_path=ref['path'],record_sha256=ref['sha256'],job_path=path,review=ref.get('review'),status=job['status'])
        except (OSError,KeyError,WorkflowError):continue
    return result


def verify(root,draft):
    root=Path(root)
    for item in draft['files']:
        path=store.project_path(root,item['path'])
        if (any(part.is_symlink() for part in [path,*path.parents] if part.is_relative_to(root))
                or not path.is_file() or store.digest(path)!=item['sha256']):
            raise WorkflowError('ARTIFACT_CHANGED','Bằng chứng bản nháp đã thay đổi: '+item['path'])
    return draft


def media_files(root):
    allowed=set()
    for draft in current(root).values():
        try:verify(root,draft)
        except (OSError,WorkflowError):continue
        allowed.update(store.project_path(root,item['path']).resolve() for item in draft['files'])
        allowed.add(store.project_path(root,draft['record_path']).resolve())
    for evidence in failed_renders(root).values():
        try:verify(root,evidence)
        except (OSError,WorkflowError):continue
        allowed.update(store.project_path(root,item['path']).resolve() for item in evidence['files'])
    return allowed


def recover_rendered(root):
    """Attach existing valid renders after an upgrade, without model/TTS calls."""
    from types import SimpleNamespace
    from src.scene_design import scene_pipeline
    root=Path(root);index=root/'generation/checkpoint_5/ledger.json'
    if not index.exists():return
    for relative in store.read_json(index)['jobs']:
        path=store.project_path(root,relative);job=store.read_json(path)
        if job.get('draft') or job.get('status') in ('working','planned') or job['input'].get('stage')!='scene_design':continue
        directory=path.parent
        for work in sorted(directory.glob('round_*'),reverse=True):
            record_path=work/('code_render.json' if (work/'code_render.json').exists() else 'job.json')
            if not record_path.exists() or not (work/'render_checks.json').exists():continue
            saved_render=store.read_json(record_path)
            render=saved_render if record_path.name=='code_render.json' else saved_render.get('relation_render',{})
            if render.get('status')!='success':continue
            try:
                session=SimpleNamespace(job=job,save=lambda:store.atomic_write(path,job))
                evidence_work=work
                review_index=str(int(work.name.split('_')[-1]))
                if record_path.name=='code_render.json' and job.get('evidence_options'):
                    from src.scene_design.scene_evidence import fingerprint
                    design=store.read_json(work/'design.json')
                    request=dict(options=job['evidence_options'],requirements=design.get('evidence_requirements',[]),
                                 previous_scene_render=job['input'].get('previous_render'))
                    if store.read_json(work/'evidence_request.json')!=request:
                        evidence_work=work/'evidence_versions'/fingerprint(request)
                        review_index+='_evidence_'+fingerprint(request)
                publish(root,work,session,render['reference'],evidence_work=evidence_work)
                phase=('v3' if record_path.name=='code_render.json' else 'v2')+'_visual_review_'+review_index
                call=next((c for c in job['calls'] if c['phase']==phase and c['status']=='complete'),None)
                if call:
                    response_path=directory/'calls'/(call['call_id']+'.json')
                    if store.digest(response_path)!=call['response_sha256']:raise WorkflowError('CACHE_CORRUPT','Phản hồi đánh giá đã thay đổi.')
                    def cached_call(request_phase,*args,**kwargs):
                        if request_phase!=phase:raise WorkflowError('CACHE_CORRUPT','Sai bước đánh giá lưu sẵn.')
                        return store.read_json(response_path)
                    session.call=cached_call
                    review=scene_pipeline._review(root,session,None,store.read_json(work/'storyboard.json'),store.read_json(work/'design.json'),store.read_json(evidence_work/'evidence.json'),store.read_json(evidence_work/'render_checks.json'),review_index)
                    job['draft']['review']=dict(passed=review['passed'],summary=review['summary'],criteria_passed=sum(c['passed'] for c in review['criteria_results']),criteria_total=len(review['criteria_results']))
                    if not review['passed']:
                        job.setdefault('error_history',[]).append(dict(error=job.get('last_error'),reason='recovered_saved_visual_review'))
                        job['quality_issues']=review['issues']
                        job['last_error']='SCENE_QUALITY_FAILED: Đã dựng bản nháp; còn tiêu chí hình ảnh chưa đạt. Có thể xem video và chạy lại một lượt mới.'
                    session.save()
                break
            except (OSError,KeyError,ValueError,WorkflowError):
                # A missing/corrupt render remains unavailable; never infer quality.
                continue

    _register_reviewable(root)


def _register_reviewable(root):
    """Recover saved failed renders into pending reviews; no generation calls.

    Runs alongside recover_rendered under the caller's project access, just as
    the existing recovery writes do. Recheck the base before submitting.
    """
    from src.shared import workflow as wf
    from src.scene_design import scene_pipeline, scene_generation as sg
    root = Path(root)
    project, reviews = wf._load(root)
    if project['stage'] != 'scene_design':
        return
    drafts = current(root)
    if not drafts:
        return
    ledger_jobs=set(store.read_json(root/sg.BASE/'ledger.json')['jobs'])
    script = wf._latest(project, 'script', None)
    busy = {sid for revision in reviews.get('scene_revisions', [])
            if revision.get('status') not in ('completed', 'cancelled')
            for sid in revision.get('affected', [])}
    changed = False
    for sid, draft in drafts.items():
        if draft['status'] != 'failed' or sid not in project['scene_ids'] or sid in busy:
            continue
        inputs = draft['input']
        base = wf._latest(project, 'scene_design', sid)
        updating=bool(base and base.get('recovered_draft') and base.get('job_id')==draft['job_id']
            and base['version']==inputs['version'] and wf._request(reviews,base)['status']=='pending')
        if updating and base.get('recovered_draft_sha256')==draft['record_sha256']:
            continue
        if (inputs.get('script_version') != script['version']
                or not updating and (inputs.get('base_version') != (base['version'] if base else None)
                    or inputs.get('base_sha256') != (base['sha256'] if base else None))
                or inputs.get('config') != sg._config(root)):
            continue
        if base and not updating and wf._request(reviews, base)['status'] != 'changes_requested':
            continue
        if not updating and inputs.get('version') != wf._next_version(project, 'scene_design', sid):
            continue
        try:
            # current() binds this path to the verified job in the ledger.
            # Drafts may live arbitrarily deep under evidence_versions.
            if draft['job_path'] not in ledger_jobs:
                continue
            job_path=store.project_path(root,draft['job_path'])
            directory=job_path.parent
            if not store.project_path(root,draft['record_path']).is_relative_to(directory):
                raise WorkflowError('STALE_JOB','Draft is outside its ledger job')
            job = store.read_json(job_path)
            if job['input'] != inputs or job['job_id'] != draft['job_id']:
                continue
            candidate = scene_pipeline.reviewable_draft(root, directory, job)
            if not candidate:
                continue
            source, extra = candidate
            paths = [p for p in source.parent.iterdir() if p.is_file()]
            paths += [store.project_path(root, item['path']) for item in draft['files']]
            paths.append(root/'scene_config.json')
            assets = store.read_json(source.parent/'assets.json')
            for asset in assets['assets']:
                paths += [store.project_path(root, asset[k]) for k in ('path', 'evidence_path')]
            bundle = sg._bundle(root, paths)
            wf._submit(root, project, reviews, 'scene_design', inputs['version'], source, sid, None)
            artifact = wf._latest(project, 'scene_design', sid)
            artifact.update(origin='ai_scene', job_id=job['job_id'], recovered_draft=True, recovered_draft_sha256=draft['record_sha256'], bundle=bundle, **extra)
            rendered = extra['manim_render']
            reference = dict(rendered, render_version=rendered['version'], scene_id=sid,
                             version=inputs['version'], design_sha256=artifact['sha256'])
            project.setdefault('design_previews', {})[sid+':'+inputs['version']] = reference
            changed = True
        except (OSError, KeyError, ValueError, WorkflowError):
            # Do not turn a stale or incomplete render into an approvable version.
            continue
    if changed:
        wf._save(root, project, reviews)


def failed_renders(root):
    """Expose verified V3 failed render evidence without creating an artifact."""
    from src.shared.ai_config import get_model, get_backend
    root=Path(root)
    index=root/'generation/checkpoint_5/ledger.json'
    if not index.exists():
        return {}
    project=store.read_json(root/'project.json')
    script=next((a for a in reversed(project['artifacts'])
                 if a['stage']=='script' and not a.get('invalidated')),None)
    if not script:
        return {}
    result={}
    for relative in store.read_json(index)['jobs']:
        try:
            job_path=store.project_path(root,relative)
            job=store.read_json(job_path);inputs=job['input']
            if (inputs.get('stage')!='scene_design'
                    or inputs.get('script_sha256')!=script['sha256']
                    or inputs.get('model')!=get_model()
                    or inputs.get('ai_backend')!=get_backend()):
                continue
            # Latest matching job owns the scene even if it produced no evidence.
            sid=inputs['scene_id']
            result.pop(sid,None)
            for work in sorted(job_path.parent.glob('round_*'),reverse=True):
                saved=work/'code_render.json'
                if not saved.exists() or not (work/'motion_checks.json').exists():
                    continue
                record=store.read_json(saved)
                if record.get('status')!='success':
                    continue
                checks=store.read_json(work/'motion_checks.json')
                if checks.get('passed') is not False:
                    continue
                ref=record['reference']
                if any(ref.get(k)!=inputs.get(k) for k in ('contract_version','contract_sha256')):
                    continue
                paths=[work/n for n in ('code_render.json','motion_checks.json','render_checks.json',
                                       'design.json','storyboard.json','evidence.json')]
                if (work/'visual_review.json').exists():
                    paths.append(work/'visual_review.json')
                paths += [store.project_path(root,ref[k])
                          for k in ('path','code_path','log_path','metadata_path')]
                for candidate in paths:
                    candidate=store.project_path(root,str(candidate.relative_to(root)))
                    if any(part.is_symlink() for part in [candidate,*candidate.parents] if part.is_relative_to(root)):
                        raise WorkflowError('ARTIFACT_CHANGED','Symlink evidence is not allowed')
                for key,digest in [('path','sha256'),('code_path','code_sha256')]:
                    if not ref.get(digest) or store.digest(store.project_path(root,ref[key]))!=ref[digest]:
                        raise WorkflowError('ARTIFACT_CHANGED','Failed render evidence changed')
                metadata=store.read_json(store.project_path(root,ref['metadata_path']))
                if (ref['code_sha256']!=record.get('source_sha256')
                        or metadata.get('scene_id')!=sid
                        or metadata.get('version')!=ref.get('version')
                        or Path(metadata.get('video_path','')).resolve()!=store.project_path(root,ref['path']).resolve()):
                    continue
                if metadata.get('status')!='success':
                    continue
                files=[dict(path=str(p.relative_to(root)),sha256=store.digest(p)) for p in paths]
                evidence=dict(job_id=job['job_id'],reference=ref,files=files,
                    status='validation_failed',quality_passed=False,approvable=False,
                    vision_status='not_run' if not (work/'visual_review.json').exists() else 'see_saved_review',
                    issues=checks['issues'])
                verify(root,evidence)
                result[sid]=evidence
                break
        except (OSError,KeyError,ValueError,TypeError,WorkflowError):
            continue
    return result
