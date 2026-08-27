# Chạy Lantern Sky Trên Windows

## 1. Cài Python

Cài Python 3.11 hoặc mới hơn:

```text
https://www.python.org/downloads/windows/
```

Khi cài Python, nhớ chọn:

```text
Add python.exe to PATH
```

## 2. Mở Terminal trong VS Code

Mở thư mục project bằng VS Code.

Vào:

```text
Terminal -> New Terminal
```

## 3. Lần đầu chạy

Copy lệnh này vào Terminal rồi Enter:

```powershell
.\setup_windows.bat
```

Đợi đến khi hiện:

```text
Setup xong.
```

## 4. Mỗi lần mở app

Copy lệnh này vào Terminal rồi Enter:

```powershell
.\START_HERE_WINDOWS.bat
```

Sau đó mở trình duyệt:

```text
http://127.0.0.1:8000/control
```

Màn hình trình chiếu:

```text
http://127.0.0.1:8000/display
```

## 5. Cách scan

1. In `print/lantern_template.png` ra giấy A4.
2. Vẽ trong phần lồng đèn, không che 4 marker ở góc.
3. Đặt giấy dưới camera.
4. Chờ đủ số `0 1 2 3` sáng lên.
5. Khi thấy `Ready to scan`, bấm `Scan lantern`.

## 6. Đổi background màn hình Display

Mở trang Control:

```text
http://127.0.0.1:8000/control
```

Ở phần `Display background`, bấm `Upload background` rồi chọn ảnh.

Ảnh hỗ trợ: JPG, PNG, WEBP.

Nếu Display đang mở, nền sẽ tự đổi. Nếu chưa thấy đổi, refresh trang Display.

## 7. Nếu camera không lên

Đóng các app đang dùng camera như Zoom, Meet, OBS.

Sau đó tắt Terminal và chạy lại:

```powershell
.\START_HERE_WINDOWS.bat
```

Nếu máy có nhiều camera, thử:

```powershell
$env:LANTERN_CAMERA_INDEX="1"
.\START_HERE_WINDOWS.bat
```

Nếu vẫn chưa được, đổi `1` thành `2` rồi chạy lại.
