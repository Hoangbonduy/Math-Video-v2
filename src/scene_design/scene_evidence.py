"""Local, source-bound encoded evidence. Coverage is availability, never a verdict."""
import copy
import hashlib
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont
from src.shared import _workflow_store as store
from src.shared._workflow_store import WorkflowError
from src.scene_design import system_contract as system, scene_theme


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def changed(message):
    raise WorkflowError('ARTIFACT_CHANGED', message)


def verified_sources(root, ref, design, plan):
    """The caller's render reference is the trust anchor, not the new manifest."""
    bundle = system.verify(design['system_contract'])
    for item in (ref, design, plan):
        system.assert_reference(item, bundle)
    if ref.get('scene_id', design['scene_id']) != design['scene_id']:
        changed('Render reference belongs to another scene')
    if design.get('generation_job_id') and ref.get('job_id') != design['generation_job_id']:
        changed('Render reference belongs to another generation job')
    if ref.get('plan_sha256') and ref['plan_sha256'] != fingerprint(plan):
        changed('Render reference belongs to another layout plan')
    if plan['scene_id'] != design['scene_id'] or design['layout_plan'] != plan:
        changed('Evidence plan/design scene or content mismatch')
    for key, digest in [('path', 'sha256'), ('code_path', 'code_sha256')]:
        path = store.project_path(root, ref[key])
        if not path.is_file() or store.digest(path) != ref[digest]:
            changed('Evidence render source changed: ' + key)
    if not ref.get('metadata_sha256') or not ref.get('version'):
        raise WorkflowError('SCENE_EVIDENCE_REQUIRED',
                            'Legacy render lacks metadata/version binding; supply a locally verified render reference')
    metadata_path = store.project_path(root, ref['metadata_path'])
    if store.digest(metadata_path) != ref['metadata_sha256']:
        changed('Render metadata changed')
    metadata = store.read_json(metadata_path)
    if metadata.get('scene_id') != design['scene_id']:
        changed('Render metadata belongs to another scene')
    if metadata.get('job_id') and metadata['job_id'] != ref.get('job_id'):
        changed('Render metadata belongs to another job')
    if ref.get('version') and metadata.get('version') != ref['version']:
        changed('Render metadata version mismatch')
    for key, path_key in [('video_path', 'path'), ('scene_file', 'code_path')]:
        if metadata.get(key) and Path(metadata[key]).resolve() != store.project_path(root, ref[path_key]).resolve():
            changed('Render metadata source path mismatch: ' + key)
    config = metadata.get('render_config', {})
    if config.get('system_contract'):
        if system.verify(config['system_contract'])['sha256'] != bundle['sha256']:
            changed('Render metadata uses another system contract')
    if config.get('layout_plan') and config['layout_plan'] != plan:
        changed('Render metadata uses another layout plan')
    video = metadata['video']
    for key in ('width', 'height', 'frame_count'):
        if video[key] != ref['video'][key]:
            changed('Render video metadata differs from reference: ' + key)
    if not math.isclose(video['fps'], ref['video']['fps'], abs_tol=.01):
        changed('Render video FPS differs from reference')
    profile = scene_theme.profile(bundle)
    resolution = [video['width'], video['height']]
    if resolution == profile['preview_resolution']:
        kind = 'preview'
    elif resolution == profile['final_resolution'] and config.get('resolution') == resolution:
        # Native render is not evidence of human approval or final audio delivery.
        kind = 'native_test'
    else:
        raise WorkflowError('SCENE_EVIDENCE_REQUIRED', 'No verified preview/native render source')
    if config and config.get('resolution') != resolution:
        changed('Encoded resolution does not match actual render settings')
    telemetry = video.get('layout_telemetry')
    if not telemetry or not telemetry.get('checked_frames'):
        raise WorkflowError('RENDER_FAILED', 'Actual render layout telemetry is missing')
    system.assert_reference(telemetry, bundle)
    if telemetry['checked_frames'] != video['frame_count']:
        changed('Telemetry frame count does not match encoded video')
    return metadata, dict(scene_id=design['scene_id'], version=metadata.get('version'),
        job_id=ref.get('job_id'), source_kind=kind, reference=copy.deepcopy(ref),
        metadata_sha256=store.digest(metadata_path), plan_sha256=fingerprint(plan),
        design_sha256=fingerprint(design), telemetry_sha256=fingerprint(telemetry))


