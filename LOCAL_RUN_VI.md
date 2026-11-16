# Chạy ứng dụng trên Windows, WSL2 hoặc Linux

Cần Python 3.11+, `uv`, Node.js 22+, npm và OpenSSL trong PATH. ZIP đã được kiểm thử trong Linux Cloud; **PowerShell/Windows và WSL2 chưa được kiểm thử trên máy của bạn**. Lần đầu chạy cần mạng để cài dependencies từ lockfile. Không cần credentials cho MOCK.

## Windows PowerShell

Tải `vn30-dnse-local-validation.zip` vào Downloads, mở PowerShell và giải nén vào thư mục mới:

```powershell
Expand-Archive -LiteralPath "$HOME\Downloads\vn30-dnse-local-validation.zip" -DestinationPath "$HOME\vn30-fixed"
Set-Location "$HOME\vn30-fixed\vn30-dnse-live"
```

Một lệnh mở MOCK, gồm cả backend và frontend:

```powershell
.\scripts\start_mock.ps1
```

Một lệnh mở LIVE read-only sau khi các biến DNSE đã được cấu hình an toàn trong môi trường của terminal:

```powershell
.\scripts\start_live.ps1
```

Giữ terminal đang chạy; nhấn Ctrl+C để dừng. Nếu PowerShell chặn script theo chính sách máy, tuân thủ chính sách đó hoặc dùng WSL2; không cần thay đổi chính sách để chạy MOCK bằng WSL2.

## WSL2 / Linux

Với WSL2 và ZIP nằm trong Downloads của Windows:

```bash
WIN_USER_DIR=$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' | tr -d '\r')")
unzip "$WIN_USER_DIR/Downloads/vn30-dnse-local-validation.zip" -d "$HOME/vn30-fixed"
cd "$HOME/vn30-fixed/vn30-dnse-live"
```

Trên Linux, giải nén ZIP vào một thư mục mới rồi `cd` vào thư mục `vn30-dnse-live` bên trong. Một lệnh mở MOCK:

```bash
bash scripts/start_mock.sh
```

Một lệnh mở LIVE read-only:

```bash
bash scripts/start_live.sh
```

Cả hai script tự xác định project root, đồng bộ Python từ `uv.lock` và cài frontend nếu dependencies còn thiếu. LIVE chạy thêm security tests trước khi khởi động. Frontend và backend chỉ lắng nghe `127.0.0.1`; backend là collector, không cần tiến trình collector riêng.

## Truy cập và chẩn đoán

Mở `http://127.0.0.1:5173`. Health backend là `http://127.0.0.1:8000/healthz`; `/api/health` cho biết trạng thái nguồn. Vite chuyển `/api` và WebSocket cùng origin tới backend, nên không cần CORS cho cấu hình này. Truy cập trực tiếp backend từ một origin khác không được cấu hình CORS.

Nếu không mở được, giữ nguyên terminal và chạy trong terminal thứ hai:

```powershell
.\scripts\doctor_local.ps1
.\scripts\doctor_local.ps1 -Network
```

Hoặc trên WSL2/Linux:

```bash
bash scripts/doctor_local.sh
bash scripts/doctor_local.sh --network
```

Doctor in phiên bản, project root, import, cổng, HTTP, proxy, WebSocket và sự hiện diện của hai biến DNSE; không in giá trị credentials. `-Network`/`--network` thêm kiểm tra DNS, HTTPS và WSS không xác thực qua proxy hiện hành. DNS trực tiếp lỗi không tự chứng minh DNS qua proxy lỗi. Nếu cổng 8000 hoặc 5173 đã có tiến trình lắng nghe, script dừng và báo cổng thay vì tự tắt tiến trình khác.

## LIVE và credentials

`DNSE_API_KEY` và `DNSE_API_SECRET` phải hiện diện trong môi trường **của backend trên máy cá nhân**. Biến từ Codex Cloud không tự xuất hiện trên Windows hay WSL. Không dán giá trị vào chat, lệnh, Git hoặc log. `.env.example` chỉ liệt kê tên, `.env` bị Git bỏ qua và ứng dụng **không tự đọc `.env`**. Frontend không nhận các biến DNSE khi chạy qua script.

Nhập hai biến kín trong **cùng PowerShell sẽ chạy backend**, sau đó chạy chẩn đoán và khởi động LIVE:

```powershell
Set-PSDebug -Off
$dnseKey = Read-Host 'DNSE_API_KEY' -AsSecureString
$dnseSecret = Read-Host 'DNSE_API_SECRET' -AsSecureString
$env:DNSE_API_KEY = [System.Net.NetworkCredential]::new('', $dnseKey).Password
$env:DNSE_API_SECRET = [System.Net.NetworkCredential]::new('', $dnseSecret).Password
Remove-Variable dnseKey, dnseSecret
uv run --frozen pytest -q backend/tests/test_connectivity.py backend/tests/test_secure_dnse.py backend/tests/test_live_local.py
if ($LASTEXITCODE -ne 0) { throw 'Security tests thất bại; dừng kiểm tra Production.' }
uv run --frozen python scripts/dnse_local_check.py
.\scripts\start_live.ps1
```

Tương ứng trên WSL2/Linux, trong cùng terminal backend:

```bash
set +x
read -r -s -p 'DNSE_API_KEY: ' DNSE_API_KEY; printf '\n'
read -r -s -p 'DNSE_API_SECRET: ' DNSE_API_SECRET; printf '\n'
export DNSE_API_KEY DNSE_API_SECRET
uv run --frozen pytest -q backend/tests/test_connectivity.py backend/tests/test_secure_dnse.py backend/tests/test_live_local.py && uv run --frozen python scripts/dnse_local_check.py
bash scripts/start_live.sh
```

Chỉ tiếp tục LIVE nếu security tests đạt và chẩn đoán cho thấy mạng và xác thực phù hợp. Công cụ kiểm tra Production read-only có giới hạn, báo HTTP status và metadata riêng từng endpoint; REST được kiểm tra độc lập với WebSocket. Không có endpoint giao dịch. `REST_LIVE_VERIFIED` cần OHLC hợp lệ, `WS_AUTHENTICATED` chưa chứng minh có market message; `MARKET_STREAM_VERIFIED` cần message hợp lệ và còn mới. Dashboard chỉ báo `LIVE` sau trade thực hợp lệ; các trạng thái khác gồm `BLOCKED`, `CONNECTED_NO_TRADES`, `STALE` và `DISCONNECTED`. Không tự chuyển sang MOCK.

Dữ liệu DNSE thô và đã chuẩn hóa chỉ được giữ riêng trong bộ nhớ có giới hạn; không ghi xuống `.data` khi chưa xác nhận license. Trade side là `UNKNOWN`, quote là MBP. VWAP/CVD/MA21 và basis LIVE chưa có đủ đầu vào được xác minh nên để trống. Chưa có kết nối DNSE thật được xác minh trong Cloud.
