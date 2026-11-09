---
contract_version: "1.0.0"

render:
  preview_resolution: [360, 640]
  final_resolution: [1080, 1920]
  fps: 30
  scene_width: 9.0
  scene_height: 16.0
  safe_bounds:
    left: -3.95
    right: 3.95
    bottom: -6.5
    top: 7.45
  min_font_size: 22
  duration_tolerance_frames: 2

ast_constraints:
  required_scene_class_name: "GeneratedScene"
  required_scene_base_class: "Scene"
  required_scene_method: "construct"
  forbidden_base_classes:
    - "MovingCameraScene"
    - "ZoomedScene"
    - "ThreeDScene"
  forbidden_scene_methods:
    - "__init__"
  camera_policy: "background_color_only_before_first_frame"

object_metadata:
  kind:
    - "text"
    - "formula"
    - "shape"
    - "background"
  layout_role:
    - "hud"
    - "focal"
    - "cropped_context"
  unknown_role_policy: "reject"

layout_policy:
  hud:
    safe_area: "required"
    anchor: "fixed_in_declared_upper_region"
  focal:
    safe_area: "required"
    visibility: "required_during_declared_observation_intervals"
  cropped_context:
    safe_area: "exempt_only_during_approved_crop_intervals"
  overlap:
    policy: "explicit_pairs_and_intervals"
    unreadable_text_or_hidden_focal: "reject"

math_policy:
  default_mode: "strict"
  visual_illusion:
    requires_approved_declaration: true
    apparent_area_mismatch: "allowed_within_declared_scope"
    undeclared_geometry_changes: "reject"

review_policy:
  criterion_statuses:
    - "pass"
    - "fail"
    - "not_applicable"
    - "insufficient_evidence"
  continuity:
    requires_verified_previous_last_frame: true
    missing_previous_frame: "not_applicable"
  current_scene_initial_state:
    required: true
  automatic_pass:
    all_applicable_criteria_must_pass: true
    unresolved_errors_allowed: false
    insufficient_evidence_allowed: false
---

# HỢP ĐỒNG KỸ THUẬT DỰNG CẢNH

## 1. Phạm vi và nguồn sự thật

Hợp đồng này quy định quy tắc chung cho:

Planner → Code Generator → Static/Layout Validator → Vision Reviewer.

Ba nguồn sự thật có trách nhiệm riêng:

- `guidelines.md`: lời đọc, chia cảnh, global_visuals và visual_intent.
- `system_contract.md`: giới hạn kỹ thuật, dữ liệu bàn giao, ngoại lệ và điều kiện đánh giá.
- `references/`: API, chữ ký hàm và cách sử dụng Manim/component.

Quy tắc kỹ thuật trong hợp đồng này được ưu tiên hơn hướng dẫn kỹ thuật
trùng lặp trong prompt riêng hoặc references. Chữ ký API thực tế phải
khớp runtime đang cài đặt; tài liệu API không cấp thêm quyền vượt hợp đồng.

Lời đọc, thời lượng, dữ kiện và tiêu chí nội dung đã duyệt là đầu vào
bất biến. Nếu đầu vào không thể thực hiện trong hợp đồng, báo
CONTRACT_CONFLICT và trả về khâu lập kế hoạch để xử lý.
Không tự đổi dữ kiện, bỏ tiêu chí hoặc nới validator để dựng cho xong.

YAML và phần diễn giải phải thống nhất. Nếu phát hiện mâu thuẫn giữa
hai phần, hợp đồng chưa hợp lệ và phải được sửa trước khi tiếp tục.

Đây là đặc tả bắt buộc khi tích hợp. Không mặc định rằng mã hiện tại
đã hỗ trợ mọi trường hoặc quy tắc trong tài liệu.

## 2. Quy tắc áp dụng chung

Cả bốn thành phần phải dùng cùng một phiên bản và cùng một snapshot
hợp đồng trong một job.

Job phải lưu contract_version và SHA-256 của toàn bộ file hợp đồng.
Kế hoạch, mã, kết quả kiểm tra và review phải tham chiếu cùng hash.

