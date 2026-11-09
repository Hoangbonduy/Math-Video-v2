"""Plan -> local references -> code -> render -> AI review -> human decision."""
import copy
import ast
import hashlib
from pathlib import Path
from src.idea.content import parse_object
from src.shared import _workflow_store as store
from src.shared._workflow_store import WorkflowError
from src.shared.ai_utils import response_text, redact
from src.scene_design import scene_contract as contract, scene_references, scene_theme, plan_validation
from src.scene_design import scene_pipeline as legacy, scene_vision
from src.scene_design.design import CODE_SCHEMA, validate_code

VERSION=3
PLAN_SCHEMA=plan_validation.planner_schema()
MAX_REPAIRS=2


def _progress(session,phase,index):
    from src.shared.task_control import checkpoint
    checkpoint()
    session.job.update(progress=phase,design_pipeline=VERSION,repair_round=index,max_repairs=session.job.get('max_repairs',MAX_REPAIRS))
    session.save()


def _ask(session,phase,instruction,context,schema):
    return parse_object(response_text(session.call(phase,legacy._messages(instruction,context),schema=schema)))


def validate_plan(plan,context):
    return plan_validation.validate(plan,context)


def _plan(session,context,index,previous,issues):
    result=_ask(session,f'v3_plan_{index}',
        'Plan one concrete Manim scene from the approved script and visual brief. Preserve scene_id, '
        'narration and duration exactly. Partition narration into consecutive timed beats. '
        'Describe what appears, moves and what viewers understand; give observable visual criteria. '
        'Declare semantic object IDs and groups. Choose 1..16 public installed APIs and valid recipe_ids '
        'for reference lookup. Return the best implementable construction, noting uncertainty in the visual_strategy. '
        'Visual quality and geometry are judged on a rendered draft; uncertainty is not a reason to refuse a plan. '
        'Preserve approved content, material relationships and reveal timing. Use runtime capabilities. '
        'Return the supplied JSON schema only.',
        dict(context,previous_visual_plan=previous,issues=issues),PLAN_SCHEMA)
    return plan_validation.prepare(result,context)


def validate_helper_calls(source,references):
    """Catch unsupported helper keywords before spending a render attempt."""
    apis=references.get('component_apis',{})
    tree=ast.parse(source)
    aliases={}
    modules=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom) and node.module in ('manim_kit','src.scene_design.manim_kit'):
            for name in node.names:
                if name.name=='*':aliases.update({key:key for key in apis})
                else:aliases[name.asname or name.name]=name.name
        if isinstance(node,ast.Import):
            modules.update(n.asname or n.name for n in node.names if n.name=='manim_kit')
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call):continue
        name=aliases.get(node.func.id) if isinstance(node.func,ast.Name) else None
        if isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id in modules:
            name=node.func.attr
        info=apis.get(name,{})
        if not info.get('available') or info.get('accepts_kwargs',True):continue
        unknown={k.arg for k in node.keywords if k.arg is not None}-set(info.get('keywords',[]))
        if unknown:
            raise WorkflowError('INVALID_SCENE_CODE',f'Line {node.lineno}: {name} has unsupported keyword(s) {sorted(unknown)}. '
                f'Installed helper signature: {name}{info["signature"]}. Preserve readable size >= 22 after scaling.')
    return source





def _code(session,context,plan,references,index,previous,issues):
    result=_ask(session,f'v3_code_{index}',
        'Write a runnable Manim GeneratedScene(Scene) with construct from the supplied plan and approved '
        'visual_handoff. Import only manim, math, numpy, manim_kit or src.scene_design.manim_kit. '
        'Use the installed signatures and supplied local reference documents. Preserve narration and duration. '
        'Use real animated geometry and shared mathematical sources for dependent labels/curves. '
        'For each semantic object use track(self, literal_id, mob, role=kind); keep labels distinct. '
        'Embed style and duration as literals. self.camera.background_color may set the background. '
        'Do not change global config, camera dimensions or access renderer internals. '
        'The render_profile supplies logical frame size, pixel resolution and FPS; coordinates do not scale '
        'with pixels. Use vn_text(content,size=28) for Vietnamese. Keep text clear during motion, '
        'avoid narration walls; preserve the approved first/end state and delayed reveals. '
        'Represent a cutting construction using actual material pieces, not duplicated extra material. '
        'Use explicit self.play run_time budgets and finish_scene(self,target_seconds). '
        'Never call wait with nonpositive duration. No filesystem, network, subprocess, environment or introspection. '
        'MathTex requires system_capabilities.runtime.latex_available. ImageMobject only uses approved asset paths. '
        'Never prebuild .animate in Succession or use two builders on the same object in one play. '
        'previous_code, issues and repair_history contain earlier attempts: fix the code while preserving earlier fixes. '
        'If construction needs a different approach, implement that approach directly in source and explain it in reason. '
        'Return runnable source with requires_design_change=false; do not stop at a design objection.',
        dict(context,visual_plan=plan,selected_references=references,previous_code=previous,issues=issues),CODE_SCHEMA)
    contract.structure(result,CODE_SCHEMA,'manim_code')
    # Even a requested design change can carry a useful implementation: validate/run it.
    source=result['source']
    return validate_helper_calls(validate_code(source,context['assets']['assets']),references)


