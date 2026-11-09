"""Shared visual declarations and the three-part scene handoff."""

import re

from src.shared._workflow_store import WorkflowError

GLOBAL_LABELS = (
    ('objects', 'Đối tượng dùng chung'),
    ('layout', 'Bố cục, góc nhìn và phong cách hình ảnh'),
    ('math', 'Hệ tọa độ, đơn vị, thông số và quan hệ toán học'),
    ('continuity', 'Quy tắc kế thừa trạng thái và ràng buộc xuyên suốt'),
)
SCENE_HEADINGS = (
    '1. Kế thừa & thay đổi',
    '2. Timeline hình ảnh',
    '3. Tiêu chí đạt',
)

VISUAL_INSTRUCTIONS = """
KHAI BÁO TOÀN CỤC — chỉ một lần ở đầu kịch bản, trong global_visuals:
Không chép phiên bản hoặc SHA-256 của system_contract vào global_visuals hay visual_intent.
Đó là metadata snapshot do bộ điều phối quản lý theo job, không phải nội dung kịch bản.
Vẫn ghi đầy đủ các ràng buộc thực tế về hình học, HUD, dữ kiện và thứ tự tiết lộ.
Scene Slicer giao ý đồ hình ảnh, không yêu cầu người dùng đã duyệt sẵn mọi đỉnh đa giác,
đường cắt phụ hay ma trận biến đổi. Planner có trách nhiệm thiết kế các chi tiết thực thi
còn mở trong phạm vi dữ kiện và ý đồ đã duyệt. Phân biệt lựa chọn thiết kế với đổi dữ kiện.
Không trả CONTRACT_CONFLICT, “chưa xác định” hoặc “trả về khâu lập kế hoạch” để lấp chỗ
cho global_visuals, timeline, trạng thái cuối và tiêu chí đạt. Tiêu chí phải là kết quả
cần đạt, không phải lời từ chối xác minh. Không thay toàn bộ hướng dẫn bằng báo lỗi.
Nếu phát hiện yêu cầu thực sự mâu thuẫn, nêu các yêu cầu cụ thể xung đột; không giả vờ
đã tạo bản bàn giao hoàn chỉnh. Ngoại lệ ảo giác cần nêu rõ trong visual_intent/global_visuals
khi ý tưởng đã xác định đó là ảo giác; vẫn giữ vật liệu thật và thứ tự tiết lộ.
- objects: tên/ID ổn định, cấu tạo, số lượng, kích thước và trạng thái ban đầu của đối tượng dùng chung.
- layout: bố cục, góc nhìn và phong cách hình ảnh.
- math: hệ tọa độ, đơn vị, thông số và quan hệ toán học dùng chung.
- continuity: quy tắc kế thừa trạng thái và các ràng buộc xuyên suốt.
Ghi cụ thể theo nội dung, không chép lại chỗ trống của mẫu. Nếu một mục không áp dụng,
ghi rõ lý do; không bịa dữ kiện. Không lặp khai báo toàn cục dưới từng lời đọc.

Mỗi scene.visual_intent là chuỗi nhiều dòng với đúng ba tiêu đề, theo thứ tự:
1. Kế thừa & thay đổi
Kế thừa: Khởi tạo theo khai báo toàn cục nếu là s1; các cảnh sau lấy Trạng thái cuối
cảnh trước (ghi ID cảnh trước cùng trạng thái cụ thể).
Thay đổi: Đối tượng mới kèm cấu tạo, kích thước / Đối tượng bị bỏ / Thay đổi bố cục /
Trạng thái cũ được gọi lại / Giữ nguyên. Ghi thay đổi thực tế; không liệt kê mọi lựa chọn.
2. Timeline hình ảnh
- Mốc giây CỤC BỘ từ 0 của cảnh hoặc mốc lời đọc/sự kiện → Đối tượng/nhóm →
Thao tác + thông số/đích đến → Chữ, số nguyên văn và điểm nhấn đồng thời nếu có
(nếu không có, ghi Không có) → Kết quả.
Mỗi sự kiện trên một dòng; không dùng giây toàn video làm giây cục bộ.
Nếu chữ nguyên văn chứa ký hiệu →, đặt toàn bộ chữ đó trong dấu ngoặc kép.
Kết cảnh: Vị trí, trạng thái và giá trị cụ thể của các đối tượng giữ sang cảnh sau.
3. Tiêu chí đạt
- Kết quả hình học, chuyển động hoặc hiển thị cụ thể có thể kiểm tra.
- Điều kiện riêng về ý nghĩa, thứ tự hoặc thời điểm tiết lộ thông tin.

Giữ danh tính và kích thước đối tượng nhất quán; mọi reset/gọi lại trạng thái cũ phải
được khai báo ở Thay đổi. Phân biệt thay đổi camera/bố cục với thay đổi vật liệu.
Không tự dựng lại trạng thái ban đầu giữa các cảnh. Mô tả mốc và đích đến đủ rõ để
bước thiết kế cảnh thực hiện; không dùng “trượt một nấc” mà thiếu khoảng dịch.
"""


