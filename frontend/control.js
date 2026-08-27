const badge = document.querySelector('#readyBadge');
const scan = document.querySelector('#scanButton');
const demo = document.querySelector('#demoButton');
const msg = document.querySelector('#message');
const result = document.querySelector('#resultImage');
const meta = document.querySelector('#cameraMeta');
const cameraWrap = document.querySelector('#cameraWrap');
const cameraEmpty = document.querySelector('#cameraEmpty');
const backgroundInput = document.querySelector('#backgroundInput');
const backgroundMessage = document.querySelector('#backgroundMessage');
const markers = [...document.querySelectorAll('.marker')];

let lastMessage = '';

function message(text, type = '') {
  if (text === lastMessage) return;
  lastMessage = text;
  msg.textContent = text;
  msg.style.color = type === 'error' ? '#ff9e9e' : type === 'success' ? '#86f0b4' : '#b8c3da';
}

function setPreviewState(state, title, detail) {
  cameraWrap.classList.toggle('is-loading', state === 'loading');
  cameraWrap.classList.toggle('is-unavailable', state === 'unavailable');
  if (title) {
    cameraEmpty.innerHTML = `<strong>${title}</strong><span>${detail || ''}</span>`;
  }
}

function setBadge(text, state = '') {
  badge.textContent = text;
  badge.className = state ? `badge ${state}` : 'badge';
}

async function poll() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    const data = await response.json();
    const found = new Set(data.markerIds || []);

    markers.forEach((marker) => {
      marker.classList.toggle('found', found.has(Number(marker.dataset.id)));
    });

    const [width, height] = data.resolution || [0, 0];
    scan.disabled = true;

    if (!data.cameraOpen) {
      meta.textContent = 'Camera unavailable';
      setBadge('Camera error', 'error');
      setPreviewState('unavailable', 'Camera unavailable', 'Check camera permission or LANTERN_CAMERA_INDEX, then restart the app.');
      message(data.error || 'Không mở được camera.', 'error');
      return;
    }

    meta.textContent = `${width} x ${height}${data.fps ? ` · ${data.fps.toFixed(0)} FPS` : ''}`;
    setPreviewState('ready');

    if (data.error) {
      setBadge('Camera warning', 'error');
      message(data.error, 'error');
      return;
    }

    if (data.readyToScan) {
      setBadge('Ready to scan', 'ready');
      scan.disabled = false;
      message('Đủ marker. Có thể scan lantern.');
      return;
    }

    setBadge(`Markers ${found.size}/4`);
    message('Đặt toàn bộ template trong khung hình, không che marker 0-3.');
  } catch (error) {
    scan.disabled = true;
    meta.textContent = 'Server disconnected';
    setBadge('Disconnected', 'error');
    setPreviewState('unavailable', 'Server disconnected', 'Make sure the Lantern Sky app is still running.');
    message('Không kết nối được server.', 'error');
  }
}

scan.onclick = async () => {
  scan.disabled = true;
  message('Đang chụp và xử lý ảnh...');
  try {
    const response = await fetch('/api/scan', { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || 'Scan failed');
    result.src = `${data.lanternUrl}?t=${Date.now()}`;
    message(`Đã tạo ${data.id} và gửi sang Display.`, 'success');
  } catch (error) {
    message(error.message, 'error');
  } finally {
    setTimeout(poll, 300);
  }
};

demo.onclick = async () => {
  await fetch('/api/demo', { method: 'POST' });
  message('Đã gửi demo lantern sang Display.', 'success');
};

backgroundInput.onchange = async () => {
  const file = backgroundInput.files && backgroundInput.files[0];
  if (!file) return;

  backgroundMessage.textContent = 'Đang upload ảnh nền...';
  backgroundMessage.style.color = '#b8c3da';

  try {
    const response = await fetch('/api/background', {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || 'Upload failed');

    backgroundMessage.textContent = 'Đã đổi background. Display sẽ tự cập nhật.';
    backgroundMessage.style.color = '#86f0b4';
  } catch (error) {
    backgroundMessage.textContent = error.message;
    backgroundMessage.style.color = '#ff9e9e';
  } finally {
    backgroundInput.value = '';
  }
};

poll();
setInterval(poll, 600);
