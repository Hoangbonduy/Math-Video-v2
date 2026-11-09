"""Script + style + capabilities -> visual plan -> direct Manim -> frame review.

V3 keeps JSON as a review manifest, never as a fixed geometry language.
Old v2 rounds remain readable and resumable through scene_pipeline.
"""
import copy
import ast
import hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from src.idea.content import _object, parse_object
from src.shared import _workflow_store as store
from src.shared._workflow_store import WorkflowError
from src.shared.ai_utils import response_text, redact
from src.scene_design import scene_contract as contract, scene_references, scene_theme, plan_validation
from src.scene_design import scene_pipeline as legacy, scene_vision, system_contract as system
from src.scene_design.design import CODE_SCHEMA, validate_code
from src.scene_design.scene_telemetry import select_frames

VERSION = 3
PLAN_SCHEMA = plan_validation.planner_schema(system.load())


def _progress(session, phase, index):
    from src.shared.task_control import checkpoint
    checkpoint()
    session.job.update(progress=phase, design_pipeline=VERSION, repair_round=index,
                       max_repairs=session.job.get('max_repairs',session.job.get('input',{}).get('max_repairs',0)))
    session.save()


def _ask(session, phase, instruction, context, schema):
    if context.get('system_contract'):
        instruction += system.instructions(context['system_contract'])
    return parse_object(response_text(session.call(phase, legacy._messages(instruction,context),schema=schema)))


def validate_plan(plan, context):
    return plan_validation.validate(plan, context)


def _plan(session, context, index, previous, issues):
    context=dict(context,system_contract=context.get('system_contract') or system.load())
    result=_ask(session,f'v3_plan_{index}',
        'Plan a concrete Manim visual explanation from the approved script, style and runtime capabilities. '
        'Return only the planning JSON schema. Preserve scene_id, narration and duration exactly. '
        'Partition the approved narration into consecutive beats without changing its words. '
        'Declare objects with stable unique IDs, kind and layout_role, groups and timeline targets. '
        'Each independently moving physical piece must have its own stable planned object ID; '
        'represent its parent assembly as a named group of those IDs, not as an overlapping tracked object. '
        'Do not track an entire assembly as one rigid piece. Keep grid lines and labels distinct from material pieces. '
        'Where an approved delayed reveal forbids exposing loss bands, do not show thin strips or gaps '
        'even without explanatory labels. If no faithful physical construction preserves the reveal, '
        'report the genuine conflict instead of silently inventing extra material. '

        'Keep all local timestamps within scene duration and every referenced ID defined. '
        'Choose 1..16 public Manim/helper APIs and valid recipe_ids for targeted reference lookup. '
        'Use runtime signatures rather than assuming APIs from newer documentation exist. '
        'Use the portrait coordinate frame and design sensible anchors, visibility intervals, paths and rigid transforms. '
        'The pre-code gate has ONLY three groups: JSON/script/contract identity; lookup catalog; IDs and bounded times. '
        'Layout, actual HUD movement, phase sequencing, geometry, mathematical illusion and reveal order are judged '
        'from the rendered draft, actual telemetry and approved script. Do not turn uncertain visual quality into a metadata conflict. '
        'Report contract_conflict only for a concrete incompatible approved requirement. '
        'Do not calculate geometry_checkpoints or predicted bounding boxes. '
        'Do not copy approved criteria, create criterion_rules, quote approval text or supply reveal self-audits: '
        'Python attaches approved criteria and initial/end/continuity rules before code generation. '
        'Explain actual construction and motion through goal, visual_strategy and beat show/motion/understand fields. '
        'Code generation receives the full approved visual handoff; preserve its dimensions, invariants and reveal order. '
        'Use planning_references as construction references, not as proof that a previous render passed. '
        'Return contract_version/contract_sha256 from this job snapshot. '
        'When repairing, address the supplied issues while preserving the approved narration and unaffected construction.',
        dict(context,previous_visual_plan=previous,issues=issues),
        plan_validation.planner_schema(context['system_contract']))
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