def extract(root, work, ref, metadata, frame_budget=180):
    """Keep every distinct consecutive RGB state, including repeated visits.

    Exact identical holds are losslessly run-length encoded. If the explicit
    payload budget is exceeded, coverage stays incomplete and cannot auto-pass.
    """
    import av
    if type(frame_budget) is not int or frame_budget < 2:
        raise WorkflowError('INVALID_INPUT', 'Evidence frame budget must be an integer >= 2')
    folder = work/'frames'
    folder.mkdir(exist_ok=True)
    video = metadata['video']
    spans, frames = [], []
    count = 0
    with av.open(str(store.project_path(root, ref['path']))) as container:
        for index, frame in enumerate(container.decode(video=0)):
            image = frame.to_image().convert('RGB')
            if list(image.size) != [video['width'], video['height']]:
                changed('Decoded video dimensions differ from render metadata')
            rgb = hashlib.sha256(image.tobytes()).hexdigest()
            count += 1
            if spans and spans[-1]['rgb_sha256'] == rgb:
                spans[-1]['end_frame'] = index
                continue
            spans.append(dict(start_frame=index, end_frame=index, rgb_sha256=rgb))
            # Reserve a slot for the final encoded frame if the budget is full.
            if len(frames) < frame_budget-1:
                path = folder/f'frame_{index:05}.png'
                image.save(path)
                frames.append(dict(frame=index, time=index/video['fps'],
                    path=str(path.relative_to(root)), sha256=store.digest(path), rgb_sha256=rgb))
        if not count:
            raise WorkflowError('RENDER_FAILED', 'Video has no decoded frames')
        if count != video['frame_count']:
            changed('Decoded frame count differs from render metadata')
        last = count-1
        if frames[-1]['frame'] != last:
            path = folder/f'frame_{last:05}.png'
            # The last decoded image may be in a frozen span.
            image.save(path)
            frames.append(dict(frame=last, time=last/video['fps'], path=str(path.relative_to(root)),
                sha256=store.digest(path), rgb_sha256=hashlib.sha256(image.tobytes()).hexdigest()))
    complete = all(any(span['start_frame'] <= item['frame'] <= span['end_frame']
                       and item['rgb_sha256'] == span['rgb_sha256'] for item in frames) for span in spans)
    return frames, spans, complete


