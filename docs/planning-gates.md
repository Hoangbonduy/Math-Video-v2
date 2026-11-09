# Luồng tạo cảnh
Kịch bản đã duyệt → kế hoạch → đọc references Manim → viết mã → render → AI kiểm tra → người dùng duyệt.
Mã lập kế hoạch chỉ kiểm tra dữ liệu đủ dùng: cấu trúc, lời đọc/thời lượng, ID và tên API.
Hình học và chất lượng được đánh giá trên video. Không có bộ chính sách hợp đồng bên ngoài.
Mỗi lượt tạo cảnh có một lần dựng đầu và tối đa hai lần sửa tự động, dùng chung cho lỗi render và lỗi hình ảnh.
Khởi động lại tiếp tục job đã lưu, không đặt lại số lượt sửa.
Có video thì AI kiểm tra trước. AI đạt vẫn chờ người dùng duyệt.
Hết lượt sửa: giữ video thành công gần nhất, hiển thị lỗi còn lại và chờ người dùng quyết định.
Không lần nào render thành công: hiển thị lỗi cùng log, không giả báo có bản nháp.
Bản v2 vẫn chỉ chạy cảnh đầu tiên. Các job cũ được giữ như lịch sử, không tái dùng chính sách cũ cho lượt mới.
