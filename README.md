# Lantern Sky

Interactive event installation for **VẼ ĐÈN LỒNG KĨ THUẬT SỐ**: khách vẽ trên mẫu giấy → camera scan → nhận diện template → perspective correction → PNG alpha → treo vào **Phố Đèn Ký Ức** trên projector/TV.

## Chạy nhanh

Lantern Sky mặc định chỉ bind vào `127.0.0.1` vì **Control và Display chạy trên cùng laptop**. Thiết bị khác trong Wi-Fi/LAN sẽ không truy cập được Control, camera stream hoặc API.

### Windows

Xem `HUONG_DAN_WINDOWS.md`.

Lần đầu:

```powershell
.\setup_windows.bat
```

Những lần sau:

```powershell
.\START_HERE_WINDOWS.bat
```

### macOS / Linux

Lần đầu:

```bash
./setup_mac.sh
```

Những lần sau:

```bash
./run_mac.sh
```

`run_mac.sh` không cài package và chạy self-test lại ở mỗi lần mở app, giúp startup tại event ổn định hơn.

## Màn hình

- Control: `http://127.0.0.1:8000/control`
- Display: `http://127.0.0.1:8000/display`

Display hiện có **4 dây đèn**, mỗi dây dành cho một template. Khoảng 10 vị trí đèn được nhìn thấy trên mỗi dây ở cùng thời điểm. Các dây chạy ngang liên tục với hướng và tốc độ xen kẽ:

| Dây | Template | Hướng | Tốc độ |
| --- | --- | --- | --- |
| 1 | Classic | phải → trái | 24 px/s |
| 2 | Balloon | trái → phải | 19 px/s |
| 3 | Round | phải → trái | 28 px/s |
| 4 | Rectangle | trái → phải | 21 px/s |

Mỗi scan mới được WebSocket push ngay vào đúng dây và **Tổng số đèn lồng** được cập nhật real-time. Display đồng bộ lại toàn bộ lịch sử sau reload/reconnect.

## 4 mẫu lồng đèn

Project hỗ trợ 4 silhouette. Mỗi template có một bộ ArUco marker riêng, nên scanner tự nhận ra mẫu mà operator không cần chọn thủ công.

| Template | File in | Marker IDs |
| --- | --- | --- |
| Classic | `print/lantern_template.png` | 0, 1, 2, 3 |
| Balloon / giọt nước | `print/lantern_template_balloon.png` | 4, 5, 6, 7 |
| Round / tròn | `print/lantern_template_round.png` | 8, 9, 10, 11 |
| Rectangle / hộp | `print/lantern_template_rectangle.png` | 12, 13, 14, 15 |

Mỗi scan phải thấy đủ đúng 4 marker của một template. Hệ thống dùng các marker để xác định mẫu, tính homography/perspective correction, crop đúng ROI, áp silhouette mask riêng và xuất PNG alpha.

Có thể mở các template trực tiếp từ Control UI ở mục **Printable lantern templates**.

Nếu cần tạo lại template:

```bash
python tools/generate_template.py
```

Luôn in A4 ở **100% / Actual Size**.

## Quy trình sử dụng

1. Khách chọn một trong bốn template.
2. Khách vẽ/trang trí bên trong silhouette và không che 4 marker góc.
3. Mở Control và Display.
4. Đặt giấy dưới camera.
5. Control hiện tên template và `Ready` khi nhận đủ đúng bộ marker.
6. Bấm **Scan lantern**.
7. Hệ thống warp/crop/mask và tạo PNG alpha trong `runtime/lanterns/`.
8. PNG được lưu vĩnh viễn trong lịch sử event và tự thêm vào đúng dây trên Display.

## Persistence trong event

Các PNG scan thành công là **append-only** trong lúc event chạy: hệ thống không tự xóa đèn cũ.

Tên file mới encode luôn template, ví dụ:

```text
20260906_201530_a1b2c3d4__round.png
```

Nhờ vậy sau khi restart/reload, backend vẫn biết ảnh thuộc `classic`, `balloon`, `round` hay `rectangle` và đưa lại vào đúng dây. File từ bản 4-template cũ chưa có suffix được suy ra lại theo kích thước/aspect ratio PNG để đưa về đúng dây; nếu file hỏng thì fallback về `classic`.

`/api/display-state` trả toàn bộ lịch sử cùng `totalCount`. Frontend giữ toàn bộ metadata nhưng chỉ cache một số bitmap đang/chuẩn bị xuất hiện trên màn hình, tránh giữ tất cả ảnh đã scan trong RAM khi sự kiện kéo dài.

## Camera ngoài / Sony

Lantern Sky dùng OpenCV `VideoCapture`, vì vậy hỗ trợ camera ngoài khi camera đó được hệ điều hành expose như một **webcam/UVC video device**.

Các cách kết nối thực tế:

1. **Sony USB Streaming / UVC qua USB-C** — nếu model Sony hỗ trợ chế độ này, cắm USB vào laptop và bật USB Streaming trên camera.
2. **Sony HDMI → USB capture card** — phù hợp nếu muốn đường video ổn định hoặc model không hỗ trợ UVC trực tiếp. Capture card sẽ xuất hiện với hệ điều hành như một webcam.
3. Nếu camera chỉ đang ở **Mass Storage / MTP / PTP** thì OpenCV hiện tại không đọc được live video từ nó. Chế độ tethered still-photo là một pipeline khác và chưa được triển khai trong bản này.