Khi hợp đồng thay đổi, không dùng lại kết quả cũ như bằng chứng tuân thủ
bản mới nếu chưa kiểm tra lại. Không trộn hai phiên bản trong một job.

Mọi ngoại lệ phải có khai báo cụ thể trong kế hoạch đã được kiểm tra.
Code Generator và Vision Reviewer không được tự tạo ngoại lệ mới.

## 3. Khung hình và khả năng đọc

Hệ tọa độ cảnh là 9 × 16 đơn vị, gốc ở giữa:
x tăng sang phải, y tăng lên trên.

Preview 360 × 640 và final 1080 × 1920 dùng cùng tọa độ, kích thước chữ,
nét vẽ và timeline. Không nhân các giá trị này theo độ phân giải.

Safe area được xác định bởi render.safe_bounds.
Vùng dưới safe area được dành cho phụ đề.

Chữ và công thức phải giữ cỡ hiệu dụng tối thiểu 22 sau mọi phép scale.
Ngoại lệ cropped_context không được dùng để miễn kiểm tra khả năng đọc.

Nếu nội dung không vừa ở cỡ đọc được, Planner phải chia thành các trạng
thái hình ảnh nối tiếp. Không giải quyết bằng cách thu nhỏ chữ vô hạn.

Thời gian là giây cục bộ của từng cảnh, bắt đầu từ 0.
Sai số thời lượng video mã hóa được phép tối đa 2 frame ở FPS quy định.
Frame cuối có thể nằm trước mốc duration một frame; không yêu cầu một
frame có timestamp chính xác bằng duration.

## 4. Loại và vai trò vật thể

Mỗi vật thể có ID ổn định và hai trường độc lập:

- kind: loại nội dung, phục vụ kiểm tra chữ, công thức và hình học.
- layout_role: chính sách bố cục, phục vụ safe area và ngoại lệ crop.

Ví dụ: một bộ đếm có kind=text và layout_role=hud.
Không thay kind bằng hud/focal/cropped_context.

### hud

Tiêu đề, câu hỏi và bộ đếm thuộc hud.

Planner khai báo hud_region ở phần trên safe area và vị trí neo
cho từng đối tượng. Nếu không có HUD thì hud_region có thể là null.

HUD giữ nguyên vị trí neo trong cảnh, độc lập với nhóm hình học được
phóng đại. Được cập nhật nội dung hoặc xuất hiện/biến mất theo timeline,
nhưng không di chuyển xuyên vùng đang biến đổi hình học.

Chữ phải nằm trong vùng đã khai báo và không bị che khuất.

### focal

Là chi tiết khán giả cần quan sát tại một thời điểm:
mảnh ghép, dải chênh, vạch cắt, điểm hoặc đường đang được giải thích.

Focal phải nằm trọn trong safe area và nhìn rõ trong các khoảng
thời gian được yêu cầu quan sát.

Ẩn/hiện theo timeline được phép. Không báo lỗi chỉ vì vật thể chưa đến
mốc xuất hiện hoặc đã kết thúc vai trò quan sát.

### cropped_context

Là phần ngữ cảnh được phép bị cắt khi phóng cận bằng biến đổi vật thể.

Ngoại lệ chỉ có hiệu lực khi kế hoạch khai báo:

- object_ids của phần được crop;
- khoảng thời gian áp dụng, gồm cả thời gian giữ góc phóng cận;
- nhóm được phóng đại, hệ số và phép tịnh tiến;
- focal cần giữ rõ;
- vùng hoặc phần thân được phép ra ngoài khung.

Ngoài khoảng này, vật thể phải tuân thủ safe area như bình thường.

Chỉ miễn lỗi tràn biên đã được khai báo.
Vẫn kiểm tra che HUD, che focal, khả năng đọc và ảnh hưởng đến phụ đề.
Khi cần, dùng cắt/mask để bảo vệ vùng hiển thị quan trọng.

Không gán cropped_context cho chữ hoặc công thức chỉ để né lỗi bố cục.