def _fail(message):
    raise WorkflowError('INVALID_SCRIPT', 'Hình ảnh: ' + message)


def scene_sections(text):
    """Split only the canonical format; old free-form scripts remain readable."""
    pattern = r'(?m)^(' + '|'.join(re.escape(h) for h in SCENE_HEADINGS) + r')\s*$'
    parts = re.split(pattern, text.strip())
    if len(parts) != 7 or parts[0].strip() or tuple(parts[1::2]) != SCENE_HEADINGS:
        _fail('visual_intent phải có đúng 3 mục: ' + '; '.join(SCENE_HEADINGS))
    bodies = [part.strip() for part in parts[2::2]]
    if any(not body for body in bodies):
        _fail('Mỗi mục hình ảnh phải có nội dung')
    return bodies


def _field(body, label):
    match = re.search(r'(?m)^' + re.escape(label) + r':[^\S\n]*(\S[^\n]*)$', body)
    if not match:
        _fail('Thiếu nội dung ' + label + ':')
    return match[1]


def timeline_cells(line):
    """Allow literal arrows inside quoted on-screen captions."""
    cells, current, closing = [], [], None
    for char in line.strip().removeprefix('- '):
        if closing:
            current.append(char)
            if char == closing:
                closing = None
        elif char in ('"', '“'):
            closing = '"' if char == '"' else '”'
            current.append(char)
        elif char == '→':
            cells.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append(''.join(current).strip())
    return cells


def validate_visuals(script):
    """Validate the handoff format, without pretending to prove its geometry."""
    for index, scene in enumerate(script['scenes']):
        inheritance, timeline, criteria = scene_sections(scene['visual_intent'])
        inherited = _field(inheritance, 'Kế thừa')
        _field(inheritance, 'Thay đổi')
        if index == 0:
            if 'khai báo toàn cục' not in inherited.casefold():
                _fail('s1 phải khởi tạo theo khai báo toàn cục')
        else:
            previous = script['scenes'][index - 1]['scene_id']
            if not re.search(r'(?<!\w)' + re.escape(previous) + r'(?!\w)', inherited):
                _fail(scene['scene_id'] + ': Kế thừa phải chỉ rõ trạng thái cuối ' + previous)
        _field(timeline, 'Kết cảnh')
        events = [line.strip().removeprefix('- ').strip() for line in timeline.splitlines()
                  if line.strip() and not line.startswith('Kết cảnh:')]
        if not events or any(len(timeline_cells(line)) != 5 or
                             any(not cell for cell in timeline_cells(line)) for line in events):
            _fail(scene['scene_id'] + ': mỗi mốc timeline cần 5 phần ngăn bằng →')
        checks = [line[2:].strip() for line in criteria.splitlines() if line.startswith('- ')]
        if len(checks) < 2 or any(not check for check in checks):
            _fail(scene['scene_id'] + ': cần tiêu chí kết quả và điều kiện ý nghĩa/thứ tự/thời điểm')


def global_markdown(script):
    if 'global_visuals' not in script:
        return []
    lines = ['## Khai báo toàn cục', '']
    for key, label in GLOBAL_LABELS:
        lines += ['### ' + label, '', script['global_visuals'][key], '']
    return lines


