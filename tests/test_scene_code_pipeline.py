"""Offline providers and real render tests for the draft-first scene loop."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from src.scene_design import scene_code_pipeline as pipeline, scene_theme, scene_generation as sg
from src.scene_design.render import _settings
from src.shared import _workflow_store as store
from src.shared.ai_config import get_model
from src.shared.job_session import Session
from tests.ai_support import FakeCodex
from tests.scene_v2_support import VisionRouter

SOURCE="""from manim import *
from manim_kit import vn_text, track, finish_scene
class GeneratedScene(Scene):
    def construct(self):
        self.camera.background_color = '#0D1726'
        title = track(self, 'title', vn_text('Chuyển động',28).move_to([0,5,0]),role='text')
        point = track(self, 'point', Dot([-1,0,0],color='#56DFC5'),role='shape')
        self.add(title,point)
        self.play(point.animate.shift(2*RIGHT),run_time=.8,rate_func=linear)
        finish_scene(self,1)
"""
BROKEN=SOURCE.replace("self.add(title,point)","self.add(title,point)\n        raise ValueError('fixture render failure')")

def visual_plan():
    return dict(scene_id='s1',narration='Một điểm chuyển động.',duration=1,
        goal='Theo dõi chuyển động.',visual_strategy='Một điểm và tiêu đề.',
        beats=[dict(id='move',start=0,end=1,narration_excerpt='Một điểm chuyển động.',
            show='Điểm và tiêu đề.',motion='Điểm đi sang phải.',understand='Vị trí thay đổi.',
            criteria=['Điểm di chuyển sang phải.'])],
        objects=[dict(id='title',kind='text'),dict(id='point',kind='shape')],groups=[],
        required_apis=['Dot','Text'],recipe_ids=['explanatory_motion'])

def issue(problem='Point motion needs correction'):
    return dict(category='meaning',beat_id='move',object_ids=['point'],time=.5,
                problem=problem,fix='Repair the actual motion in code')

class CodeRouter(FakeCodex):
    def __init__(self,sources=None,plan=None):
        super().__init__();self.sources=sources or [SOURCE];self.plan=plan;self.code_count=0
    def complete(self,payload):
        self.requests.append(copy.deepcopy(payload))
        props=payload['schema']['properties']
        if 'beats' in props:
            context=json.loads(payload['messages'][1]['content'])
            result=copy.deepcopy(self.plan or visual_plan())
            result.update(scene_id=context['scene']['scene_id'],narration=context['scene']['narration'],
                          duration=context['target_seconds'])
            result['beats'][0].update(narration_excerpt=result['narration'],end=result['duration'])
        elif 'source' in props:
            result=dict(source=self.sources[min(self.code_count,len(self.sources)-1)],requires_design_change=False,reason='')
            self.code_count+=1
        else:raise AssertionError(props)
        return dict(id='direct-'+str(len(self.requests)),model=get_model(),
            usage=dict(billing_source='codex_subscription',prompt_tokens=100,completion_tokens=100,cost=None),
            choices=[dict(finish_reason='stop',message=dict(content=json.dumps(result,ensure_ascii=False)))])

def run_pipeline(root,router=None,repairs=2,vision=None):
    router=router or CodeRouter();vision=vision or VisionRouter()
    directory=root/'generation'/'direct';directory.mkdir(parents=True)
    job=dict(job_id='direct',input=dict(stage='scene_design',max_repairs=repairs),
             calls=[],status='working',pricing=router.preflight())
    session=Session(directory,job,router,None,budget_usd=.5,other_used=0)
    context=dict(scene=dict(scene_id='s1',narration=visual_plan()['narration']),
        target_seconds=1,config=copy.deepcopy(sg.DEFAULT_CONFIG),script={},brief={})
    with patch('src.scene_design.scene_vision.CLIENT_FACTORY',return_value=vision):
        result=pipeline.generate(root,directory,session,context)
    return result,session,context,vision

def test_preview_and_final_have_identical_logical_camera():
    a,_=_settings(scene_theme.render_profile(sg.DEFAULT_CONFIG['render']))
    b,_=_settings(scene_theme.render_profile(sg.DEFAULT_CONFIG['render'],final=True))
    assert (a['frame_width'],a['frame_height'])==(9,16)==(b['frame_width'],b['frame_height'])
    assert a['frame_rate']==b['frame_rate']==30
    assert b['pixel_width']==a['pixel_width']*3

def test_real_render_review_and_native_final(tmp_path):
    (path,extra),session,context,vision=run_pipeline(tmp_path)
    assert extra['quality_passed']
    ref=extra['manim_render']
    assert [ref['video']['width'],ref['video']['height']]==[360,640]
    work=path.parent/'round_00'
    evidence=store.read_json(work/'evidence.json')
    assert evidence['sampling']['complete'] and len(evidence['frames'])>5
    assert len(vision.requests)==1
    quality=store.read_json(path.parent/'quality.json')
    assert quality['human_approval_required'] is True
    assert session.job['progress']=='ready_for_review'
    artifact=dict(extra,path=str(path.relative_to(tmp_path)),sha256=store.digest(path))
    final=pipeline.render_final(tmp_path,artifact,context['config'])
    assert final['status']=='success',final
    assert store.read_json(Path(final['log_path']).with_suffix('.json'))['video']['width']==1080
    before=len(session.job['calls'])
    with patch('src.scene_design.scene_vision.CLIENT_FACTORY',side_effect=AssertionError('No inference on resume')):
        assert pipeline.generate(tmp_path,path.parent,session,context)[0]==path
    assert len(session.job['calls'])==before
    # A modified frame cannot be reviewed or approved under the old evidence hash.
    frame=store.project_path(tmp_path,evidence['frames'][0]['path'])
    frame.write_bytes(b'changed')
    with pytest.raises(store.WorkflowError,match='ARTIFACT_CHANGED'):
        from src.scene_design.scene_pipeline import verify_quality
        verify_quality(tmp_path,artifact)

def test_two_visual_repairs_then_return_unpassed_draft(tmp_path):
    from src.shared import workflow as wf
    from src.shared.review import record_review
    wf.create_project(tmp_path,'Moving point')
    script=tmp_path/'input_script.md';script.write_text('Approved narration')
    wf.submit_artifact(tmp_path,'script','v001',script,scene_ids=['s1','s2'])
    record_review(tmp_path,'script','v001','approve')
    router=CodeRouter();vision=VisionRouter([[issue()]])
    (path,extra),session,context,vision=run_pipeline(tmp_path,router,vision=vision)
    assert router.code_count==3 and len(vision.requests)==3
    assert not extra['quality_passed']
    quality=store.read_json(path.parent/'quality.json')
    assert quality['repairs']==2 and quality['issues']
    assert session.job['draft']['review']['passed'] is False
    assert len(list(path.parent.glob('round_*')))==3
    assert (tmp_path/extra['manim_render']['path']).is_file()
    assert [c['phase'] for c in session.job['calls']].count('v3_plan_0')==1
    assert 'v3_plan_1' not in [c['phase'] for c in session.job['calls']]

    # Register the stopped draft, preserving its failed AI verdict.
    wf.submit_artifact(tmp_path,'scene_design','v001',path,scene_id='s1')
    with store.locked_project(tmp_path) as root:
        project,reviews=wf._load(root)
        artifact=wf._latest(project,'scene_design','s1')
        artifact.update(extra,origin='ai_scene',job_id=session.job['job_id'],bundle=sg._bundle(root,[path,path.parent/'quality.json']))
        ref=extra['manim_render']
        project.setdefault('design_previews',{})['s1:v001']=dict(ref,render_version=ref['version'],
            version='v001',design_sha256=artifact['sha256'])
        assert wf._request(reviews,artifact)['status']=='pending'
        wf._save(root,project,reviews)
    before=len(session.job['calls'])
    with patch('src.scene_design.scene_vision.CLIENT_FACTORY',side_effect=AssertionError('No automatic restart')):
        pipeline.generate(tmp_path,path.parent,session,context)
    assert len(session.job['calls'])==before
    # The explicit human decision may approve a draft even when AI still flags errors.
    record_review(tmp_path,'scene_design','v001','approve',scene_id='s1')
    project,reviews=wf._load(tmp_path)
    assert wf._request(reviews,wf._latest(project,'scene_design','s1'))['status']=='approved'
    assert project['stage']=='scene_design'  # s2 is still unreviewed.

def test_render_and_visual_errors_share_the_two_repair_budget(tmp_path):
    router=CodeRouter([BROKEN,SOURCE,SOURCE])
    vision=VisionRouter([[issue()],[]])
    (path,extra),session,context,vision=run_pipeline(tmp_path,router,vision=vision)
    assert router.code_count==3 and len(vision.requests)==2
    assert extra['quality_passed']
    assert store.read_json(path.parent/'round_00/result.json')['issues']
    assert session.job['repair_round']==2

def test_keep_previous_draft_if_later_repairs_fail_to_render(tmp_path):
    router=CodeRouter([SOURCE,BROKEN,BROKEN]);vision=VisionRouter([[issue()]])
    (path,extra),session,context,vision=run_pipeline(tmp_path,router,vision=vision)
    assert not extra['quality_passed']
    assert len(vision.requests)==1 and router.code_count==3
    draft=store.read_json(tmp_path/session.job['draft']['path'])
    assert draft['design_path'].endswith('round_00/design.json')
    assert extra['manim_render']['sha256']==draft['reference']['sha256']
    quality=store.read_json(path.parent/'quality.json')
    assert any('fixture render failure' in i['problem'] for i in quality['issues'])
    assert any(i['problem']==issue()['problem'] for i in quality['issues'])

def test_all_render_failures_stop_without_claiming_video_exists(tmp_path):
    router=CodeRouter([BROKEN])
    with pytest.raises(store.WorkflowError,match='No playable draft'):
        run_pipeline(tmp_path,router)
    job=store.read_json(tmp_path/'generation/direct/job.json')
    assert router.code_count==3 and job['repair_round']==2 and not job.get('draft')

def test_invalid_review_preserves_playable_draft_and_error(tmp_path):
    with patch('src.scene_design.scene_pipeline._review',
               side_effect=store.WorkflowError('INVALID_VISUAL_REVIEW','fixture invalid review')):
        (path,extra),session,_,vision=run_pipeline(tmp_path,repairs=0)
    assert not extra['quality_passed']
    assert (tmp_path/extra['manim_render']['path']).is_file()
    assert store.read_json(path.parent/'quality.json')['issues'][0]['owner']=='vision_reviewer'

def test_visual_measurements_are_sent_to_ai_without_blocking_render(tmp_path):
    bad=SOURCE.replace(".move_to([0,5,0])",".move_to([4.4,5,0])")
    vision=VisionRouter([[issue('Title is clipped')]])
    (path,extra),session,_,_=run_pipeline(tmp_path,CodeRouter([bad]),repairs=0,vision=vision)
    assert (tmp_path/extra['manim_render']['path']).is_file()
    payload=json.loads(vision.requests[0]['messages'][1]['content'][0]['text'])
    assert payload['render_checks']['layout_checks']['issues']
    assert not extra['quality_passed']

def test_runtime_lookup_reads_local_manim_docs():
    from src.scene_design import scene_references
    references=scene_references.lookup(['manim.Polygon','manim_kit.vn_text'],['group_motion'])
    assert not references['missing']
    assert any(r['path'].endswith('/Polygon.md') and r['content'] for r in references['references'])

def test_default_repairs_are_two_including_trial(monkeypatch):
    monkeypatch.setenv('SCENE_MAX_REPAIRS','99')
    monkeypatch.setenv('SCENE_TRIAL_MAX_REPAIRS','0')
    assert sg.repair_limit()==sg.repair_limit(True)==2

def test_full_generation_registers_pending_human_review_with_errors(tmp_path):
    from src.shared import workflow as wf
    from src.shared.review import record_review
    wf.create_project(tmp_path,'Moving point')
    script=tmp_path/'input_script.md';script.write_text('Approved narration')
    wf.submit_artifact(tmp_path,'script','v001',script,scene_ids=['s1','s2'])
    # Four units out of 120 give scene s1 exactly one second of a measured 30s script.
    payload=dict(script=dict(scenes=[
        dict(scene_id='s1',narration=visual_plan()['narration'],visual_intent='Point moves'),
        dict(scene_id='s2',narration=' '.join(['next']*116),visual_intent='Next scene')]),brief={})
    store.atomic_write(tmp_path/'input_script.json',payload)
    store.atomic_write(tmp_path/'input_research.json',{})
    store.atomic_write(tmp_path/'input_generation.json',{})
    with store.locked_project(tmp_path) as root:
        project,reviews=wf._load(root)
        artifact=wf._latest(project,'script',None)
        artifact.update(origin='ai',bundle={'script.json':dict(path='input_script.json',
            sha256=store.digest(tmp_path/'input_script.json')),
            'research.json':dict(path='input_research.json',sha256=store.digest(tmp_path/'input_research.json')),
            'generation.json':dict(path='input_generation.json',sha256=store.digest(tmp_path/'input_generation.json'))})
        wf._save(root,project,reviews)
    record_review(tmp_path,'script','v001','approve',read_seconds=30)
    router=CodeRouter([SOURCE,BROKEN,BROKEN]);vision=VisionRouter([[issue()]])
    with patch.object(sg,'CLIENT_FACTORY',return_value=router), \
         patch('src.scene_design.scene_vision.CLIENT_FACTORY',return_value=vision):
        state=sg.run_scenes(tmp_path,scene_id='s1',trial_mode=True)
    artifact=next(a for a in state['artifacts'] if a['stage']=='scene_design')
    assert artifact['quality_passed'] is False
    assert any(r['scene_id']=='s1' and r['stage']=='scene_design' for r in state['pending_reviews'])
    assert not state['integrity_issues']
    job=state['scene_generation']['jobs'][-1]
    assert job['status']=='awaiting_review' and job['max_repairs']==2
    assert any('fixture render failure' in i['problem'] for i in job['quality_issues'])
    draft=store.read_json(tmp_path/job['draft']['path'])
    assert (tmp_path/draft['reference']['path']).is_file()
    record_review(tmp_path,'scene_design',artifact['version'],'approve',scene_id='s1')
    assert len(router.requests)==4 and len(vision.requests)==1

def test_native_render_preserves_human_reviewed_layout_despite_existing_warnings():
    warning=dict(problem='Existing readability warning')
    telemetry=dict(checked_frames=30,object_ids=['title'],issues=[warning],
        samples=[dict(frame=0,objects=dict(title=dict(box=[0,1,0,1])))])
    design=dict(objects=[dict(id='title'),dict(id='untracked_planned_piece')])
    assert pipeline.compare_layouts(telemetry,copy.deepcopy(telemetry),design)['passed']
    changed=copy.deepcopy(telemetry)
    changed['samples'][0]['objects']['title']['box']=[1,2,0,1]
    assert not pipeline.compare_layouts(telemetry,changed,design)['passed']