### Nền và nhóm vật thể

Màu nền toàn cảnh là thuộc tính style, không phải vật thể ngữ nghĩa
cần gán layout_role.

Đối tượng có kind=background vẫn phải có layout_role;
tên gọi background không tự cấp quyền miễn kiểm tra.

Một nhóm chứa cả phần được crop và phần cần nhìn rõ phải được theo dõi
ở mức thành phần. Không miễn kiểm tra toàn nhóm vì một phần được crop.
Tránh tính cùng một hình học hai lần qua cả nhóm cha và đối tượng con.

## 5. Camera và mã cảnh

Mã phải định nghĩa lớp GeneratedScene kế thừa trực tiếp Scene
và triển khai construct.

GeneratedScene là tên lớp; Scene là tên lớp cơ sở.

Không dùng MovingCameraScene, ZoomedScene, ThreeDScene hoặc thay đổi
vị trí, góc nhìn, kích thước khung và mức zoom của camera.

Ngoại lệ duy nhất cho truy cập camera:
được gán self.camera.background_color theo style trước frame đầu tiên.

Ngoài phép gán trên, không đọc, ghi hoặc gọi thuộc tính/phương thức
camera, kể cả thông qua alias hay tham chiếu gián tiếp.

Mọi phóng cận được thực hiện bằng scale và tịnh tiến nhóm vật thể.
HUD không nằm trong nhóm được phóng đại.

Không ghi đè __init__, thay đổi global config, truy cập filesystem,
network hoặc subprocess từ mã cảnh. Asset chỉ dùng đường dẫn đã duyệt.

AST Validator kiểm tra cấu trúc cú pháp và cách sử dụng,
không chỉ tìm từ khóa trong chuỗi hoặc comment.

## 6. Timeline và chồng lấp

Planner phải khai báo thời điểm bắt đầu/kết thúc, đối tượng tác động
và kết quả của từng sự kiện.

Trong cùng vùng thao tác, các pha sau phải nối tiếp nhau:

1. Làm mờ hoặc loại bỏ ghost.
2. Di chuyển, xoay hoặc tái ghép hình học.
3. Cập nhật bộ đếm/chữ xác nhận kết quả.

Được đổi thứ tự nếu phù hợp kịch bản, nhưng các pha này không chồng
thời gian trong cùng vùng thao tác. HUD vẫn giữ nguyên vị trí neo.

Các chuyển động hình học có thể diễn ra đồng thời khi đó là chủ đích
đã khai báo và không gây che khuất hoặc sai thứ tự tiết lộ.

Chồng lấp có chủ đích phải khai báo đúng cặp object_ids, khoảng thời
gian và lý do, ví dụ nhãn đặt trên mảnh ghép hoặc hai phần đang lắp lại.

Khai báo chồng lấp không được hợp thức hóa chữ khó đọc, focal bị che
hoặc hình học gây hiểu sai.

Giao nhau giữa hai bounding box chỉ là bằng chứng nghi vấn đối với
đường cong, vùng rỗng hoặc hình lắp ghép. Cần kiểm tra hình học hoặc
ảnh thực trước khi kết luận lỗi che khuất.

## 7. Chính sách toán học và đánh lừa thị giác

Mặc định math_mode=strict:
giữ đúng dữ kiện, quan hệ toán học và các đại lượng được bảo toàn.

Chỉ dùng math_mode=visual_illusion khi visual_intent đã duyệt thể hiện
chủ đích đánh lừa thị giác. Sau khi có bản nháp, Reviewer đối chiếu
trực tiếp kịch bản và bằng chứng render về:

- đối tượng và giai đoạn chịu ngoại lệ;
- sai lệch biểu kiến được mong đợi;
- kích thước và bất biến phải giữ;
- thông tin được phép tiết lộ ở từng mốc.

Trong phạm vi này, không bắt buộc diện tích đường bao nhìn có vẻ hoàn
chỉnh phải bằng tổng diện tích vật liệu thật. Không chặn dựng cảnh chỉ
vì sai lệch biểu kiến chính là hiệu ứng đã được duyệt.

