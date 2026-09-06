# Lantern Sky

Prototype/event installation end-to-end: **vẽ lồng đèn → camera scan → perspective correction → PNG alpha → lồng đèn bay trên projector/TV**.

## Chạy nhanh

Lantern Sky hiện mặc định chỉ bind vào `127.0.0.1` vì **Control và Display chạy trên cùng laptop**. Thiết bị khác trong Wi-Fi/LAN sẽ không truy cập được Control, camera stream hoặc API.

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

`run_mac.sh` không còn cài package và chạy self-test lại ở mỗi lần mở app, giúp startup tại event ổn định hơn.

## Màn hình

- Control: `http://127.0.0.1:8000/control`
- Display: `http://127.0.0.1:8000/display`

## 4 mẫu lồng đèn

Project hỗ trợ 4 silhouette. Mỗi template có một bộ ArUco marker riêng, nên scanner tự nhận ra mẫu mà operator không cần chọn thủ công.

| Template | File in | Marker IDs |
| --- | --- | --- |
| Classic (mẫu cũ) | `print/lantern_template.png` | 0, 1, 2, 3 |
| Balloon / giọt nước | `print/lantern_template_balloon.png` | 4, 5, 6, 7 |
| Round / tròn | `print/lantern_template_round.png` | 8, 9, 10, 11 |
| Rectangle / hộp | `print/lantern_template_rectangle.png` | 12, 13, 14, 15 |

Có thể mở các template trực tiếp từ Control UI ở mục **Printable lantern templates**.

Nếu cần tạo lại template:

```bash
python tools/generate_template.py
```

Luôn in A4 ở **100% / Actual Size**.

## Quy trình sử dụng

1. Chọn và in một trong bốn template.
2. Người dùng vẽ bên trong silhouette, không che 4 marker.
3. Mở Control và Display.
4. Đặt giấy dưới camera.
5. Control sẽ hiện tên template và `Ready` khi đủ đúng bộ marker.
6. Bấm **Scan lantern**.
7. PNG alpha được tạo trong `runtime/lanterns/` và tự spawn trên Display.

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
```

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

- Đóng Zoom, Meet, OBS hoặc app Camera nếu đang giữ thiết bị.
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

Runtime tự giữ tối đa 240 lantern gần nhất theo mặc định. Có thể đổi bằng:

```text
LANTERN_MAX_STORED=240
```

## Đổi Background Display

Mở Control, ở phần **Display background**, bấm **Upload background** rồi chọn JPG, PNG hoặc WEBP.

Ảnh được validate, giới hạn kích thước, re-encode để bỏ metadata và lưu trong `runtime/backgrounds/` thay vì ghi vào source tree. Display đang mở sẽ tự cập nhật và khi WebSocket reconnect nó sẽ đồng bộ lại state.

## Phím Display

- `F`: fullscreen
- `H`: ẩn/hiện controls

## Self-test

```bash
python tools/self_test.py
```

Self-test hiện chạy synthetic scan cho cả 4 template: detect marker → identify variant → homography → extract alpha PNG.