def scene_markdown(visual):
    try:
        bodies = scene_sections(visual)
    except WorkflowError:
        return visual
    blocks = []
    for heading, body in zip(SCENE_HEADINGS, bodies):
        # Blank lines keep state fields separate when rendered as Markdown.
        lines = body.splitlines()
        formatted = []
        for line in lines:
            if line.startswith(('Kế thừa:', 'Thay đổi:', 'Kết cảnh:')) and formatted:
                formatted.append('')
            formatted.append(line)
        blocks.append('#### ' + heading + '\n\n' + '\n'.join(formatted))
    return '\n\n'.join(blocks)


def visual_readiness(script):
    """Reject diagnostic placeholders, not intentionally hidden visual states."""
    if 'global_visuals' not in script:
        return dict(ready=True,issues=[])
    issues=[]
    def inspect(path,text):
        if not isinstance(text,str):
            return
        # These are refusal/status fields, never an on-screen caption. Do not
        # flag intentional instructions such as "chua tiet lo dap an".
        refusal=(re.search(r'^\s*CONTRACT_CONFLICT(?:\s*:|\s*$)',text,re.I)
                 or re.search(r'chưa (?:thể )?(?:xác định|xác minh|lập|có đủ dữ kiện)',text,re.I)
                 or re.search(r'(?:^|[.!]\s+)Trả về khâu lập kế hoạch',text,re.I))
        if refusal:
            issues.append(dict(field=path,owner='scene_slicer',
                problem='Bản bàn giao chứa trạng thái từ chối/chưa hoàn tất thay cho mô tả hình ảnh.'))
    for key,text in script['global_visuals'].items():
        inspect('global_visuals.'+key,text)
    for scene in script.get('scenes',[]):
        sid=scene.get('scene_id','?')
        try:
            inheritance,timeline,criteria=scene_sections(scene['visual_intent'])
        except (KeyError,WorkflowError):
            issues.append(dict(field=sid+'.visual_intent',owner='scene_slicer',
                problem='Bản bàn giao hình ảnh thiếu cấu trúc.'))
            continue
        inspect(sid+'.inheritance',inheritance)
        inspect(sid+'.end_state',_field(timeline,'Kết cảnh'))
        for line in timeline.splitlines():
            if not line.startswith('- '):continue
            cells=timeline_cells(line)
            if len(cells)==5:
                # Screen text (cell 3) may legitimately quote an error code.
                for index in (0,1,2,4):inspect(sid+'.timeline',cells[index])
        inspect(sid+'.criteria',criteria)
    return dict(ready=not issues,issues=issues)


def require_visual_readiness(script):
    status=visual_readiness(script)
    if not status['ready']:
        fields=', '.join(dict.fromkeys(i['field'] for i in status['issues']))[:300]
        raise WorkflowError('SCRIPT_VISUALS_INCOMPLETE',
            'Bản bàn giao hình ảnh của kịch bản chưa hoàn tất ('+fields+'). '
            'Cần sửa phần hình ảnh ở bước Kịch bản và duyệt phiên bản mới, giữ nguyên lời đọc. '
            'Chưa chạy Planner/Code Generator; bấm tạo lại từng cảnh sẽ không giải quyết đầu vào này.')
    return status


def project_visual_readiness(root,project):
    """Read-only health for the current script, including already approved ones."""
    from src.shared import _workflow_store as store
    script=next((a for a in reversed(project.get('artifacts',[]))
        if a['stage']=='script' and not a.get('invalidated')),None)
    ref=(script or {}).get('bundle',{}).get('script.json')
    if not ref:return dict(ready=True,issues=[])
    try:
        path=store.project_path(root,ref['path'])
        if store.digest(path)!=ref['sha256']:
            raise WorkflowError('ARTIFACT_CHANGED','Bản bàn giao kịch bản đã thay đổi.')
        result=visual_readiness(store.read_json(path)['script'])
        return dict(result,script_version=script['version'],script_sha256=script['sha256'])
    except (OSError,KeyError,WorkflowError) as exc:
        return dict(ready=False,issues=[dict(field='script.json',owner='scene_slicer',problem=str(exc))],
                    script_version=script['version'],script_sha256=script['sha256'])