Vẫn phải bảo toàn diện tích của từng mảnh khi chỉ tịnh tiến hoặc xoay.
Không tự thêm mảnh, nhân bản vật liệu, kéo giãn ngầm hay đổi kích thước.

Nếu dữ kiện yêu cầu một thao tác thật sự bất khả thi và chưa có cách
minh họa được duyệt, báo CONTRACT_CONFLICT.
Không tự suy diễn ngoại lệ để che lỗi toán học.

Ngoại lệ này không cho phép tiết lộ đáp án sớm hơn visual_intent.

## 8. Dữ liệu bàn giao và trách nhiệm

### Planner

Nhận kịch bản đã duyệt, global_visuals, visual_intent, style,
runtime capabilities và hợp đồng.

Bàn giao mã cảnh, lời đọc, thời lượng; mục tiêu và các nhịp thể hiện;
đối tượng và nhóm có ID ổn định, kind/layout_role; timeline, vị trí neo
và khoảng quan sát dự kiến; API và recipe cần dùng.

Python tự sao chép các tiêu chí đã duyệt và tự tạo ánh xạ tiêu chí,
gồm trạng thái đầu, cuối và điều kiện nối cảnh khi cần.
Không yêu cầu AI tự chép tiêu chí, tính geometry_checkpoints, tạo
criterion_rules, illusion_spec hay reveal_checks để vượt bước Kế hoạch.

Planner vẫn giữ dữ kiện, cách thể hiện và thứ tự tiết lộ trong kịch bản.
Chỉ báo CONTRACT_CONFLICT khi có yêu cầu đã duyệt thực sự mâu thuẫn;
các dự đoán về chất lượng hình ảnh được đánh giá sau khi có bản nháp.

### Code Generator

Thực hiện kế hoạch bằng API có trong runtime.
Đăng ký metadata cho từng vật thể ngữ nghĩa, gồm nhãn chữ riêng.

Giữ nguyên ID, vai trò, dữ kiện, thứ tự tiết lộ và tiêu chí.
Không tự đổi focal thành cropped_context hoặc thêm ngoại lệ overlap.

Nếu cần thay đổi kế hoạch để thực hiện được, trả về yêu cầu sửa kế hoạch
với lý do cụ thể. Không sinh một phương án thay thế âm thầm.

### Static/Layout Validator

Trước bước sinh mã, kế hoạch chỉ bị chặn bởi đúng ba nhóm:
1. Khung JSON và khớp mã cảnh, lời đọc, thời lượng, phiên bản hợp đồng;
   không có khai báo xung đột yêu cầu.
2. Danh mục tên API và recipe hợp lệ để tra cứu Manim.
3. ID không trùng, tham chiếu có tồn tại, thời gian nằm trong cảnh.

Các giới hạn trình bày, vị trí neo, thứ tự pha, hình học và thứ tự
tiết lộ là kiểm tra chất lượng sau render. Không dùng dò từ khóa
chuyển động HUD hay đối chiếu trích dẫn nguyên văn để chặn kế hoạch.
Mốc hình học của dữ liệu cũ có thể tham chiếu đối tượng hoặc nhóm;
không bắt AI tính hộp bao cho lượt mới.

Static Validator vẫn kiểm tra cú pháp, AST và metadata track của mã
sắp chạy; các kiểm tra thực thi này không phải nhóm chặn kế hoạch.

Layout Validator kiểm tra hình học thực tế trong toàn bộ các khoảng
hiển thị/chuyển động, áp dụng đúng role và ngoại lệ theo thời gian.

Mỗi lỗi phải có mã lỗi, object_ids, thời điểm nếu có, bằng chứng,
quy tắc bị vi phạm và thành phần cần xử lý.

Không tự chấm ý nghĩa sư phạm bằng suy đoán hình học.
Không coi render thành công là bằng chứng cảnh đạt.

### Vision Reviewer

Nhận kế hoạch, metadata, ngoại lệ hợp lệ, tiêu chí, kết quả validator
và ảnh/video thực tế.