def _manifest(plan):
    return dict(schema_version=VERSION,scene_id=plan['scene_id'],narration=plan['narration'],
        purpose=plan['goal'],duration=plan['duration'],visual_strategy=plan['visual_strategy'],
        objects=plan['objects'],groups=plan['groups'],graphs=[],render_profile=scene_theme.profile(),
        layout_plan=copy.deepcopy(plan))


def render_code(root,work,session,design,source,config):
    from src.scene_design import scene_generation as sg, scene_evidence
    checksum=hashlib.sha256(source.encode()).hexdigest()
    path=work/'code_render.json'
    record=store.read_json(path) if path.exists() else None
    if record and record['source_sha256']!=checksum:
        raise WorkflowError('CACHE_CORRUPT','Saved scene source changed')
    if record and record['status']=='success':
        ref=record['reference']
        scene_evidence.verified_sources(root,ref,design,design['layout_plan'])
        return ref
    metadata=root/f"logs/{design['scene_id']}_{record['version']}.json" if record else None
    report=store.read_json(metadata) if metadata and metadata.exists() else {}
    if report.get('status')=='failed':
        raise WorkflowError('RENDER_FAILED',report.get('error') or 'Saved render failed')
    if report.get('status')!='success':
        version=sg._clip_version(root,design['scene_id'])
        code_path=f"scenes/{design['scene_id']}_{version}.py"
        store.materialize(root,code_path,content=source.encode())
        record=dict(status='running',version=version,code_path=code_path,source_sha256=checksum)
        store.atomic_write(path,record)
        settings=dict(scene_theme.render_profile(config['render']),target_duration=design['duration'],collect_layout=True)
        output=sg.RENDERER(root,design['scene_id'],version,code_path,'GeneratedScene',settings)
        if output['status']!='success':
            record.update(status='failed',error=output.get('error'));store.atomic_write(path,record)
            raise WorkflowError('RENDER_FAILED',output.get('error') or 'Manim failed')
        report=store.read_json(Path(output['log_path']).with_suffix('.json'))
    ref=sg.render_reference(root,design['scene_id'],Path(report['video_path']),
        dict(clip_version=record['version'],code_path=record['code_path']))
    ref['video'].pop('layout_telemetry',None)
    ref.update(preview_engine='direct_code',render_profile=scene_theme.profile(),scene_id=design['scene_id'],
        job_id=session.job['job_id'],metadata_sha256=store.digest(root/ref['metadata_path']),
        plan_sha256=scene_evidence.fingerprint(design['layout_plan']),
        component_sha256=store.digest(Path(__file__).with_name('manim_kit.py')),
        theme_sha256=store.digest(Path(scene_theme.__file__)))
    store.atomic_write(path,dict(record,status='success',reference=ref))
    return ref


def evidence(root,work,ref,design,plan,*,frame_budget=180):
    from src.scene_design import scene_evidence
    metadata,binding=scene_evidence.verified_sources(root,ref,design,plan)
    frames,spans,complete=scene_evidence.extract(root,work,ref,metadata,frame_budget)
    checks,render_checks=scene_evidence.build_checks(ref,metadata,design,spans,complete)
    video=metadata['video']
    # Duration mismatch is repair feedback, not grounds for hiding an existing video.
    if abs(video['duration_seconds']-design['duration'])>2/scene_theme.FPS+1e-6:
        checks['issues'].append(dict(category='timing',time=0,object_ids=[],
            problem=f"Video duration {video['duration_seconds']} differs from target {design['duration']}",
            fix='Adjust animation run_time budgets to the approved duration'))
        checks['passed']=False
    manifest=dict(frames=frames,contact_sheets=scene_evidence.sheets(root,work,frames,[video['width'],video['height']]),
        video_sha256=ref['sha256'],scene_id=design['scene_id'],render_version=ref['version'],
        encoded_visual_states=spans,source_kind='preview',
        sampling=dict(limit=frame_budget,review_frame_count=len(frames),complete=complete,
            strategy='Consecutive distinct encoded states, with first/last frames and identical holds compressed'))
    for name,value in [('layout_telemetry.json',video.get('layout_telemetry',{})),
                       ('motion_checks.json',checks),('render_checks.json',render_checks)]:
        store.atomic_write(work/name,value)
    scene_evidence.seal(root,work,manifest,binding,render_checks)
    store.atomic_write(work/'evidence.json',manifest)
    return checks,render_checks,manifest


