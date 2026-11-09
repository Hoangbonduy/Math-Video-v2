# Kiểm tra kế hoạch: 3 nhóm

Luồng mới: kịch bản đã duyệt → AI lập kế hoạch → 3 nhóm kiểm tra → Python bổ sung tiêu chí → tra cứu Manim → viết code → render nháp → kiểm tra telemetry và ảnh → người dùng duyệt.

## Ba nhóm chặn trước khi viết code

1. Khung JSON và khớp kịch bản: đúng trường/kiểu dữ liệu cần dùng, mã cảnh, lời đọc, thời lượng và phiên bản/hash hợp đồng. Chặn khai báo xung đột yêu cầu. Giữ lời đọc trong các nhịp nhưng không chặn theo độ dài hook hay chất lượng mô tả.
2. Danh mục tra cứu: API có namespace hợp lệ, số lượng trong giới hạn và recipe nằm trong danh mục.
3. ID và thời gian: ID không trùng/xung đột, các đối tượng/nhóm được tham chiếu tồn tại, mốc thời gian nằm trong cảnh và start không vượt end.

Các hàm nằm trong src/scene_design/plan_validation.py. Scene_code_pipeline.validate_plan gọi ba nhóm; _plan gọi prepare để tự động bổ sung dữ liệu.

## Xử lý các nhóm cũ

| Nhóm cũ | Cách xử lý mới |
|---|---|
| 1, 2, 3, 6 | Gộp thành khung dữ liệu và khớp kịch bản; bỏ kiểm tra chất lượng hook. |
| 4 | Danh mục tra cứu Manim. |
| 7, 8, 9 | Chỉ giữ ID và thời gian ở bước kế hoạch. Vị trí neo, crop, che khuất và HUD được đo/đánh giá sau render. |
| 5, 14 | Python chép tiêu chí đã duyệt và sinh ánh xạ; không yêu cầu AI tự nhập lại. |
| 10 | Dùng thời gian animation thực tế và ảnh để đánh giá thứ tự pha. |
| 11, 13 | Reviewer so trực tiếp hình ảnh, kịch bản đã duyệt và telemetry về toán học/ảo giác/thứ tự tiết lộ. Không yêu cầu trích dẫn nguyên văn hay tự khai báo đạt. |
| 12 | Không yêu cầu lượt mới tính geometry_checkpoints. Với dữ liệu cũ, có thể đo đối tượng hoặc hợp các hộp bao thành viên nhóm sau render. |

Python tự gắn tiêu chí trạng thái đầu, cuối và nối cảnh khi cần. Chỉ nối cảnh mới có điều kiện thiếu frame trước; các tiêu chí còn lại vẫn áp dụng.

Code vẫn cần qua kiểm tra cú pháp, API, AST và track trước khi được thực thi. Đây là kiểm tra code, không phải kiểm tra chất lượng kế hoạch.

Sau khi có video, lỗi bố cục hay metadata chất lượng được ghi nhận trong motion_checks/result; draft.json vẫn được lưu để xem. Bản nháp có lỗi chưa được coi là đạt hoặc được duyệt.

## Phiên bản và dữ liệu cũ

Prompt cảnh dùng phiên bản 15 và execution_policy ghi ba nhóm. Nội dung hợp đồng thay đổi tạo hash mới cho lượt chạy mới. Không chỉnh sửa kết quả, phản hồi AI hay snapshot của job cũ. Khởi động lại server rồi bấm Tạo cảnh này để tạo lượt mới.

## Kiểm thử không gọi Codex thật

    python -m unittest tests.test_minimal_plan_validation tests.test_first_scene_scope
    python -m pytest -q tests/test_minimal_plan_render.py

Kiểm thử render dùng AI giả, Manim thật và dữ liệu tạm.

Vật thể thường có thể khai báo anchor làm vị trí ban đầu. Telemetry đo từng thành phần vật liệu có fill; các nét chỉ có stroke không được tính là mảnh. Vision Reviewer vẫn được gọi khi bản render có cảnh báo tự động, nhưng kết luận tổng thể không thể đạt nếu cảnh báo đó chưa được giải quyết.
