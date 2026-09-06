const badge = document.querySelector('#readyBadge');
const scan = document.querySelector('#scanButton');
const demo = document.querySelector('#demoButton');
const msg = document.querySelector('#message');
const result = document.querySelector('#resultImage');
const meta = document.querySelector('#cameraMeta');
const templateMeta = document.querySelector('#templateMeta');
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

function updateMarkerSlots(requiredIds, found) {
  markers.forEach((marker, index) => {
    const markerId = requiredIds[index];
    marker.textContent = Number.isInteger(markerId) ? markerId : '–';
    marker.classList.toggle('found', Number.isInteger(markerId) && found.has(markerId));
  });
}

async function poll() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    const data = await response.json();
    const found = new Set(data.markerIds || []);
    const requiredIds = data.requiredMarkerIds || [];
    updateMarkerSlots(requiredIds, found);

    const [width, height] = data.resolution || [0, 0];
    const [requestedWidth, requestedHeight] = data.requestedResolution || [0, 0];
    scan.disabled = true;

    if (!data.cameraOpen) {
      meta.textContent = `Camera #${data.cameraIndex ?? 0} unavailable`;
      templateMeta.textContent = 'Waiting for camera...';
      setBadge('Camera error', 'error');
      setPreviewState(
        'unavailable',
        'Camera unavailable',
        'Kiểm tra cáp/quyền Camera hoặc LANTERN_CAMERA_INDEX. App sẽ tự reconnect.'
      );
      message(data.error || 'Không mở được camera.', 'error');
      return;
    }

    const requested = requestedWidth && requestedHeight && (requestedWidth !== width || requestedHeight !== height)
      ? ` · requested ${requestedWidth} x ${requestedHeight}`
      : '';
    meta.textContent = `Camera #${data.cameraIndex ?? 0} · ${width} x ${height}${requested}${data.fps ? ` · ${data.fps.toFixed(0)} FPS` : ''}`;
    templateMeta.textContent = data.variantLabel
      ? `Template: ${data.variantLabel} · markers ${requiredIds.join(', ')}`
      : 'Đưa một trong bốn template vào camera.';
    setPreviewState('ready');

    if (data.error) {
      setBadge('Camera warning', 'error');
      message(data.error, 'error');
      return;
    }

    if (data.readyToScan) {
      setBadge(`Ready · ${data.variantLabel || 'Template'}`, 'ready');
      scan.disabled = false;
      message(`Đủ marker cho mẫu ${data.variantLabel || ''}. Có thể scan lantern.`);
      return;
    }

    const foundExpected = requiredIds.filter((id) => found.has(id)).length;
    setBadge(requiredIds.length ? `Markers ${foundExpected}/4` : 'Find template');
    message('Đặt toàn bộ template trong khung hình và không che bốn marker góc.');
  } catch (error) {
    scan.disabled = true;
    meta.textContent = 'Server disconnected';
    templateMeta.textContent = 'Waiting for server...';
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
    const warnings = data.quality?.warnings || [];
    const warningText = warnings.length ? ` Cảnh báo chất lượng: ${warnings.join(' ')}` : '';
    message(`Đã tạo ${data.variantLabel || 'lantern'} ${data.id} và gửi sang Display.${warningText}`, warnings.length ? '' : 'success');
  } catch (error) {
    message(error.message, 'error');
  } finally {
    setTimeout(poll, 300);
  }
};

demo.onclick = async () => {
  try {
    const response = await fetch('/api/demo', { method: 'POST' });
    if (!response.ok) throw Error('Demo failed');
    message('Đã gửi demo lantern sang Display.', 'success');
  } catch (error) {
    message(error.message, 'error');
  }
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
setInterval(poll, 700);