def _publish(root,directory,session,work,design,plan,assets,ref,review):
    from src.scene_design import scene_generation as sg, scene_drafts
    scene_drafts.verify(root,store.read_json(store.project_path(root,session.job['draft']['path'])))
    sg._design_files(directory,design,assets,dict(schema_version=VERSION,datasets=[]))
    for name,value in [('assets.json',assets),('storyboard.json',plan),('manim_render.json',ref)]:
        legacy._write(directory/name,value)
    paths=[p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.json','.png','.jpg','.py')
           and p.name not in ('job.json','quality.json')]
    paths += [root/ref[k] for k in ('path','code_path','log_path','metadata_path')]
    quality=dict(passed=review['passed'],human_approval_required=True,pipeline_version=VERSION,
        design_sha256=store.digest(directory/'design.json'),video_sha256=ref['sha256'],
        storyboard_sha256=store.digest(directory/'storyboard.json'),
        review_model=session.job['vision_pricing']['model'],summary=review['summary'],
        repairs=session.job.get('repair_round',0),max_repairs=MAX_REPAIRS,issues=review['issues'],
        evidence_files=[dict(path=str(p.relative_to(root)),sha256=store.digest(p)) for p in paths])
    legacy._write(directory/'quality.json',quality)
    session.job.update(progress='ready_for_review',quality_issues=review['issues']);session.save()
    return directory/'design.json',dict(review_path=str((directory/'design.md').relative_to(root)),
        render_engine='manim',manim_render=ref,design_pipeline=VERSION,quality_passed=review['passed'],
        quality_path=str((directory/'quality.json').relative_to(root)),
        storyboard_path=str((directory/'storyboard.json').relative_to(root)))


def _detail(exc,phase):
    return dict(code=exc.code,category='meaning' if phase=='planning_visuals' else 'relation',
        owner='vision_reviewer' if phase=='evaluating_frames' else 'planner' if phase=='planning_visuals' else 'code_generator',
        time=0,object_ids=[],problem=redact(str(exc)),
        fix='Inspect the saved draft and repair the implementation using this feedback')