def _code(session, context, plan, references, index, previous, issues):
    context=dict(context,system_contract=context.get('system_contract') or system.load())
    result=_ask(session,f'v3_code_{index}',
        'Write runnable direct Python Manim code from the visual plan, style and installed API references. '
        'Return one GeneratedScene(Scene) with construct; import only manim, math, numpy, manim_kit or src.scene_design.manim_kit. '
        'Use shared components and track(self, object_id, mobject, kind=kind, layout_role=layout_role) '
        'for EVERY planned semantic object, especially each text/formula separately from backgrounds and axes. '
        'Use literal object IDs, kind and layout_role in each track() call; match validated metadata exactly. Do not pass overlap_with; runtime applies only plan-approved intervals. '
        'Track semantic parts separately without duplicate registration of parent and child geometry. '
        'Track independently moving material pieces separately using their planned IDs; '
        'do not represent an assembly and all independently moving pieces as one rigid object. '
        'Do not show internal loss bands or moving strips before an approved delayed reveal. '
        'Preserve the original material and piece boundaries; a drawn grid is a marking, not extra material. '

        'Labels must remain clear throughout motion. '
        'Use vn_text(content, size=28), formula_lines, fit_to_safe_area and MIN_FONT_SIZE; wrap formulas at semantic boundaries. '
        'Helper signatures in component_apis are authoritative. Effective font size after every scale must stay >= MIN_FONT_SIZE. '
        'repair_history contains earlier failures: preserve fixes already made and do not reintroduce them while fixing the latest issue. '
        'Text and geometry use the same 9 x 16 frame at 360x640 preview and 1080x1920 final, both 30 FPS. '
        'Never multiply coordinates, font sizes, stroke widths or timing by pixel resolution. Never change global config or camera dimensions. '
        'Only camera exception: set self.camera.background_color to the style literal at the start of construct, before all calls. '
        'No other camera/renderer access or lifecycle hooks. Embed style/duration as Python literals. '
        'Enforce safe_bounds except exact approved cropped_context edges and intervals. '
        'Never prebuild .animate in Succession or multiple builders for the same geometry in one play. '
        'Use consecutive self.play calls or explicit Transform targets built from cumulative independent copies; '
        'do not derive every target from the original state. Verify intermediate and final centers/dimensions against the plan. '
        'HUD emphasis changes only color/brightness at the fixed anchor, never shake/scale/rotate, even with zero net displacement. '
        'Keep HUD fixed, focal visible in observation_intervals, and captions protected during crops. '
        'Use actual Manim animations, geometry, Axes, ValueTracker and updaters; dependent mathematical values use a single shared source. '
        'For cutting/rearranging objects, derive pieces from the original geometry and conserve area; never create a duplicate piece to fake extraction. '
        'Start with visible anchor objects at t=0, meaningful motion by 0.8s, no blank opening. '
        'Budget each self.play explicitly; call finish_scene(self, target_seconds). Never wait with nonpositive duration. '
        'Preserve narration exactly; no sound or narration walls. Use DejaVu Sans Text for Vietnamese; '
        'MathTex is allowed ONLY if system_capabilities.runtime.latex_available is true. '
        'ImageMobject may use only literal approved asset paths; use Group for images. '
        'No filesystem, networking, subprocess, environment, introspection or external imports. '
        'Repair normal layout/timing/math/runtime issues DIRECTLY IN THE CODE (buff, scale, shift, paths, run_time). '
        'Set requires_design_change=true ONLY when meaning or density cannot be repaired while preserving readable minimum fonts; '
        'Prefix reason with LAYOUT_REPLAN_REQUIRED for density or MEANING_REPLAN_REQUIRED for meaning errors. This returns to visual planning. '
        'Do not change visual criteria merely to pass review. Use exact installed API signatures over newer local documentation.',
        dict(context,visual_plan=plan,selected_references=references,
             previous_code=previous,issues=issues),CODE_SCHEMA)
    contract.structure(result,CODE_SCHEMA,'manim_code')
    if result['requires_design_change']:
        if result['reason'].startswith('CONTRACT_CONFLICT'):
            system.fail(result['reason'])
        code='MEANING_REPLAN_REQUIRED' if result['reason'].startswith('MEANING_REPLAN_REQUIRED') else 'LAYOUT_REPLAN_REQUIRED'
        raise WorkflowError(code,result['reason'] or 'Visual plan needs splitting')
    bundle=context['system_contract']
    source=validate_helper_calls(validate_code(result['source'],context['assets']['assets']),references)
    system.validate_ast(source,bundle,background=context.get('config',{}).get('background'))
    system.validate_tracking(source,plan)
    return '# system_contract_version: '+bundle['contract_version']+'\n# system_contract_sha256: '+bundle['sha256']+'\n'+source


