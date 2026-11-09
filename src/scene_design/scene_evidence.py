"""Video-bound frame evidence for AI review, independent of planning policies."""
import copy
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from src.shared import _workflow_store as store
from src.shared._workflow_store import WorkflowError
from src.scene_design import scene_theme


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def changed(message):
    raise WorkflowError('ARTIFACT_CHANGED',message)


def verified_sources(root,ref,design,plan):
    if design['layout_plan']!=plan or design['scene_id']!=plan['scene_id']:
        changed('Review plan differs from rendered design')
    if ref.get('plan_sha256')!=fingerprint(plan) or ref.get('job_id')!=design.get('generation_job_id'):
        changed('Video belongs to a different plan or job')
    for key,digest in [('path','sha256'),('code_path','code_sha256'),('metadata_path','metadata_sha256')]:
        if store.digest(store.project_path(root,ref[key]))!=ref[digest]:
            changed('Render source changed: '+key)
    metadata=store.read_json(store.project_path(root,ref['metadata_path']))
    if (metadata.get('status')!='success' or metadata.get('scene_id')!=design['scene_id']
            or metadata.get('version')!=ref['version']):
        changed('Render metadata identity differs')
    for key,path_key in [('video_path','path'),('scene_file','code_path')]:
        if Path(metadata[key]).resolve()!=store.project_path(root,ref[path_key]).resolve():
            changed('Render metadata path differs')
    for key in ('width','height','fps','frame_count','duration_seconds'):
        if metadata['video'][key]!=ref['video'][key]:changed('Video metadata differs')
    return metadata,dict(reference=copy.deepcopy(ref),plan_sha256=fingerprint(plan),
                         design_sha256=fingerprint(design))


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





def build_checks(ref,metadata,design,spans,complete):
    telemetry=metadata['video'].get('layout_telemetry',{})
    # Measurements are feedback for the reviewer, never a hidden planning gate.
    issues=copy.deepcopy(telemetry.get('issues',[]))
    motion=dict(passed=not issues,issues=issues,checked_frames=telemetry.get('checked_frames',0),
        visual_candidates=telemetry.get('candidates',[]),motion_events=telemetry.get('events',[]))
    render=dict(passed=True,issues=[],video=ref['video'],layout_checks=motion,
        target_duration_seconds=design['duration'],duration_tolerance_seconds=2/scene_theme.FPS,
        sampling_complete=complete)
    return motion,render


def seal(root,work,manifest,binding,checks):
    record=dict(binding,manifest=copy.deepcopy(manifest),checks_sha256=fingerprint(checks),
        artifacts=[dict(path=str((work/n).relative_to(root)),sha256=store.digest(work/n))
                   for n in ('layout_telemetry.json','motion_checks.json')])
    path=work/'evidence_binding.json'
    store.atomic_write(path,record)
    manifest['binding']=dict(path=str(path.relative_to(root)),sha256=store.digest(path))


def verify(root,story,design,manifest,checks):
    try:
        anchor=manifest['binding'];path=store.project_path(root,anchor['path'])
        if store.digest(path)!=anchor['sha256']:changed('Evidence binding changed')
        record=store.read_json(path)
        if {k:v for k,v in manifest.items() if k!='binding'}!=record['manifest']:
            changed('Evidence manifest changed')
        if fingerprint(story)!=record['plan_sha256'] or fingerprint(design)!=record['design_sha256']:
            changed('Review inputs changed')
        if fingerprint(checks)!=record['checks_sha256']:changed('Render checks changed')
        verified_sources(root,record['reference'],design,story)
        for item in manifest['frames']+manifest['contact_sheets']+record['artifacts']:
            if store.digest(store.project_path(root,item['path']))!=item['sha256']:
                changed('Review evidence changed')
        if [f for sheet in manifest['contact_sheets'] for f in sheet['frames']]!=manifest['frames']:
            changed('Contact sheets differ from selected frames')
        return record
    except (KeyError,OSError,ValueError,TypeError) as exc:
        changed('Missing/invalid review evidence: '+str(exc))
