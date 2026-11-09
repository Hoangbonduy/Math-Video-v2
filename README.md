# Math-Video-v2

Dự án thử nghiệm riêng. Phần 1 tạo và duyệt kịch bản; phần 2 tạo, render và kiểm tra cảnh đầu tiên của kịch bản đã duyệt. Các cảnh tiếp theo, âm thanh và ghép video chưa được kết nối.

Luồng cảnh dùng Manim và đọc có chọn lọc tài liệu ở references/manim-0.22.1. API và signature của Manim thực tế được kiểm tra trước khi sinh mã. Kết quả, job và bản nháp lưu trong data/projects của v2; phần mềm không tự tạo các cảnh tiếp theo.

## Chạy trong WSL

Cần Python 3.11 trở lên, Manim 0.22.1 (cùng các phụ thuộc hệ thống của Manim), FFmpeg, PyYAML và Codex CLI đã đăng nhập. Có thể dùng môi trường video của dự án gốc:

    cd ~/experiments/Math-Video-v2
    conda activate video
    python main.py serve-review --port 8765

Mở http://127.0.0.1:8765 và mở project. Sau khi duyệt kịch bản, vào Thiết kế cảnh, chọn cảnh đầu và bấm Tạo cảnh này. Việc tạo cảnh dùng Codex thật và hạn mức tài khoản. Duyệt kết quả sau khi kiểm tra.

## Kiểm thử

    python -m unittest tests.test_generation tests.test_content src.idea.test_guideline_pipeline src.idea.test_guideline_revision
    python -m pytest -q tests/test_scene_code_pipeline.py::test_real_direct_pipeline_and_native_final

Kiểm thử render trên dùng AI giả và Manim thật; không khẳng định mọi kịch bản thực tế đều tạo cảnh thành công. Bộ tests.test_narration được sao chép nguyên trạng, có các trường hợp thất bại cả ở dự án gốc.

Chính sách kiểm tra kế hoạch và cách chuyển các nhóm cũ: [docs/planning-gates.md](docs/planning-gates.md).