def generate(root,directory,session,context):
    from src.scene_design.script_visuals import with_visual_handoff
    from src.scene_design import scene_drafts
    context=with_visual_handoff(context)
    job=session.job
    session.max_requests=12
    max_repairs=job.get('input',{}).get('max_repairs',MAX_REPAIRS)
    if type(max_repairs) is not int or not 0<=max_repairs<=MAX_REPAIRS:
        raise WorkflowError('INVALID_INPUT','At most two automatic repairs are allowed')
    job['max_repairs']=max_repairs
    if (directory/'quality.json').exists():
        quality=legacy.verify_quality(root,dict(sha256=store.digest(directory/'design.json'),
            quality_path=str((directory/'quality.json').relative_to(root)),
            manim_render=store.read_json(directory/'manim_render.json')))
        return directory/'design.json',dict(review_path=str((directory/'design.md').relative_to(root)),
            render_engine='manim',manim_render=store.read_json(directory/'manim_render.json'),
            design_pipeline=VERSION,quality_passed=quality['passed'],
            quality_path=str((directory/'quality.json').relative_to(root)),
            storyboard_path=str((directory/'storyboard.json').relative_to(root)))
    cap_path=directory/'system_capabilities.json'
    capabilities=store.read_json(cap_path) if cap_path.exists() else scene_references.capabilities()
    legacy._write(cap_path,capabilities)
    if capabilities['runtime']['version']!=scene_references.manim_runtime.info()['version']:
        raise WorkflowError('DEPENDENCY_ERROR','Installed Manim changed during this job')
    assets=context.get('shared_assets') or dict(assets=[],failures=[],fallback_required=False)
    legacy._write(directory/'assets.json',assets)
    if context.get('visual_handoff'):legacy._write(directory/'visual_handoff.json',context['visual_handoff'])
    context=dict(context,system_capabilities=capabilities,render_profile=scene_theme.profile(),assets=assets)
    vision=scene_vision.CLIENT_FACTORY()
    if 'vision_pricing' not in job:
        job['vision_pricing']=vision.preflight(search=False);session.save()
    if job['vision_pricing']['model']!=scene_vision.review_model():
        raise WorkflowError('MODEL_MISMATCH','Restore the configured visual review model')
    plan=None;source=None;issues=[];latest=None
    allowed={'INVALID_SCENE_DESIGN','INVALID_SCENE_REFERENCE','INVALID_SCENE_CODE','RENDER_FAILED',
             'SCENE_DURATION_MISMATCH','INVALID_MODEL_OUTPUT','INVALID_VISUAL_REVIEW'}
    for index in range(max_repairs+1):
        work=directory/f'round_{index:02}';work.mkdir(exist_ok=True)
        result_path=work/'result.json'
        if result_path.exists():
            result=store.read_json(result_path)
            if (work/'storyboard.json').exists():plan=store.read_json(work/'storyboard.json')
            if (work/'scene.py').exists():source=(work/'scene.py').read_text()
            issues=result['issues']
            if result.get('reference') and result.get('review'):
                latest=(work,store.read_json(work/'design.json'),plan,assets,result['reference'],result['review'])
            if result.get('passed') and latest:
                return _publish(root,directory,session,*latest)
            continue
        ref=None;review=None
        try:
            if plan is None:
                _progress(session,'planning_visuals',index)
                plan=_plan(session,context,index,plan,issues)
            legacy._write(work/'storyboard.json',plan)
            _progress(session,'reading_references',index)
            references=scene_references.lookup(plan['required_apis'],plan['recipe_ids'])
            legacy._write(work/'references.json',references)
            if references['missing']:
                raise WorkflowError('INVALID_SCENE_REFERENCE','Unavailable APIs: '+', '.join(references['missing']))
            design=_manifest(plan);design['generation_job_id']=job['job_id']
            legacy._write(work/'design.json',design)
            _progress(session,'writing_code' if index==0 else 'repairing_code',index)
            history=[dict(round=p.parent.name,issues=store.read_json(p)['issues'])
                     for p in sorted(directory.glob('round_*/result.json'))]
            source=_code(session,dict(context,repair_history=history),plan,references,index,source,issues)
            store.materialize(work,'scene.py',content=source.encode())
            _progress(session,'rendering_draft',index)
            ref=render_code(root,work,session,design,source,context['config'])
            checks,render_checks,manifest=evidence(root,work,ref,design,plan,
                frame_budget=context.get('evidence_frame_budget',180))
            scene_drafts.publish(root,work,session,ref)
            # A valid video remains reviewable even when Vision cannot return valid JSON.
            review=dict(passed=False,summary='AI chưa hoàn tất kiểm tra hình ảnh',criteria_results=[],issues=[])
            latest=(work,design,plan,assets,ref,review)
            _progress(session,'evaluating_frames',index)
            review=legacy._review(root,session,vision,plan,design,manifest,render_checks,index,
                phase_prefix='v3',visual_handoff=context.get('visual_handoff'))
            # Exact duration is technical; other geometric measurements are visual review clues.
            timing=[i for i in checks['issues'] if i['category']=='timing' and i['problem'].startswith('Video duration')]
            review=copy.deepcopy(review)
            review['issues']=timing+review['issues']
            review['passed']=review['passed'] and not timing
            legacy._write(work/'visual_review.json',review)
            issues=review['issues']
            latest=(work,design,plan,assets,ref,review)
            job['draft']['review']=dict(passed=review['passed'],summary=review['summary'],
                criteria_passed=sum(r['passed'] for r in review['criteria_results']),
                criteria_total=len(review['criteria_results']),vision_status='completed')
            session.save()
            legacy._write(result_path,dict(passed=review['passed'],issues=issues,reference=ref,review=review))
            if review['passed']:return _publish(root,directory,session,*latest)
        except WorkflowError as exc:
            if exc.code not in allowed:raise
            phase=job.get('progress')
            issues=[_detail(exc,phase)]
            # If reference selection failed, the next repair revises the handoff.
            if phase in ('planning_visuals','reading_references'):
                issues[0]['category']='unsupported' if phase=='reading_references' else 'meaning'
                issues[0]['fix']='Correct required_apis / recipe_ids or return a usable scene plan'
                plan=None
            if latest and ref:
                review=dict(latest[-1],passed=False,issues=issues)
                latest=(*latest[:-1],review)
                job['draft']['review']=dict(passed=False,summary='AI chưa hoàn tất kiểm tra; xem lỗi còn lại',
                    vision_status='failed',criteria_passed=0,criteria_total=0)
                session.save()
            legacy._write(result_path,dict(passed=False,issues=issues,
                **(dict(reference=ref,review=review) if ref and latest else {})))
    job.update(quality_issues=issues);session.save()
    if latest:
        work,design,plan,assets,ref,review=latest
        remaining=list(review['issues'])
        for item in issues:
            if item not in remaining:remaining.append(item)
        review=dict(review,passed=False,issues=remaining,
                    summary='Đã dừng sau tối đa 2 lượt sửa. Xem bản nháp và lỗi còn lại để quyết định.')
        return _publish(root,directory,session,work,design,plan,assets,ref,review)
    job.update(progress='quality_failed');session.save()
    raise WorkflowError('SCENE_QUALITY_FAILED','No playable draft after two repairs. '+'; '.join(i['problem'] for i in issues)[:1200])