Đánh giá ý nghĩa, khả năng đọc, che khuất, chuyển động, thứ tự tiết lộ
và kết quả nhìn thấy.

Tôn trọng ngoại lệ crop và visual_illusion đã được xác nhận.
Không yêu cầu khôi phục toàn bộ vật thể chỉ vì phần được phép crop
không xuất hiện trên màn hình.

Không kết luận một sự kiện ngắn bị thiếu chỉ vì ảnh lấy mẫu không chứa
sự kiện đó nếu telemetry/video đã có bằng chứng phù hợp.

## 9. Trạng thái đầu cảnh và nối cảnh

Hai phép kiểm tra độc lập:

1. initial_state: frame đầu cảnh hiện tại so với trạng thái Kế thừa
   đã được duyệt.
2. cross_scene_continuity: frame cuối cảnh trước so với frame đầu
   cảnh hiện tại.

initial_state luôn áp dụng, kể cả khi dựng riêng một cảnh.

cross_scene_continuity chỉ áp dụng khi có frame cuối cảnh trước đã
được xác minh đúng scene, phiên bản video và nguồn artifact.

Thiếu frame trước:
- cross_scene_continuity = not_applicable;
- vẫn kiểm tra initial_state theo kịch bản;
- không báo cảnh hiện tại bị lỗi nối cảnh vì thiếu artifact trước.

Ảnh hỏng, sai nguồn hoặc không xác minh được không phải bằng chứng
mâu thuẫn hình ảnh. Hệ thống phải nêu rõ trạng thái artifact và lý do
không thực hiện phép so sánh.

Trạng thái cuối được mô tả trong kịch bản là trạng thái dự kiến,
không phải bằng chứng rằng video cảnh trước đã render đúng.

## 10. Kết quả kiểm tra và điều hướng sửa lỗi

Mỗi tiêu chí có một trạng thái:

- pass: đủ bằng chứng đáp ứng tiêu chí.
- fail: có bằng chứng vi phạm cụ thể.
- not_applicable: điều kiện áp dụng không thỏa, kèm lý do.
- insufficient_evidence: tiêu chí có áp dụng nhưng chưa đủ bằng chứng.

Thiếu bằng chứng không được tự chuyển thành pass hoặc fail.
not_applicable không được dùng để bỏ qua tiêu chí initial_state,
khả năng đọc hay yêu cầu nội dung đang áp dụng.

Chỉ tự động đạt khi tất cả tiêu chí áp dụng đều pass, không còn lỗi
validator và không còn insufficient_evidence.

Điều hướng xử lý:

| Vấn đề | Nơi xử lý |
|---|---|
| Kế hoạch sai ý nghĩa, thiếu dữ kiện, ngoại lệ không hợp lệ | Planner |
| Mã không đúng kế hoạch, AST, API, bố cục hoặc timing | Code Generator |
| Không thể sửa mã mà vẫn giữ tiêu chí/cỡ chữ | Trả về Planner |
| Thiếu ảnh hoặc telemetry cho tiêu chí đang áp dụng | Bổ sung bằng chứng rồi review lại |
| Thiếu frame cảnh trước | Bỏ qua riêng cross_scene_continuity |
| Sai phiên bản hợp đồng hoặc runtime không tương thích | Điều phối job trước khi tiếp tục |
| Hết lượt sửa nhưng còn lỗi | Giữ trạng thái chưa đạt và báo lỗi còn lại |

Reviewer chỉ báo vấn đề và bằng chứng; không sửa tiêu chí hoặc tự
chọn lại chính sách kỹ thuật.

## 11. Tình huống nghiệm thu hợp đồng

Khi tích hợp, tối thiểu phải chứng minh các trường hợp sau:

