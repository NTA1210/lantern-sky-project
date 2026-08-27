# Lantern Sky

Prototype end-to-end: **vẽ lồng đèn → camera scan → perspective correction → PNG alpha → lồng đèn bay trên projector/TV**.

## Chạy Nhanh

### Windows

Xem file `HUONG_DAN_WINDOWS.md`.

Tóm tắt:

1. Mở VS Code trong thư mục project.
2. Mở `Terminal -> New Terminal`.
3. Lần đầu chạy:

```powershell
.\setup_windows.bat
```

4. Những lần sau chạy:

```powershell
.\START_HERE_WINDOWS.bat
```

### macOS / Linux

```bash
./run_mac.sh
```

## Màn hình

- Control: `http://127.0.0.1:8000/control`
- Display: `http://127.0.0.1:8000/display`

## Quy trình sử dụng

1. In `print/lantern_template.png` ở A4, 100% / Actual Size.
2. Người dùng vẽ trong thân lồng đèn, không che 4 marker.
3. Mở Control và Display.
4. Đặt giấy dưới camera.
5. Khi hiện **Ready to scan**, bấm **Scan lantern**.
6. PNG được tạo ở `generated/lanterns/` và tự spawn trên Display.

## Camera không mở

Windows:

- Đóng Zoom, Meet, OBS hoặc app Camera nếu đang mở.
- Tắt Terminal rồi chạy lại `.\START_HERE_WINDOWS.bat`.
- Nếu máy có nhiều camera, xem `HUONG_DAN_WINDOWS.md`.

macOS:

- Vào **System Settings -> Privacy & Security -> Camera**.
- Cấp quyền camera cho Terminal hoặc VS Code.

## Chất lượng scan

- Camera cố định, giấy phẳng.
- Hai nguồn sáng mềm ở hai bên, tránh hotspot/bóng tay.
- Đặt giấy sao cho camera thấy đủ 4 marker `0 1 2 3`.

## Đổi Background Display

Mở Control, ở phần **Display background**, bấm **Upload background** rồi chọn ảnh JPG, PNG hoặc WEBP.

Nếu Display đang mở, nền sẽ tự cập nhật.

## Phím Display

- `F`: fullscreen
- `H`: ẩn/hiện controls
