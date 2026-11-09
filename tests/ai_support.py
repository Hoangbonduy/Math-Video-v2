"""Offline provider and public-source fixtures; never contacts a service."""

import copy
import hashlib
import json

from src.shared.ai_config import get_model
from src.shared.codex_client import CodexClient


SOURCE_TEXT = ('A derivative describes the instantaneous rate of change. '
               'Earth rotates on its axis, so locations face toward the Sun or away from it. ' * 8)


def valid_script():
    words = ('Bạn hãy hình dung một thay đổi quen thuộc quanh mình. Ta cùng quan sát ví dụ này thật chậm '
             'để nhận ra điều quan trọng và nối kiến thức với trải nghiệm mỗi ngày. ').split()
    narration = ' '.join((words * 8)[:140])
    parts = narration.split()
    return dict(title='Một ý tưởng qua ví dụ trực quan', main_idea='Hiểu thay đổi qua một ví dụ',
                claims=[dict(claim_id='claim_01', statement='Một phát biểu có nguồn hỗ trợ',
                             evidence=[dict(source_id='source_01', quote='A derivative describes the instantaneous rate of change.')])],
                scenes=[dict(scene_id='scene_01', narration=' '.join(parts[:70]), visual_intent='Một điểm và mũi tên', claim_refs=['claim_01']),
                        dict(scene_id='scene_02', narration=' '.join(parts[70:]), visual_intent='So sánh trước và sau', claim_refs=['claim_01'])])


def fake_fetch(url):
    return dict(url=url, final_url=url, title='Authored educational source', text=SOURCE_TEXT,
                sha256=hashlib.sha256(SOURCE_TEXT.encode()).hexdigest(), raw_sha256='a' * 64,
                retrieved_at='2026-10-23T00:00:00+00:00', truncated=False, status='success')


class FakeCodex(CodexClient):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.preflights = 0
        self.failures = []
        self.invalid_drafts = 0
        self.needs_research = False
        self.missing_usage = False
        self.wrong_model = False
        self.before_complete = None

    def preflight(self, *, search=True):
        self.preflights += 1
        return dict(model=get_model(),provider='Fake Codex',billing_source='codex_subscription',
                    checked_at='2026-10-23T00:00:00+00:00')

    def search_pricing(self):
        return dict(billing_source='codex_subscription')

    def complete(self, payload):
        self.requests.append(copy.deepcopy(payload))
        if self.before_complete:
            self.before_complete(payload)
        if self.failures:
            raise self.failures.pop(0)
        annotations = []
        if payload.get('search'):
            text = 'Sources retrieved with the search tool.'
            prefix = 'additional' if self.needs_research else 'original'
            annotations = [dict(type='url_citation', url_citation=dict(url=f'https://university.example/{prefix}/{i}',
                           title='Educational source', content=SOURCE_TEXT[:300])) for i in range(4)]
        elif 'needs_research' in payload['schema']['properties']:
            text = json.dumps(dict(needs_research=self.needs_research, reason='Compare feedback against saved evidence', search_query='educational topic'))
        elif 'all_passed' in payload['schema']['properties']:
            context=json.loads(payload['messages'][1]['content'])
            narration=context['draft']['narration']
            rules=payload['schema']['properties']['checks']['items']['properties']['rule']['enum']
            text=json.dumps(dict(all_passed=True,checks=[dict(rule=rule,passed=True,reason='Offline review') for rule in rules],
                                 narration=narration),ensure_ascii=False)
        else:
            if self.invalid_drafts:
                self.invalid_drafts -= 1
                text = '{bad json'
            else:
                script = valid_script()
                # Keep the two-scene, 140-unit fixture used by downstream design tests,
                # with distinct sentences instead of the old repeated padding.
                sentences = [
                    'Một chiếc xe có thể chạy nhanh dần dù quãng đường trước mắt vẫn ngắn và ta muốn biết ngay lúc này nó đang chuyển động nhanh tới mức nào để hiểu rõ tình huống hơn',
                    'Nhưng lấy cả quãng đường chia cho toàn bộ thời gian chỉ cho biết tốc độ trung bình của hành trình nên kết quả đó chưa mô tả được đúng khoảnh khắc đang xét ở đây',
                    'Rồi ta thu nhỏ khoảng thời gian quanh khoảnh khắc ấy và quan sát quãng đường tương ứng để thấy phép so sánh đang dần tiến tới một giá trị phản ánh chuyển động tức thời',
                    'Vậy đạo hàm giúp diễn tả tốc độ thay đổi ngay tại một thời điểm qua giới hạn của những khoảng nhỏ dần và mở ra cách hiểu chuyển động bằng hình ảnh quen thuộc này',
                ]
                sentences = [' '.join(sentence.split()[:35]) + '.' for sentence in sentences]
                assert all(len(sentence.split()) == 35 for sentence in sentences)
                for index, scene in enumerate(script['scenes']):
                    scene['narration'] = ' '.join(sentences[index*2:index*2+2])

                context=json.loads(payload['messages'][1]['content']) if len(payload.get('messages',[]))>1 else {}
                if 'narration' in payload['schema']['properties']:
                    script=dict(title=script['title'],main_idea=script['main_idea'],claims=script['claims'],
                                narration=' '.join(scene['narration'] for scene in script['scenes']))
                elif 'scenes' in payload['schema']['properties']:
                    draft=context.get('narration_draft')
                    if draft:
                        from src.idea.narration import _sentences
                        lines=_sentences(draft['narration'])
                        script.update(title=draft['title'],main_idea=draft['main_idea'],claims=draft['claims'])
                        script['scenes']=[dict(scene_id=f's{i//2+1}',narration=' '.join(lines[i:i+2]),
                            visual_intent='Point moves',claim_refs=['claim_01']) for i in range(0,len(lines),2)]
                    for i,scene in enumerate(script['scenes'],1):
                        scene['scene_id']=f's{i}'
                    if 'global_visuals' in payload['schema']['properties']:
                        from src.idea.test_guideline_pipeline import visual_script_fixture
                        script=visual_script_fixture(script)
                text = json.dumps(script, ensure_ascii=False)
        usage = dict(prompt_tokens=100, completion_tokens=200, cost=None,billing_source='codex_subscription')
        if payload.get('search'):
            usage['server_tool_use_details'] = dict(web_search_requests=1, tool_calls_requested=1, tool_calls_executed=1)
        if self.missing_usage:
            usage.pop('prompt_tokens')
        codex=dict(search_performed=bool(payload.get('search')),search_count=1 if payload.get('search') else 0,
            sources=[dict(url=a['url_citation']['url'],title=a['url_citation']['title'],
                          excerpt=a['url_citation']['content']) for a in annotations])
        return dict(codex=codex,id=f'fake-response-{len(self.requests)}', model='other/model' if self.wrong_model else get_model(),
                    usage=usage, choices=[dict(finish_reason='stop', message=dict(content=text, annotations=annotations))])