| Tình huống | Kết quả bắt buộc |
|---|---|
| Chỉ đặt màu nền camera trước frame đầu | Được phép |
| Dùng camera để zoom/pan | Static Validator từ chối |
| HUD bị scale theo nhóm hình học | Báo lỗi |
| Focal ra ngoài safe area khi cần quan sát | Báo lỗi |
| Cropped context tràn biên trong khoảng được duyệt | Không báo lỗi tràn biên đó |
| Cropped context tràn biên ngoài khoảng được duyệt | Báo lỗi |
| Cropped context che câu hỏi hoặc focal | Vẫn báo lỗi |
| Nhãn trên mảnh ghép, overlap đã khai báo, chữ rõ | Được phép |
| Dựng riêng cảnh, không có frame trước | Bỏ qua nối clip; vẫn chấm initial_state |
| Có đủ bằng chứng cảnh trước và nối cảnh bị lệch | Báo lỗi nối cảnh |
| Ảo giác có sai lệch biểu kiến đúng illusion_spec | Không bắt lỗi sai lệch được duyệt |
| Mảnh ghép bị kéo giãn ngoài kế hoạch | Báo lỗi |
| Thiếu bằng chứng cho tiêu chí đang áp dụng | Chưa tự động đạt |
| Video lệch thời lượng trong dung sai 2 frame | Không báo lỗi thời lượng |

## 12. Runtime evidence and emphasis
HUD emphasis, including a request to shake, is implemented as a color or
brightness pulse at the declared anchor with unchanged size and orientation.
A literal spatial shake fails measured layout review, even if net displacement is zero; do not infer movement from words in planning prose.
Content replacement may change glyph shape without changing font size or pose.
Do not compare intermediate glyph outlines as rigid HUD geometry.
Manim can dissolve a VGroup while its descendants remain on screen; visibility
and bounds must use the visible point-bearing descendants, not parent identity.
Never prebuild .animate builders inside Succession. Use sequential plays, paths,
or explicit independent cumulative Transform targets.
A delayed reveal protects what intermediate geometry teaches, not just labels.
Exposed loss strips may reveal an illusion early; report a conflict if no
truthful approved construction can preserve the reveal order.
A rendered video that fails validation remains inspectable evidence only:
it is neither a passed candidate nor an approved artifact.

## 13. Chính sách bản nháp trước, kiểm tra chất lượng sau

Các giới hạn chất lượng vẫn áp dụng cho kết quả cuối, nhưng không bổ sung
nhóm chặn Kế hoạch ngoài ba nhóm ở mục 8. Python gắn tiêu chí từ kịch bản
và sinh ánh xạ kiểm tra trước bước viết code. Giữ ảnh, telemetry và video
nháp đã render để người dùng xem dù chưa đạt chất lượng; chưa đạt không
đồng nghĩa đã được duyệt. Reviewer kiểm tra ý nghĩa, ảo giác và thứ tự
tiết lộ từ bản gốc đã duyệt và hình ảnh thực, không dựa vào việc AI chép
đúng một trích dẫn hay tự khai báo rằng kế hoạch đã đạt.

## 14. Vị trí ban đầu, mảnh vật liệu và xem lại bản nháp

Vật thể không phải HUD được phép có anchor mô tả vị trí ban đầu;
trường này không ràng buộc vật thể đứng yên. HUD vẫn cần giữ đúng neo.

Một cụm vật liệu có thể gồm các mảnh chuyển động riêng và nét trang trí.
Không kết luận toàn bộ cụm là một mảnh cứng; đối chiếu từng thành phần
vật liệu có hình học độc lập. Nét lưới chỉ có stroke không tính là vật
liệu. Nếu hình học không đủ để xác định danh tính, diện tích hoặc biến dạng
của từng mảnh, báo thiếu bằng chứng để kiểm tra hình ảnh; không tự kết luận
có hoặc không có biến dạng.

Vision Reviewer được xem video nháp ngay cả khi kiểm tra tự động phát hiện
lỗi; giữ nguyên và báo cả hai loại kết quả. Lỗi tự động chưa giải quyết
không thể tự chuyển thành kết quả đạt. Cảnh có thứ tự tiết lộ đã duyệt phải
được kiểm tra qua các frame trung gian; không làm lộ dải hụt hoặc cơ chế
bằng cách cắt thành các dải nhìn thấy trước mốc tiết lộ.