def _manifest(plan,bundle):
    return dict(schema_version=VERSION,scene_id=plan['scene_id'],narration=plan['narration'],
        purpose=plan['goal'],duration=plan['duration'],visual_strategy=plan['visual_strategy'],
        objects=plan['objects'],groups=plan['groups'],graphs=[],render_profile=scene_theme.profile(bundle),
        system_contract=bundle,layout_plan=copy.deepcopy(plan),**system.reference(bundle))


def render_code(root, work, session, design, source, config):
    from src.scene_design import scene_generation as sg
    bundle=system.verify(design['system_contract'])
    system.assert_reference(design,bundle)
    system.validate_ast(source,bundle,background=config.get('background'))
    system.validate_tracking(source,design['layout_plan'])
    frame_profile=scene_theme.profile(bundle)
    checksum=hashlib.sha256(source.encode()).hexdigest()
    path=work/'code_render.json'
    record=store.read_json(path) if path.exists() else None
    if record:
        system.assert_reference(record,bundle)
    if record and record['source_sha256']!=checksum:
        raise WorkflowError('CACHE_CORRUPT','Saved v3 source changed')
    if record and record['status']=='success':
        ref=record['reference']
        for key,digest in [('path','sha256'),('code_path','code_sha256')]:
            if store.digest(root/ref[key])!=ref[digest]:
                raise WorkflowError('ARTIFACT_CHANGED','Saved Manim candidate changed')
        if ref.get('metadata_sha256'):
            return ref
        # A legacy reference cannot authenticate telemetry. Render the exact
        # cached source locally into a new version instead of adopting its metadata.
        record=None
    # Recover a completed worker after an interruption without another render.
    metadata=root/f"logs/{design['scene_id']}_{record['version']}.json" if record else None
    report=store.read_json(metadata) if metadata and metadata.exists() else {}
    if report.get('status')=='success':
        output=report
    else:
        version=sg._clip_version(root,design['scene_id'])
        code_path=f"scenes/{design['scene_id']}_{version}.py"
        store.materialize(root,code_path,content=source.encode())
        record=dict(status='running',version=version,code_path=code_path,source_sha256=checksum,**system.reference(bundle))
        store.atomic_write(path,record)
        settings=dict(scene_theme.render_profile(config['render'],bundle=bundle),
                      target_duration=design['duration'],collect_layout=True,
                      system_contract=bundle,layout_plan=design['layout_plan'])
        output=sg.RENDERER(root,design['scene_id'],version,code_path,'GeneratedScene',settings)
        if output['status']!='success':
            raise WorkflowError('RENDER_FAILED',output.get('error') or 'Manim failed')
        report=store.read_json(Path(output['log_path']).with_suffix('.json'))
    video=report['video']
    if abs(video['duration_seconds']-design['duration'])>frame_profile['duration_tolerance_frames']/frame_profile['fps']+1e-6:
        raise WorkflowError('SCENE_DURATION_MISMATCH','Manim duration differs from approved narration timing')
    # The worker already validates FPS with encoding tolerance. Do not reject
    # a valid movie here because its measured average is slightly above 30.
    if [video['width'],video['height']]!=frame_profile['preview_resolution']:
        raise WorkflowError('RENDER_FAILED','Preview must match contract resolution')
    ref=sg.render_reference(root,design['scene_id'],Path(output['video_path']),
        dict(clip_version=record['version'],code_path=record['code_path']))
    ref['video'].pop('layout_telemetry',None)
    from src.scene_design.scene_evidence import fingerprint
    ref.update(preview_engine='direct_code',frame_contract=frame_profile,scene_id=design['scene_id'],job_id=getattr(session,'job',{}).get('job_id'),
        metadata_sha256=store.digest(root/ref['metadata_path']),
        plan_sha256=fingerprint(design['layout_plan']),
        **system.reference(bundle),
        component_sha256=store.digest(Path(__file__).with_name('manim_kit.py')),
        theme_sha256=store.digest(Path(scene_theme.__file__)))
    store.atomic_write(path,dict(record,status='success',reference=ref))
    return ref


