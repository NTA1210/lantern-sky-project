# Chạy Lantern Sky Trên Windows

## 1. Cài Python

Cài Python 3.11 hoặc mới hơn từ python.org và nhớ chọn `Add python.exe to PATH`.

## 2. Mở Terminal trong VS Code

Mở thư mục project bằng VS Code rồi vào `Terminal -> New Terminal`.

## 3. Lần đầu chạy

```powershell
.\setup_windows.bat
```

Đợi đến khi hiện `Setup xong.`. Bước này cài dependency, tạo đủ 4 printable template và chạy synthetic self-test.

## 4. Mỗi lần mở app

```powershell
.\START_HERE_WINDOWS.bat
```

Control:

```text
http://127.0.0.1:8000/control
```

Display:

```text
http://127.0.0.1:8000/display
```

Server mặc định chỉ listen trên localhost vì Control và Display chạy cùng máy.

## 5. Cách scan

Có 4 mẫu:

- `print/lantern_template.png` — Classic — marker 0,1,2,3
- `print/lantern_template_balloon.png` — Balloon — marker 4,5,6,7
- `print/lantern_template_round.png` — Round — marker 8,9,10,11
- `print/lantern_template_rectangle.png` — Rectangle — marker 12,13,14,15

Quy trình:

1. In một template A4 ở 100% / Actual Size.
2. Vẽ bên trong silhouette, không che 4 marker.
3. Đặt giấy dưới camera.
4. Control tự nhận dạng mẫu và hiển thị đúng bộ marker.
5. Khi thấy `Ready`, bấm `Scan lantern`.

## 6. Đổi background Display

Ở trang Control, bấm `Upload background` rồi chọn JPG, PNG hoặc WEBP. Background được lưu trong runtime data, không ghi vào source code.

## 7. Camera ngoài / Sony

Lantern Sky hỗ trợ camera ngoài nếu Windows nhận nó như webcam/UVC device.

Các cách phổ biến:

- Sony có chế độ USB Streaming/UVC: nối USB trực tiếp và bật USB Streaming trên camera.
- Sony qua clean HDMI: nối HDMI vào USB capture card, rồi capture card vào laptop.
- Nếu camera chỉ ở Mass Storage/MTP/PTP thì OpenCV không nhận đó là live camera.

Sau khi cắm camera, chạy:

```powershell
python tools\list_cameras.py
```

Ví dụ nếu Sony/capture card là camera #1:

```powershell
$env:LANTERN_CAMERA_INDEX="1"
.\START_HERE_WINDOWS.bat
```

Muốn request 4K/30fps:

```powershell
$env:LANTERN_CAMERA_WIDTH="3840"
$env:LANTERN_CAMERA_HEIGHT="2160"
$env:LANTERN_CAMERA_FPS="30"
.\START_HERE_WINDOWS.bat
```

Control sẽ hiển thị resolution thực tế. Camera/capture card có thể tự hạ xuống 1080p nếu thiết bị không xuất được 4K.

## 8. Nếu camera không lên

1. Đóng Zoom, Meet, OBS và app Camera nếu đang giữ thiết bị.
2. Kiểm tra dây USB/HDMI capture.
3. Chạy `python tools\list_cameras.py`.
4. Chọn lại `LANTERN_CAMERA_INDEX`.
5. Kiểm tra Windows Camera privacy permission.

Scanner hiện tự reconnect nếu camera bị rút cáp hoặc tạm ngừng trả frame, nên không nhất thiết phải restart app ngay.
