# Hướng Dẫn Triển Khai Lantern Sky Lên VPS + Nginx

Kiến trúc production khi host lên VPS:
- **Database**: SQLite WAL (`runtime/lantern_sky.db`) tự động khởi tạo và đồng bộ với ảnh PNG trên disk.
- **Tối ưu băng thông 200+ user**: Ảnh hiển thị trên `/display` dùng thumbnail WebP RGBA nhẹ (`runtime/thumbs/*.webp`, ~20–50 KB/ảnh) với `Cache-Control: immutable` + nén `GZip` + cache `/api/display-state` trong RAM + WebSocket broadcast song song có timeout & reconnect jitter.
- **Quét bản vẽ từ xa**: Trên trang `/control`, admin bật biểu tượng **🌐** để dùng **Camera trình duyệt** (`getUserMedia`, hỗ trợ cả tự động nhận 4 marker ArUco) hoặc dùng nút **📷 Quét từ ảnh** để tải/chụp ảnh trực tiếp từ máy tính/điện thoại. *(Lưu ý: `getUserMedia` trên trình duyệt bắt buộc chạy **HTTPS** trừ localhost.)*

## 1. Chuẩn bị môi trường trên VPS Ubuntu

```bash
cd /opt/lantern_sky_project
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-server.txt
python tools/generate_template.py
```

## 2. Cấu hình biến môi trường `.env`

```bash
cp .env.example .env
nano .env
```

Đặt tối thiểu các biến sau trong `.env`:

```env
LANTERN_CONTROL_USER=admin
LANTERN_CONTROL_PASSWORD=mat-khau-manh-cua-ban
LANTERN_AUTH_SECRET=chuoi-ngau-nhien-dai-64-ky-tu
LANTERN_COOKIE_SECURE=auto
LANTERN_DISABLE_CAMERA=1
LANTERN_NO_BROWSER=1
LANTERN_RELOAD=0
```

## 3. Chạy dịch vụ nền bằng systemd

```bash
sudo cp deploy/lantern-sky.service /etc/systemd/system/lantern-sky.service
# Chỉnh đường dẫn WorkingDirectory / User nếu khác /opt/lantern_sky_project
sudo systemctl daemon-reload
sudo systemctl enable --now lantern-sky
sudo systemctl status lantern-sky
```

> **Lưu ý**: Giữ `--workers 1` để WebSocket broadcast in-memory đồng bộ tức thời cho tất cả 200+ người xem, và giữ `--proxy-headers` để nhận diện đúng HTTPS (`X-Forwarded-Proto`) và IP thật cho giới hạn đăng nhập.

## 4. Cấu hình Nginx & SSL HTTPS

```bash
sudo cp deploy/nginx-lantern-sky.conf /etc/nginx/sites-available/lantern-sky
# Thay your-domain.com bằng tên miền thật của bạn
sudo ln -s /etc/nginx/sites-available/lantern-sky /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Cấp chứng chỉ HTTPS miễn phí (bắt buộc để dùng Camera trình duyệt trên /control)
sudo certbot --nginx -d your-domain.com
```

## 5. Kiểm tra sau khi chạy

- Health check: `curl https://your-domain.com/healthz` -> `{"ok": true, "db": "ok", ...}`
- Màn hình công khai cho 200+ user: `https://your-domain.com/display`
- Trang điều khiển cho admin (có xác thực): `https://your-domain.com/control`