def sheets(root, work, frames, resolution):
    width, height = resolution
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
    result = []
    for offset in range(0, len(frames), 6):
        batch = frames[offset:offset+6]
        columns = min(3, len(batch))
        rows = (len(batch)+columns-1)//columns
        canvas = Image.new('RGB', (width*columns, (height+32)*rows), '#F3F6F8')
        draw = ImageDraw.Draw(canvas)
        for index, item in enumerate(batch):
            x, y = (index % columns)*width, (index//columns)*(height+32)
            with Image.open(store.project_path(root, item['path'])) as image:
                canvas.paste(image.convert('RGB'), (x, y+32))
            draw.text((x+8, y+6), f"{item['time']:.3f}s · #{item['frame']}", font=font, fill='#173746')
        path = work/f'contact_sheet_{offset//6:02}.jpg'
        canvas.save(path, quality=95)
        result.append(dict(path=str(path.relative_to(root)), sha256=store.digest(path), frames=batch))
    return result


def coverage(plan, frames, spans, complete, source_kind, requirements=()):
    pairs = {(b['id'], c) for b in plan['beats'] for c in b['criteria']}
    requested = {}
    for row in requirements:
        pair = (row['beat_id'], row['criterion'])
        if pair not in pairs or pair in requested or row['source'] not in ('preview', 'native', 'approved_final'):
            raise WorkflowError('INVALID_INPUT', 'Invalid/duplicate criterion evidence requirement')
        requested[pair] = row['source']
    result = []
    for rule in plan['criterion_rules']:
        required = requested.get((rule['beat_id'], rule['criterion']), 'preview')
        available = {'preview': 'preview', 'native': 'native_test',
                     'approved_final': 'approved_final'}[required] == source_kind
        sufficient = available and (complete or rule['check'] in ('initial_state', 'end_state'))
        result.append(dict(beat_id=rule['beat_id'], criterion=rule['criterion'], check=rule['check'], required_source=required,
            actual_source=source_kind, status='available_for_review' if sufficient else 'insufficient_evidence',
            reason=('Encoded visual states supplied; reviewer must judge meaning/quality' if sufficient else
                    'Required source unavailable' if not available else 'Encoded visual states exceed evidence frame budget'),
            frame_range=[frames[0]['frame'], frames[-1]['frame']], visual_state_count=len(spans)))
    return result



def build_checks(ref, metadata, design, spans, rows):
    """Reconstruct checks exclusively from the verified render and caller policy."""
    bundle = system.verify(design['system_contract'])
    telemetry = metadata['video']['layout_telemetry']
    issues = copy.deepcopy(telemetry['issues'])
    if design.get('layout_plan',{}).get('planning_policy_version'):
        from src.scene_design.plan_validation import post_render_checks
        issues.extend(post_render_checks(design['layout_plan'],bundle))
    known = {obj['id'] for obj in design['objects']}
    missing = known-set(telemetry['object_ids'])
    if missing:
        issues.append(dict(category='layout',time=0,object_ids=sorted(missing),
            problem='Planned semantic objects were not tracked',fix='Register every planned semantic object with track()'))
    for issue in issues:
        issue['object_ids'] = [oid for oid in issue['object_ids'] if oid in known]
    motion = dict(passed=not issues,issues=issues,checked_frames=telemetry['checked_frames'],
        **system.reference(bundle),source='actual Manim Cairo geometry and decoded video RGB',
        early_motion=telemetry['early_motion'],visual_candidates=telemetry.get('candidates',[]),
        motion_events=telemetry.get('events',[]),semantic_states=telemetry.get('semantic_states',[]),
        encoded_visual_states=spans,evidence_coverage=rows)
    profile = scene_theme.profile(bundle)
    render = dict(passed=True,issues=[],video=ref['video'],layout_checks=motion,
        evidence_coverage=rows,evidence_source=source_kind(metadata,bundle),
        target_duration_seconds=design['duration'],
        duration_tolerance_seconds=profile['duration_tolerance_frames']/profile['fps'],
        **system.reference(bundle))
    return motion, render


def source_kind(metadata, bundle):
    resolution = [metadata['video']['width'],metadata['video']['height']]
    return 'preview' if resolution == scene_theme.profile(bundle)['preview_resolution'] else 'native_test'


def verify_derivation(root, story, design, manifest, checks, record, metadata):
    """A resealed envelope is not an authority: reproduce it from the video.

    This scratch extraction never overwrites supplied images. Compare actual PNG
    bytes and reconstructed JPEG panels, not attacker-editable image hashes alone.
    """
    ref = record['reference']
    with TemporaryDirectory(prefix='.verify-evidence-',dir=root) as temporary:
        work = Path(temporary)
        frames,spans,complete = extract(root,work,ref,metadata,manifest['sampling']['limit'])
        fields = ('frame','time','sha256','rgb_sha256')
        actual = [{key:row[key] for key in fields} for row in manifest['frames']]
        expected = [{key:row[key] for key in fields} for row in frames]
        if actual != expected or manifest['encoded_visual_states'] != spans:
            changed('Evidence frames do not match their encoded source video/frame indices')
        if manifest['sampling']['complete'] != complete or manifest['sampling']['review_frame_count'] != len(frames):
            changed('Evidence sampling coverage does not match decoded video')
        if (manifest['scene_id'] != design['scene_id'] or manifest['render_version'] != ref['version']
                or manifest['video_sha256'] != ref['sha256'] or manifest['source_kind'] != record['source_kind']):
            changed('Evidence identity/source fields differ from verified render')
        resolution = [metadata['video']['width'],metadata['video']['height']]
        rebuilt = sheets(root,work,frames,resolution)
        if [row['sha256'] for row in rebuilt] != [row['sha256'] for row in manifest['contact_sheets']]:
            changed('Contact sheet pixels do not match sheets reconstructed from encoded source frames')
        rows = coverage(story,frames,spans,complete,record['source_kind'],design.get('evidence_requirements',[]))
        if manifest['evidence_coverage'] != rows:
            changed('Criterion coverage differs from caller policy and verified video')
        _,expected_checks = build_checks(ref,metadata,design,spans,rows)
        stable_checks = {key:value for key,value in checks.items() if key != 'continuity_evidence'}
        if stable_checks != expected_checks:
            changed('Review checks differ from verified render/coverage')
    # Wrong sources or incomplete states must stop even a direct payload call.
    require_coverage(checks,checks.get('continuity_evidence') or {'status':'missing'})

def seal(root, work, manifest, binding, checks):
    record = dict(binding, manifest=copy.deepcopy(manifest), checks_sha256=fingerprint(checks),
        artifacts=[dict(path=str((work/name).relative_to(root)),sha256=store.digest(work/name))
                   for name in ('layout_telemetry.json','motion_checks.json')])
    path = work/'evidence_binding.json'
    store.atomic_write(path, record)
    manifest['binding'] = dict(path=str(path.relative_to(root)), sha256=store.digest(path))
    return manifest


def verify(root, story, design, manifest, checks):
    """Check the entire evidence closure again immediately before payload creation."""
    try:
        anchor = manifest['binding']
        path = store.project_path(root, anchor['path'])
        if store.digest(path) != anchor['sha256']:
            changed('Evidence binding changed')
        record = store.read_json(path)
        current = {key: value for key, value in manifest.items() if key != 'binding'}
        if current != record['manifest']:
            changed('Evidence manifest/frame/sheet records changed after extraction')
        if fingerprint(design) != record['design_sha256'] or fingerprint(story) != record['plan_sha256']:
            changed('Review plan/design changed after extraction')
        # Continuity is prepared separately and verified by contract_review.
        stable_checks = {key: value for key, value in checks.items() if key != 'continuity_evidence'}
        if fingerprint(stable_checks) != record['checks_sha256']:
            changed('Review checks or telemetry changed after extraction')
        metadata, source = verified_sources(root, record['reference'], design, story)
        for key in ('metadata_sha256', 'telemetry_sha256', 'source_kind'):
            if source[key] != record[key]:
                changed('Evidence source binding changed: ' + key)
        for item in manifest['frames'] + manifest['contact_sheets'] + record['artifacts']:
            if store.digest(store.project_path(root, item['path'])) != item['sha256']:
                changed('Evidence image changed: ' + item['path'])
        if [f for sheet in manifest['contact_sheets'] for f in sheet['frames']] != manifest['frames']:
            changed('Contact sheets are not bound to the selected frames')
        verify_derivation(root,story,design,manifest,checks,record,metadata)
    except (KeyError, OSError, ValueError, TypeError) as exc:
        raise WorkflowError('ARTIFACT_CHANGED', 'Missing/invalid evidence binding: ' + str(exc)) from exc
    return record


def require_review_evidence(review):
    if any(row.get('status') == 'insufficient_evidence' for row in review['criteria_results']):
        raise WorkflowError('SCENE_EVIDENCE_REQUIRED', 'Applicable criteria need evidence; do not blindly regenerate code')


def require_coverage(checks, continuity):
    missing = [row for row in checks.get('evidence_coverage', [])
               if row['status'] == 'insufficient_evidence'
               and not (row['check'] == 'cross_scene_continuity' and continuity.get('status') != 'verified')]
    if missing:
        raise WorkflowError('SCENE_EVIDENCE_REQUIRED',
                            'Required video states/source missing; preserve code and supply evidence')
