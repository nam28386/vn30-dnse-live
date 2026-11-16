> Đây là báo cáo lịch sử trước khi bổ sung gói chạy cục bộ; xem [LOCAL_RUN_VI.md](../LOCAL_RUN_VI.md) để biết trạng thái và lệnh mới.

# Trạng thái kết nối DNSE Production

Ngày kiểm tra: 16/11/2026. Các quan sát dưới đây chỉ áp dụng cho máy đang chạy; không suy diễn rằng cấu hình đã được xuất bản hoặc kết nối mới đã thành công.

| Cổng kiểm tra | Trạng thái | Bằng chứng |
|---|---|---|
| Security Gate | PARTIAL | SDK chính thức vẫn tắt kiểm tra hostname ở REST và có thể in signed headers khi debug/dry-run. Client SDK gốc vẫn bị chặn. Transport read-only mới đã qua các kiểm thử cục bộ về TLS, HMAC và redaction, nhưng chưa hoàn tất kiểm toán tương thích WebSocket/proxy trong môi trường DNSE thực tế. I/O có xác thực bị khóa theo mặc định. |
| Network Gate | FAIL | Chính sách restricted đang có hiệu lực và không có hostname DNSE trong allowlist hiện hành. Proxy trả HTTP CONNECT 403 cho cả REST và WebSocket Production. Kết quả trực tiếp: DNS REST thất bại; DNS WebSocket timeout. Chưa thiết lập TLS tới DNSE, chưa nhận HTTP từ máy chủ DNSE và chưa thử WebSocket upgrade. CONNECT 403 là phản hồi proxy, không phải phản hồi xác thực DNSE. |
| Authentication Gate | UNKNOWN | `DNSE_API_KEY` và `DNSE_API_SECRET` đều không hiện diện hoặc rỗng trong tiến trình hiện tại; môi trường hiện hành cũng không báo binding tương ứng. Không có yêu cầu xác thực nào được gửi. Không biết key, chữ ký, version, quyền hay rate limit có được DNSE chấp nhận hay không. |
| Market Data Gate | UNKNOWN | Không truy vấn instruments, metadata, session, OHLC, trade/quote history hay WebSocket. Chưa nhận message thực và chưa xác định hợp đồng VN30 gần đáo hạn. |

Ứng dụng vẫn chạy MOCK. Những message và giá trong dashboard là dữ liệu giả lập, không phải dữ liệu DNSE. Không có dữ liệu thị trường thực nào được lưu.

## Các thay đổi đã triển khai

- `backend/vn30/adapters/secure_dnse.py`: transport Production giới hạn REST GET tới sáu nhóm endpoint market-data, kiểm tra TLS chain và hostname qua context mặc định, không theo redirect, giới hạn kích thước, thời gian và đọc dữ liệu trong bộ nhớ. REST sử dụng proxy kế thừa của môi trường. WebSocket dùng WSS, timeout, logger bị vô hiệu hóa và không ghi raw frames; xử lý ping ở tầng ứng dụng. Không gọi SDK gốc có nhánh in headers khi DEBUG/dry-run. I/O có xác thực bị khóa bằng `_AUTHENTICATED_IO_ENABLED = False`; không được mở khóa cho đến khi Security Gate và Network Gate đã được kiểm toán và xác minh.
- Chữ ký REST và WebSocket được đối chiếu cục bộ bằng credentials giả lập với source SDK chính thức commit `aa55a5117de2534707bca6165b6738e1cc6fc6a4`. Kết quả này chứng minh phép tính trùng source được kiểm tra, không chứng minh DNSE chấp nhận chữ ký hoặc API version. Hai bài đối chiếu cần checkout SDK tại `/tmp/dnse-openapi-sdk`; nếu checkout không có, chúng được đánh dấu skipped.
- `backend/tests/test_secure_dnse.py`: kiểm tra allowlist read-only, khóa an toàn mặc định, không in credential giả lập, xử lý 401, giới hạn WebSocket và TLS thật trên loopback với CA không đáng tin, sai hostname và hostname hợp lệ. Chỉ dùng certificate và credential giả lập.
- Không nối transport mới vào Market State Engine; chưa thay đổi indicator hoặc cho phép mode LIVE. Stream thử nghiệm chưa có xác nhận tương thích thực tế về subscription, mapping, độ mới, heartbeat, reconnect hay resubscription. Không coi báo cáo test là kiểm toán bảo mật độc lập.

## Thiết lập mạng và biến môi trường

Bản nháp cấu hình đã được lưu với đúng hai hostname bổ sung `openapi.dnse.com.vn` và `ws-openapi.dnse.com.vn`; các preset hiện có được giữ nguyên. Bản nháp không tự áp dụng vào máy đang chạy. Trong cài đặt Codex Cloud Environment, hãy xem lại/lưu cấu hình mạng và xuất bản khi phù hợp; sau đó khởi tạo hoặc cập nhật môi trường theo cơ chế của nền tảng và kiểm tra lại trạng thái thực tế.

Trong cài đặt môi trường, kiểm tra binding của `DNSE_API_KEY` và `DNSE_API_SECRET` đối với chính môi trường/tác vụ này. Không dán giá trị vào chat, source, lệnh shell, log hay artifact. User đã cho biết các biến được cấu hình, nhưng máy đang chạy hiện chưa nhận được chúng; chỉ có thể xác minh lại sau khi binding được áp dụng. SDK tạo HMAC cục bộ, vì vậy một proxy placeholder không tự chứng minh rằng giá trị dùng cho ký HMAC là khả dụng; cần xác minh theo cơ chế cung cấp bí mật được hỗ trợ, không xuất giá trị.

Sau thay đổi môi trường, chạy lại chẩn đoán không xác thực theo cả đường proxy được hỗ trợ và đường trực tiếp. Chỉ gửi request có xác thực sau khi audit transport mới, phiên bản SDK, TLS chain/hostname, bảo vệ log, proxy và trạng thái Security/Network Gate đều đạt. Tiếp tục giữ khóa I/O cho đến khi các điều kiện đó được xác minh; không tự coi việc lưu bản nháp là PASS. Sau đó mới được kiểm tra REST Production giới hạn theo yêu cầu, phân biệt lỗi 401/403, 429, version và quyền; WebSocket và dữ liệu thực chỉ được dùng sau khi schema, thời gian và độ mới được xác thực.

## Kiểm thử đã chạy

- `UV_CACHE_DIR=/workspace/.cache/uv uv run pytest -q`: **60 passed**, một cảnh báo deprecation của Starlette TestClient/httpx.
- `UV_CACHE_DIR=/workspace/.cache/uv uv run ruff check backend scripts` và `ruff format --check backend scripts`: PASS.
- `npm test` và `npm run build` trong `frontend`: **5 tests passed**, TypeScript/Vite build PASS.
- Kiểm tra direct Production không xác thực: DNS REST lỗi, DNS WebSocket timeout; các bước sau UNKNOWN.
- Kiểm tra HTTP CONNECT qua proxy không xác thực: `403` đối với cả hai hostname. Không có TLS/HTTP tới DNSE và không có message thực.

Mở dashboard MOCK theo `README.md`. Không có hướng dẫn mở dashboard LIVE vì Market Data Gate chưa đạt và chế độ LIVE còn bị khóa.