def evidence(root, work, ref, design, plan, *, frame_budget=180, requirements=None):
    from src.scene_design import scene_evidence
    bundle=system.verify(design['system_contract'])
    if requirements is not None and requirements != design.get('evidence_requirements',[]):
        raise WorkflowError('INVALID_INPUT','Bind evidence requirements to the caller design before extraction')
    metadata,binding=scene_evidence.verified_sources(root,ref,design,plan)
    video=metadata['video'];telemetry=video['layout_telemetry']
    frames,spans,complete=scene_evidence.extract(root,work,ref,metadata,frame_budget)
    rows=scene_evidence.coverage(plan,frames,spans,complete,binding['source_kind'],
        design.get('evidence_requirements',[]))
    checks,render_checks=scene_evidence.build_checks(ref,metadata,design,spans,rows)
    manifest=dict(**system.reference(bundle),frames=frames,
        contact_sheets=scene_evidence.sheets(root,work,frames,[video['width'],video['height']]),
        video_sha256=ref['sha256'],scene_id=design['scene_id'],render_version=binding['version'],
        source_kind=binding['source_kind'],encoded_visual_states=spans,evidence_coverage=rows,
        sampling=dict(limit=frame_budget,review_frame_count=len(frames),complete=complete,
            strategy='Consecutive decoded RGB states in order, identical holds compressed; first and last included'))
    for name,data in [('layout_telemetry.json',telemetry),('motion_checks.json',checks),('render_checks.json',render_checks)]:
        store.atomic_write(work/name,data)
    scene_evidence.seal(root,work,manifest,binding,render_checks)
    store.atomic_write(work/'evidence.json',manifest)
    return checks,render_checks,manifest


def _publish(root,directory,session,work,design,plan,assets,ref,review):
    from src.scene_design import scene_generation as sg
    bundle=system.verify(design['system_contract'])
    for artifact in (design,plan,ref,review):
        system.assert_reference(artifact,bundle)
    for key,digest in [('path','sha256'),('code_path','code_sha256')]:
        if store.digest(store.project_path(root,ref[key]))!=ref[digest]:
            raise WorkflowError('ARTIFACT_CHANGED','Candidate changed before publication')
    sg._design_files(directory,design,assets,dict(schema_version=VERSION,datasets=[]))
    for name,data in [('assets.json',assets),('storyboard.json',plan),('manim_render.json',ref)]:
        legacy._write(directory/name,data)
    files=[p for p in work.rglob('*') if p.is_file() and p.suffix in ('.json','.png','.jpg','.py')]
    files += [directory/'design.json',directory/'storyboard.json',root/ref['path'],root/ref['code_path']]
    bundle=design['system_contract']
    files += [directory/'system_contract_snapshot.md',directory/'system_contract.json']
    files += [directory/name for name in ('visual_handoff.json','visual_handoff_source.json')
              if (directory/name).exists()]
    quality=dict(passed=review['passed'],pipeline_version=VERSION,**system.reference(bundle),
        design_sha256=store.digest(directory/'design.json'),video_sha256=ref['sha256'],
        storyboard_sha256=store.digest(directory/'storyboard.json'),
        review_model=session.job['vision_pricing']['model'],summary=review['summary'],
        repairs=session.job.get('repair_round',0),issues=review['issues'],
        evidence_files=[dict(path=str(p.relative_to(root)),sha256=store.digest(p)) for p in files])
    legacy._write(directory/'quality.json',quality)
    session.job.update(progress='ready_for_review',quality_issues=review['issues']);session.save()
    return directory/'design.json',dict(review_path=str(directory/'design.md'),
        render_engine='manim',manim_render=ref,design_pipeline=VERSION,quality_passed=review['passed'],
        quality_path=str((directory/'quality.json').relative_to(root)),
        storyboard_path=str((directory/'storyboard.json').relative_to(root)))