def render_final(root, artifact, config=None):
    """Rerender approved source at native final resolution without model calls."""
    from src.scene_design import scene_generation as sg
    root=Path(root)
    legacy.verify_quality(root,artifact)
    ref=artifact['manim_render']
    if store.digest(root/ref['code_path'])!=ref['code_sha256']:
        raise WorkflowError('ARTIFACT_CHANGED','Approved source changed')
    design=store.read_json(root/artifact['path'])
    for name,checksum in [('manim_kit.py',ref.get('component_sha256')),
                          ('scene_theme.py',ref.get('theme_sha256'))]:
        if checksum and store.digest(Path(__file__).with_name(name))!=checksum:
            raise WorkflowError('ARTIFACT_CHANGED','Shared component/theme changed after scene review')
    runtime=scene_references.manim_runtime.info()
    if runtime['version']!=ref['runtime']['version']:
        raise WorkflowError('DEPENDENCY_ERROR','Final render requires the reviewed Manim runtime')
    # Keep the source and logical camera fixed; only increase pixel density.
    version=sg._clip_version(root,design['scene_id'])
    output=sg.RENDERER(root,design['scene_id'],version,ref['code_path'],'GeneratedScene',
        dict(scene_theme.render_profile((config or sg._config(root))['render'],final=True),
              target_duration=design['duration'],collect_layout=True))
    if output['status']!='success':
        return output
    metadata_path=Path(output['log_path']).with_suffix('.json')
    metadata=store.read_json(metadata_path)
    preview=store.read_json(root/ref['metadata_path'])['video']['layout_telemetry']
    final=metadata['video'].get('layout_telemetry',{})
    checks=compare_layouts(preview,final,design)
    path=metadata_path.with_suffix('.layout.json');store.atomic_write(path,checks)
    output['layout_checks_path']=str(path)
    if not checks['passed']:
        output.update(status='failed',error='FINAL_LAYOUT_MISMATCH: '+str(checks['issues'])[:1000])
    return output


def compare_layouts(preview,final,design,tolerance=.03):
    # Preserve the reviewed geometry; existing visual warnings belong to human review.
    issues=[]
    known={o['id'] for o in design['objects']} & set(preview.get('object_ids',[]))
    if not final.get('checked_frames') or not known<=set(final.get('object_ids',[])):
        issues.append(dict(problem='Final layout telemetry is incomplete'))
    expected={row['frame']:row for row in preview.get('samples',[])}
    actual={row['frame']:row for row in final.get('samples',[])}
    checked=0
    for frame,a in expected.items():
        b=actual.get(frame)
        if not b:
            issues.append(dict(frame=frame,problem='Final render is missing a preview layout milestone'))
            continue
        for oid in known:
            x,y=a['objects'].get(oid),b['objects'].get(oid)
            if x is None and y is None:
                continue
            if x is None or y is None or any(abs(v-w)>tolerance for v,w in zip(x['box'],y['box'])):
                issues.append(dict(frame=frame,object_ids=[oid],problem='Final geometry differs from reviewed preview'))
            checked+=1
    return dict(passed=not issues,issues=issues,compared_objects=checked,
        tolerance_scene_units=tolerance,preview_resolution=[360,640],final_resolution=[1080,1920],
        frame_contract=scene_theme.profile())