### Tìm camera index

Sau khi cắm camera ngoài:

```bash
python tools/list_cameras.py
```

Ví dụ output:

```text
Camera #0: 1920x1080 @ 30 FPS
Camera #1: 3840x2160 @ 30 FPS
```

Chọn camera ngoài trên macOS/Linux:

```bash
LANTERN_CAMERA_INDEX=1 ./run_mac.sh
```

PowerShell trên Windows:

```powershell
$env:LANTERN_CAMERA_INDEX="1"
.\START_HERE_WINDOWS.bat
```

Camera thực tế có thể không chấp nhận resolution được request. Control UI hiển thị cả **resolution thực tế** và **resolution được request** để kiểm tra.

Các biến cấu hình chính:

```text
LANTERN_CAMERA_INDEX=0
LANTERN_CAMERA_WIDTH=3840
LANTERN_CAMERA_HEIGHT=2160
LANTERN_CAMERA_FPS=30
LANTERN_CAMERA_MJPG=1
LANTERN_PREVIEW_MAX_WIDTH=1280
LANTERN_PREVIEW_FPS=12
```

Frame full-resolution mới nhất luôn được giữ cho thao tác **Scan**. Riêng ArUco live preview được downscale và giới hạn FPS theo hai biến `LANTERN_PREVIEW_*`, giúp giảm CPU mà không giảm độ phân giải PNG cuối.

Scanner tự reconnect nếu camera bị rút cáp hoặc tạm thời ngừng trả frame.

### Để scan nét hơn

- Dùng tripod/arm cố định camera vuông góc tương đối với giấy.
- Ưu tiên optical focus cố định hoặc AF-S ổn định; tránh continuous AF hunting.
- Nếu camera cho phép, khóa exposure/white balance sau khi setup ánh sáng.
- Dùng hai nguồn sáng mềm ở hai bên, tránh hotspot và bóng tay.
- Đặt template đủ lớn trong frame; sau scan Control sẽ trả cảnh báo focus/brightness/marker-size nếu chất lượng có dấu hiệu thấp.
- Resolution cao hơn chỉ có ích khi USB/capture device thực sự xuất được resolution đó; request 4K không tự biến stream 1080p thành 4K.

## Camera không mở

Windows:

- Đóng Zoom, Meet, OBS và app Camera nếu đang giữ thiết bị.
- Chạy `python tools/list_cameras.py`.
- Chọn đúng `LANTERN_CAMERA_INDEX`.

macOS:

- Vào **System Settings → Privacy & Security → Camera**.
- Cấp quyền camera cho Terminal hoặc VS Code.
- Chạy `python tools/list_cameras.py` sau khi cắm camera.

App sẽ tự thử reconnect thay vì bắt buộc restart khi camera mất kết nối.

## Privacy và storage

Mặc định chỉ file PNG lantern cuối cùng được serve cho Display:

```text
runtime/lanterns/
```

Raw camera frame và corrected page **không được public**. Mặc định chúng cũng không được lưu để giảm rủi ro privacy và tránh đầy disk.

Nếu cần diagnostics trong quá trình calibration:

```bash
LANTERN_KEEP_DIAGNOSTICS=1 ./run_mac.sh
```

Khi đó dữ liệu debug được lưu private trong:

```text
runtime/diagnostics/original/
runtime/diagnostics/corrected/
```

Lantern PNG **không có automatic retention limit** trong event. Nếu muốn dọn dữ liệu giữa hai event, hãy backup/xóa `runtime/lanterns/` bằng quy trình vận hành riêng thay vì để app tự xóa ảnh đang tích lũy.

## Đổi Background Display

Mở Control, ở phần **Display background**, bấm **Upload background** rồi chọn JPG, PNG hoặc WEBP.

Ảnh được validate, giới hạn kích thước, re-encode để bỏ metadata và lưu trong `runtime/backgrounds/` thay vì ghi vào source tree. Display đang mở sẽ tự cập nhật và khi WebSocket reconnect nó sẽ đồng bộ lại state.

## Phím Display

- `F`: fullscreen
- `H`: ẩn/hiện controls

## Browser E2E với Playwright

E2E dùng Chromium thật để kiểm tra Control/Display, 4 dây lantern và WebSocket. Lần đầu cài:

```bash
npm ci
npx playwright install chromium
```

Chạy headless:

```bash
npm run test:e2e
```

Chạy có browser để review UI trực tiếp:

```bash
npm run test:e2e:headed
```

Hoặc mở Playwright UI:

```bash
npm run test:e2e:ui
```

Test tự start Lantern Sky ở port `8765`, dùng `runtime/e2e/` riêng và bật `LANTERN_DISABLE_CAMERA=1` để không phụ thuộc camera thật. CI cũng cài Chromium và chạy E2E sau synthetic CV test.

## Self-test

```bash
python tools/self_test.py
```

Self-test chạy synthetic scan cho cả 4 template: detect marker → identify variant → homography → extract alpha PNG. Ngoài happy path, test còn kiểm tra thiếu marker, preview/final detector separation, full processing/storage path, persisted variant metadata, append-only event history, diagnostics-off behavior và explicit maintenance pruning.