def generate(root,directory,session,context):
    from src.scene_design.script_visuals import with_visual_handoff, visual_handoff
    script=context.get('script') or {}
    from src.idea.visuals import require_visual_readiness
    require_visual_readiness(script)
    source_handoff=(visual_handoff(script,context['scene']['scene_id']) if 'global_visuals' in script
                    else copy.deepcopy(context.get('visual_handoff')))
    context=with_visual_handoff(context)
    bundle=system.bind_job(directory,session.job,context.get('system_contract'))
    context=with_visual_handoff(dict(context,system_contract=bundle))
    session.save()
    if context.get('visual_handoff'):
        legacy._write(directory/'visual_handoff.json',context['visual_handoff'])
        if context['visual_handoff'].get('contract_binding'):
            legacy._write(directory/'visual_handoff_source.json',source_handoff)
    session.max_requests=24
    job=session.job
    max_repairs=job.get('input',{}).get('max_repairs',0)
    if type(max_repairs) is not int or not 0<=max_repairs<=3:
        raise WorkflowError('INVALID_INPUT','Invalid scene repair limit')
    from src.scene_design.scene_generation import repair_limit
    max_repairs=min(max_repairs,repair_limit(job.get('input',{}).get('trial_mode',False)))
    job['max_repairs']=max_repairs
    session.save()
    final=directory/'quality.json'
    if final.exists():
        quality=store.read_json(final);ref=store.read_json(directory/'manim_render.json')
        system.assert_reference(quality,bundle)
        system.assert_reference(ref,bundle)
        legacy.verify_quality(root,dict(sha256=store.digest(directory/'design.json'),
            quality_path=str(final.relative_to(root)),manim_render=ref))
        return directory/'design.json',dict(review_path=str(directory/'design.md'),render_engine='manim',
            manim_render=ref,design_pipeline=VERSION,quality_passed=quality['passed'],
            quality_path=str(final.relative_to(root)),storyboard_path=str((directory/'storyboard.json').relative_to(root)))
    cap_path=directory/'system_capabilities.json'
    if cap_path.exists():
        capabilities=store.read_json(cap_path)
        if capabilities['runtime']['version']!=scene_references.manim_runtime.info()['version']:
            raise WorkflowError('DEPENDENCY_ERROR','Installed Manim changed during a saved job')
    else:
        capabilities=scene_references.capabilities();legacy._write(cap_path,capabilities)
    assets=context.get('shared_assets') or dict(assets=[],failures=[],fallback_required=False)
    legacy._write(directory/'assets.json',assets)
    context=dict(context,system_capabilities=capabilities,frame_contract=scene_theme.profile(bundle),assets=assets)
    vision=scene_vision.CLIENT_FACTORY()
    if 'vision_pricing' not in job:
        job['vision_pricing']=vision.preflight(search=False);session.save()
    if job['vision_pricing']['model']!=scene_vision.review_model():
        raise WorkflowError('MODEL_MISMATCH','Restore the configured visual review model')
    plan=None;source=context.get('previous_code');issues=[]
    previous=context.get('previous_design') or {}
    if previous.get('schema_version')==3 and previous.get('contract_sha256')==bundle['sha256']:
        plan=context.get('previous_storyboard')
        if plan:
            validate_plan(plan,context)
    elif previous:
        source=None
    for index in range(max_repairs+1):
        work=directory/f'round_{index:02}';work.mkdir(exist_ok=True)
        result_path=work/'result.json'
        if result_path.exists():
            result=store.read_json(result_path)
            system.assert_reference(result,bundle)
            if (work/'storyboard.json').exists():
                plan=store.read_json(work/'storyboard.json')
                validate_plan(plan,context)
            if (work/'scene.py').exists():source=(work/'scene.py').read_text(encoding='utf-8')
            issues=result['issues']
            if result.get('reviewable'):
                return _publish(root,directory,session,work,store.read_json(work/'design.json'),
                    plan,assets,result['reference'],result['review'])
            continue
        checks=None
        try:
            needs_plan=plan is None or any(i['category'] in ('meaning','unsupported') or 'LAYOUT_REPLAN_REQUIRED' in i['problem'] for i in issues)
            if needs_plan:
                _progress(session,'planning_visuals',index)
                plan=_plan(session,context,index,plan,issues)
            legacy._write(work/'storyboard.json',plan)
            _progress(session,'reading_references',index)
            ref_path=work/'references.json'
            references=store.read_json(ref_path) if ref_path.exists() else {}
            if references.get('schema_version')!=scene_references.REFERENCE_VERSION:
                references=scene_references.lookup(plan['required_apis'],plan['recipe_ids'])
            legacy._write(ref_path,references)
            if references['missing']:
                raise WorkflowError('LAYOUT_REPLAN_REQUIRED','Unavailable installed APIs: '+', '.join(references['missing']))
            design=_manifest(plan,bundle)
            design['generation_job_id']=session.job['job_id']
            if context.get('evidence_requirements'):
                design['evidence_requirements']=copy.deepcopy(context['evidence_requirements'])
            legacy._write(work/'design.json',design)
            _progress(session,'writing_code' if source is None else 'repairing_code',index)
            history=[dict(round=path.parent.name,issues=store.read_json(path).get('issues',[]))
                for path in sorted(directory.glob('round_*/result.json')) if path.parent.name<work.name]
            source=_code(session,dict(context,repair_history=history),plan,references,index,source,issues)
            store.materialize(work,'scene.py',content=source.encode())
            _progress(session,'rendering_draft',index)
            ref=render_code(root,work,session,design,source,context['config'])
            evidence_options={}
            if 'evidence_frame_budget' in context:
                evidence_options['frame_budget']=context['evidence_frame_budget']
            # Preserve old evidence when a caller supplies a new frame budget.
            from src.scene_design.scene_evidence import fingerprint
            request=dict(options=evidence_options,requirements=design.get('evidence_requirements',[]),
                         previous_scene_render=context.get('previous_scene_render'))
            request_path=work/'evidence_request.json'
            if not request_path.exists():
                legacy._write(request_path,request)
            evidence_work=work
            if store.read_json(request_path)!=request:
                evidence_work=work/'evidence_versions'/fingerprint(request)
                evidence_work.mkdir(parents=True,exist_ok=True)
            if job.get('draft'):
                from src.scene_design import scene_drafts
                previous=job['draft']
                previous_path=store.project_path(root,previous['path'])
                if store.digest(previous_path)!=previous['sha256']:
                    raise WorkflowError('ARTIFACT_CHANGED','Saved draft manifest changed')
                scene_drafts.verify(root,store.read_json(previous_path))
            draft_path=evidence_work/'draft.json'
            if draft_path.exists():
                from src.scene_design import scene_drafts
                scene_drafts.verify(root,store.read_json(draft_path))
            checks,render_checks,manifest=evidence(root,evidence_work,ref,design,plan,**evidence_options)
            from src.scene_design import scene_drafts
            from src.scene_design.contract_review import prepare_continuity
            render_checks['continuity_evidence']=prepare_continuity(root,evidence_work,context)
            store.atomic_write(evidence_work/'render_checks.json',render_checks)
            scene_drafts.publish(root,work,session,ref,evidence_work=evidence_work)
            # Deterministic findings never suppress visual inspection of an
            # existing draft. They remain binding on the overall result.
            _progress(session,'evaluating_frames',index)
            from src.scene_design.scene_evidence import require_coverage
            require_coverage(render_checks,render_checks['continuity_evidence'])
            review=legacy._review(root,session,vision,plan,design,manifest,render_checks,index if evidence_work==work else str(index)+'_evidence_'+fingerprint(request),phase_prefix='v3',visual_handoff=context.get('visual_handoff'))
            if any(c.get('status')=='insufficient_evidence' for c in review['criteria_results']):
                legacy._write(evidence_work/'visual_review.json',review)
                from src.scene_design.scene_evidence import require_review_evidence
                require_review_evidence(review)
            legacy._write(evidence_work/'visual_review.json',review)
            issues=list(checks['issues'])+list(review['issues'])
            job['draft']['review']=dict(passed=review['passed'] and checks['passed'],summary=review['summary'],
                criteria_passed=sum(c.get('status')=='pass' for c in review['criteria_results']),criteria_total=len(review['criteria_results']),
                vision_status='completed',automatic_issue_count=len(checks['issues']))
            session.save()
            if not checks['passed']:
                legacy._write(result_path,dict(**system.reference(bundle),passed=False,
                    issues=issues,reference=ref,draft_saved=True,review=review))
                continue
            reviewable=review['passed'] or index==max_repairs
            legacy._write(result_path,dict(**system.reference(bundle),passed=review['passed'],issues=issues,reviewable=reviewable,reference=ref,review=review))
            if reviewable:
                return _publish(root,directory,session,work,design,plan,assets,ref,review)
        except WorkflowError as exc:
            if exc.code not in ('INVALID_SCENE_DESIGN','INVALID_SCENE_REFERENCE','INVALID_SCENE_CODE','RENDER_FAILED','SCENE_DURATION_MISMATCH','INVALID_MODEL_OUTPUT','INVALID_VISUAL_REVIEW','LAYOUT_REPLAN_REQUIRED','MEANING_REPLAN_REQUIRED','CONTRACT_CONFLICT'):
                raise
            reference_failure=exc.code=='INVALID_SCENE_REFERENCE' or job.get('progress')=='reading_references'
            planning_failure=job.get('progress')=='planning_visuals'
            category='unsupported' if reference_failure else 'meaning' if planning_failure or plan is None or exc.code in ('MEANING_REPLAN_REQUIRED','CONTRACT_CONFLICT') else 'layout' if exc.code=='LAYOUT_REPLAN_REQUIRED' else 'relation'
            review_failure=job.get('progress')=='evaluating_frames'
            detail=dict(code=exc.code,owner='vision_reviewer' if review_failure else 'planner' if category in ('meaning','unsupported') else 'code_generator',
                         rule='visual_review' if review_failure else 'ast_constraints' if exc.code=='INVALID_SCENE_CODE' else 'visual_plan',
                         evidence=redact(str(exc)),category=category,time=0,object_ids=[],problem=redact(str(exc)),
                         fix='Retry visual review of the saved draft; keep automatic findings.' if review_failure else 'Correct required_apis or recipe_ids in the visual plan; no scene code has been rendered for this reference error.' if reference_failure else 'Repair the visual plan' if planning_failure or exc.code in ('LAYOUT_REPLAN_REQUIRED','MEANING_REPLAN_REQUIRED','CONTRACT_CONFLICT') or plan is None else 'Repair the Manim code; preserve the visual plan and criteria')
            issues=(list(checks.get('issues',[])) if checks else [])+[detail]
            legacy._write(result_path,dict(**system.reference(bundle),passed=False,issues=issues,
                **(dict(draft_saved=True) if job.get('draft') else {})))
            if review_failure:
                break
    job.update(progress='quality_failed',quality_issues=issues);session.save()
    raise WorkflowError('SCENE_QUALITY_FAILED','Cảnh cần sửa sau các vòng kiểm tra. '+ '; '.join(i['problem'] for i in issues)[:800])


def render_final(root, artifact, config=None):
    """Rerender approved source at native final resolution without model calls."""
    from src.scene_design import scene_generation as sg
    root=Path(root)
    legacy.verify_quality(root,artifact)
    ref=artifact['manim_render']
    if store.digest(root/ref['code_path'])!=ref['code_sha256']:
        raise WorkflowError('ARTIFACT_CHANGED','Approved source changed')
    design=store.read_json(root/artifact['path'])
    bundle=system.verify(design['system_contract'])
    system.assert_reference(ref,bundle)
    system.validate_ast((root/ref['code_path']).read_text(),bundle)
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
        dict(scene_theme.render_profile((config or sg._config(root))['render'],final=True,bundle=bundle),
              target_duration=design['duration'],collect_layout=True,
              system_contract=bundle,layout_plan=design['layout_plan']))
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
    issues=list(final.get('issues',[]))
    known={o['id'] for o in design['objects']}
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
