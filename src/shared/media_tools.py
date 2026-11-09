"""Bounded local media processes, using the active video environment."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from src.shared._workflow_store import WorkflowError


def binary(name):
    local=Path(sys.executable).with_name(name)
    result=str(local) if local.is_file() else shutil.which(name)
    if not result: raise WorkflowError('DEPENDENCY_ERROR',f'Missing {name}; use the video environment')
    return result


def run(args,timeout=600):
    try:
        env=os.environ.copy()
        for key in list(env):
            if key.endswith("API_KEY"):env.pop(key,None)
        from src.shared.task_control import current_control, checkpoint, watch_process
        checkpoint()
        if current_control():
            process=subprocess.Popen(args,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=(os.name=='posix'))
            try:
                with watch_process(process):
                    stdout,stderr=process.communicate(timeout=timeout)
                result=subprocess.CompletedProcess(args,process.returncode,stdout,stderr)
            finally:
                if process.poll() is None:
                    process.kill();process.wait()
        else:
            result=subprocess.run(args,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    except subprocess.TimeoutExpired: raise WorkflowError('MEDIA_TIMEOUT','Media process timed out') from None
    if result.returncode: raise WorkflowError('MEDIA_FAILED',result.stderr.decode(errors='replace')[-2000:])
    return result.stdout


def probe(path):
    return json.loads(run([binary('ffprobe'),'-v','error','-show_format','-show_streams','-of','json',str(path)]))


def duration(path):
    data = probe(path)
    try:
        seconds = float(data.get('format', {}).get('duration'))
    except (TypeError, ValueError):
        raise WorkflowError('MEDIA_DURATION', 'Media has no measurable duration') from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise WorkflowError('MEDIA_DURATION', 'Media duration must be finite and positive')
    return seconds


def validate(path,audio=True,resolution=None,fps=None):
    data=probe(path); streams=data['streams']; videos=[s for s in streams if s['codec_type']=='video']; sounds=[s for s in streams if s['codec_type']=='audio']
    if not videos or bool(sounds)!=audio: raise WorkflowError('INVALID_VIDEO','Unexpected audio/video streams')
    v=videos[0]
    if resolution and [v['width'],v['height']]!=resolution: raise WorkflowError('INVALID_VIDEO','Wrong resolution')
    if fps:
        a,b=map(float,v['avg_frame_rate'].split('/'))
        if abs(a/b-fps)>.01: raise WorkflowError('INVALID_VIDEO','Wrong frame rate')
    run([binary('ffmpeg'),'-v','error','-i',str(path),'-f','null','-'])
    if audio:
        vd=float(v.get('duration',data['format']['duration'])); ad=float(sounds[0].get('duration',data['format']['duration']))
        if abs(vd-ad)>1/(fps or 30)+.001: raise WorkflowError('AV_DRIFT','Audio/video duration mismatch')
    return data
