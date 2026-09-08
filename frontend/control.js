const badge = document.querySelector('#readyBadge');
const cameraSelect = document.querySelector('#cameraSelect');
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
const autoScanToggle = document.querySelector('#autoScanToggle');
const countdownTrack = document.querySelector('#countdownTrack');
const countdownBar = document.querySelector('#countdownBar');
const markers = [...document.querySelectorAll('.marker')];

// Elements quản lý lồng đèn
const lanternManageMeta = document.querySelector('#lanternManageMeta');
const toggleSequentialBtn = document.querySelector('#toggleSequentialBtn');
const deleteAllBtn = document.querySelector('#deleteAllBtn');
const recentGallery = document.querySelector('#recentGallery');

// Elements modal popup
const confirmModal = document.querySelector('#confirmModal');
const modalTitle = document.querySelector('#modalTitle');
const modalMessage = document.querySelector('#modalMessage');
const modalCancelBtn = document.querySelector('#modalCancelBtn');
const modalConfirmBtn = document.querySelector('#modalConfirmBtn');

const AUTO_SCAN_DURATION_MS = 2000;  // Giảm thời gian tự động scan xuống 2 giây
const FLICKER_GRACE_PERIOD_MS = 800; // Giữ trạng thái khi mất marker 1-2 frame
const POST_SCAN_COOLDOWN_MS = 3500;  // Tránh scan liên tục cùng 1 tờ giấy

let isScanning = false;
let stableStartAt = null;
let lastSeenCompleteAt = null;
let lastSeenVariant = null;
let cooldownUntil = 0;
let lastMessage = '';
let currentModalAction = null;
let latestTotalCount = 0;
let isSequentialDeleting = false;

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

function setCountdownProgress(percent) {
  if (percent > 0) {
    countdownTrack.classList.add('active');
    countdownBar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  } else {
    countdownTrack.classList.remove('active');
    countdownBar.style.width = '0%';
  }
}

// Modal confirmation system
function showConfirm(title, text, onConfirm) {
  modalTitle.textContent = title;
  modalMessage.textContent = text;
  currentModalAction = onConfirm;
  confirmModal.classList.remove('hidden');
}

function hideConfirm() {
  confirmModal.classList.add('hidden');
  currentModalAction = null;
}

modalCancelBtn.onclick = hideConfirm;
modalConfirmBtn.onclick = async () => {
  const action = currentModalAction;
  hideConfirm();
  if (typeof action === 'function') {
    await action();
  }
};

const refreshCamerasBtn = document.querySelector('#refreshCamerasBtn');
let isSwitchingCamera = false;

async function fetchCameras(showToastOnDone = false) {
  if (!cameraSelect || isSwitchingCamera) return;
  try {
    const res = await fetch('/api/cameras', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    const current = data.current ?? 0;
    const cameras = data.cameras || [];
    
    // Format options with real device names
    const optionsHtml = cameras.map((c) => {
      const isSelected = c.index === current ? ' selected' : '';
      return `<option value="${c.index}"${isSelected}>${c.label}</option>`;
    }).join('');

    cameraSelect.innerHTML = optionsHtml;
    if (showToastOnDone) {
      showToast(`Đã tìm thấy ${cameras.length} thiết bị camera!`, 'success');
    }
  } catch (e) {}
}

if (refreshCamerasBtn) {
  refreshCamerasBtn.onclick = async () => {
    refreshCamerasBtn.style.transform = 'rotate(360deg)';
    refreshCamerasBtn.style.transition = 'transform 0.4s ease';
    await fetchCameras(true);
    setTimeout(() => {
      refreshCamerasBtn.style.transform = 'none';
      refreshCamerasBtn.style.transition = 'none';
    }, 450);
  };
}

if (cameraSelect) {
  cameraSelect.onchange = async () => {
    const newIndex = parseInt(cameraSelect.value);
    if (Number.isNaN(newIndex)) return;
    isSwitchingCamera = true;
    message(`Đang chuyển sang Camera #${newIndex}...`);
    showToast(`Đang kết nối Camera #${newIndex}...`, 'info');
    try {
      const res = await fetch('/api/cameras/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: newIndex }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Không thể đổi camera');
      showToast(`Đã chuyển sang Camera #${newIndex}!`, 'success');
      message(`Đã chuyển sang Camera #${newIndex}.`, 'success');
      // Re-trigger preview stream
      const streamImg = document.querySelector('#cameraStream');
      if (streamImg) {
        streamImg.src = `/api/camera/stream?t=${Date.now()}`;
      }
    } catch (e) {
      showToast(e.message, 'error');
      message(e.message, 'error');
    } finally {
      setTimeout(() => {
        isSwitchingCamera = false;
        fetchCameras();
      }, 1500);
    }
  };
}

async function fetchRecentLanterns() {
  try {
    const res = await fetch('/api/recent?limit=8', { cache: 'no-store' });
    if (!res.ok) return;
    const items = await res.json();
    renderRecentGallery(items);
  } catch (e) {
    console.error(e);
  }
}

function renderRecentGallery(items) {
  if (!recentGallery) return;
  recentGallery.innerHTML = '';
  if (!items || !items.length) {
    recentGallery.innerHTML = '<span class="muted small" style="padding:10px;">Chưa có lồng đèn nào được scan.</span>';
    return;
  }
  // Hiển thị mới nhất trước
  const reversed = [...items].reverse();
  reversed.forEach((item) => {
    const div = document.createElement('div');
    div.className = 'recent-item';
    div.title = `ID: ${item.id} (${item.variant || 'classic'})`;
    div.innerHTML = `
      <img src="${item.url}?t=${Date.now()}" alt="${item.id}">
      <button class="recent-delete-btn" title="Xóa đèn này" data-id="${item.id}">✕</button>
    `;
    div.querySelector('.recent-delete-btn').onclick = (e) => {
      e.stopPropagation();
      showConfirm(
        'Xóa lồng đèn này?',
        `Bạn có chắc chắn muốn làm mờ và xóa lồng đèn [${item.variant || 'lantern'}] ${item.id} khỏi màn hình không?`,
        () => deleteSingleLantern(item.id)
      );
    };
    recentGallery.appendChild(div);
  });
}

async function deleteSingleLantern(scanId) {
  try {
    message(`Đang xóa lồng đèn ${scanId}...`);
    const res = await fetch(`/api/lanterns/${encodeURIComponent(scanId)}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Xóa thất bại');
    latestTotalCount = data.totalCount ?? 0;
    updateTotalMeta();
    message(`Đã xóa lồng đèn ${scanId}.`, 'success');
    await fetchRecentLanterns();
  } catch (e) {
    message(e.message, 'error');
  }
}

function showToast(text, type = 'success', durationMs = 4000) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icon = type === 'success' ? '✨' : type === 'error' ? '⚠️' : 'ℹ️';
  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <div class="toast-body">${text}</div>
    <button class="toast-close">✕</button>
  `;
  const close = () => {
    toast.classList.add('toast-hiding');
    setTimeout(() => toast.remove(), 300);
  };
  toast.querySelector('.toast-close').onclick = close;
  container.appendChild(toast);
  setTimeout(close, durationMs);
}

function connectControlWs() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'sequential_delete_completed') {
        const wasDeleting = isSequentialDeleting;
        isSequentialDeleting = false;
        updateSequentialBtnUI();
        if (Number.isFinite(Number(payload.totalCount))) {
          latestTotalCount = payload.totalCount;
          updateTotalMeta();
        }
        showToast('Đã hoàn tất xóa lần lượt tất cả lồng đèn!', 'success');
        message('Đã hoàn tất xóa lần lượt tất cả lồng đèn.', 'success');
        fetchRecentLanterns();
      }
      if (payload.type === 'all_lanterns_fading_out' || payload.type === 'lanterns_cleared') {
        isSequentialDeleting = false;
        updateSequentialBtnUI();
        latestTotalCount = 0;
        updateTotalMeta();
        fetchRecentLanterns();
        showToast('Đã xóa toàn bộ lồng đèn!', 'success');
      }
      if (payload.type === 'lantern_fading_out' || payload.type === 'pop_oldest_lantern') {
        if (Number.isFinite(Number(payload.totalCount))) {
          latestTotalCount = payload.totalCount;
          updateTotalMeta();
        }
        fetchRecentLanterns();
      }
    } catch (e) {}
  };
  ws.onclose = () => setTimeout(connectControlWs, 1500);
}

async function startSequentialDelete() {
  try {
    message('Đang bắt đầu xóa lần lượt từng lồng đèn (1s/đèn)...');
    const res = await fetch('/api/lanterns/sequential-delete/start', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Không thể bắt đầu xóa');
    isSequentialDeleting = true;
    updateSequentialBtnUI();
    showToast('Đang xóa lần lượt từng đèn (1s/đèn)...', 'info');
    message('Đang xóa lần lượt từng đèn (1s/đèn)...', 'success');
  } catch (e) {
    message(e.message, 'error');
    showToast(e.message, 'error');
  }
}

async function stopSequentialDelete() {
  try {
    message('Đang dừng xóa lần lượt...');
    const res = await fetch('/api/lanterns/sequential-delete/stop', { method: 'POST' });
    const data = await res.json();
    isSequentialDeleting = false;
    updateSequentialBtnUI();
    showToast('Đã dừng xóa lần lượt.', 'info');
    message('Đã dừng xóa lần lượt.', 'success');
    await fetchRecentLanterns();
  } catch (e) {
    message(e.message, 'error');
  }
}

function updateSequentialBtnUI() {
  if (!toggleSequentialBtn) return;
  if (isSequentialDeleting) {
    toggleSequentialBtn.textContent = '⏹ Dừng xóa lần lượt';
    toggleSequentialBtn.className = 'button danger-outline';
  } else {
    toggleSequentialBtn.textContent = '▶ Xóa lần lượt (1s/đèn)';
    toggleSequentialBtn.className = 'button secondary';
  }
}

toggleSequentialBtn.onclick = () => {
  if (isSequentialDeleting) {
    stopSequentialDelete();
  } else {
    showConfirm(
      'Bắt đầu xóa lần lượt?',
      'Hệ thống sẽ làm mờ và xóa lần lượt từng lồng đèn (cách nhau 1 giây) từ cũ nhất đến mới nhất. Bạn có chắc muốn bắt đầu không?',
      startSequentialDelete
    );
  }
};

async function deleteAllLanterns() {
  try {
    message('Đang làm mờ và xóa toàn bộ lồng đèn...');
    const res = await fetch('/api/lanterns', { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Xóa tất cả thất bại');
    latestTotalCount = 0;
    updateTotalMeta();
    result.src = '/static/sample_lantern.png';
    message(`Đã xóa toàn bộ ${data.deletedCount || 0} lồng đèn. Màn hình chiếu đang mờ dần và reset.`, 'success');
    await fetchRecentLanterns();
  } catch (e) {
    message(e.message, 'error');
  }
}

function updateTotalMeta() {
  if (lanternManageMeta) {
    lanternManageMeta.textContent = `Tổng số đèn: ${latestTotalCount.toLocaleString('vi-VN')} chiếc`;
  }
}

deleteAllBtn.onclick = () => {
  showConfirm(
    '⚠️ XÓA TẤT CẢ LỒNG ĐÈN?',
    'Hành động này sẽ làm mờ và xóa TOÀN BỘ lồng đèn đã quét khỏi hệ thống và màn hình hiển thị. Bạn có chắc chắn muốn tiếp tục không?',
    deleteAllLanterns
  );
};

async function doScan(isAuto = false) {
  if (isScanning) return;
  isScanning = true;
  scan.disabled = true;
  setCountdownProgress(0);
  message(isAuto ? '⚡ Tự động chụp và xử lý ảnh...' : '📸 Đang chụp và xử lý ảnh...');

  try {
    const response = await fetch('/api/scan', { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || 'Scan failed');

    result.src = `${data.lanternUrl}?t=${Date.now()}`;
    const warnings = data.quality?.warnings || [];
    const warningText = warnings.length ? ` (Cảnh báo: ${warnings.join(' ')})` : '';
    latestTotalCount = data.totalCount ?? latestTotalCount + 1;
    updateTotalMeta();

    message(`Đã tạo thành công [${data.variantLabel || 'Lantern'}] ${data.id}.${warningText}`, warnings.length ? '' : 'success');

    // Bật Cooldown sau khi scan thành công
    cooldownUntil = Date.now() + POST_SCAN_COOLDOWN_MS;
    stableStartAt = null;
    lastSeenCompleteAt = null;
    lastSeenVariant = null;
    await fetchRecentLanterns();
  } catch (error) {
    message(error.message, 'error');
    cooldownUntil = Date.now() + 1000;
    stableStartAt = null;
  } finally {
    isScanning = false;
    setTimeout(poll, 300);
  }
}

async function poll() {
  if (isScanning) return;

  try {
    // Đồng bộ trạng thái xóa lần lượt
    try {
      const seqRes = await fetch('/api/lanterns/sequential-delete/status', { cache: 'no-store' });
      if (seqRes.ok) {
        const seqData = await seqRes.json();
        const isNowActive = !!seqData.active;
        if (isSequentialDeleting !== isNowActive) {
          const wasDeleting = isSequentialDeleting;
          isSequentialDeleting = isNowActive;
          updateSequentialBtnUI();
          if (wasDeleting && !isNowActive) {
            showToast('Đã hoàn tất xóa lần lượt tất cả lồng đèn!', 'success');
            message('Đã hoàn tất xóa lần lượt tất cả lồng đèn.', 'success');
            fetchRecentLanterns();
          }
        }
        if (Number.isFinite(Number(seqData.totalCount))) {
          latestTotalCount = seqData.totalCount;
          updateTotalMeta();
        }
      }
    } catch (e) {}

    const response = await fetch('/api/status', { cache: 'no-store' });
    const data = await response.json();
    const found = new Set(data.markerIds || []);
    const requiredIds = data.requiredMarkerIds || [];
    updateMarkerSlots(requiredIds, found);

    const [width, height] = data.resolution || [0, 0];
    const [requestedWidth, requestedHeight] = data.requestedResolution || [0, 0];
    const autoScanEnabled = autoScanToggle ? autoScanToggle.checked : true;
    const now = Date.now();

    if (!data.cameraOpen) {
      stableStartAt = null;
      setCountdownProgress(0);
      scan.disabled = true;
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
      stableStartAt = null;
      setCountdownProgress(0);
      scan.disabled = true;
      setBadge('Camera warning', 'error');
      message(data.error, 'error');
      return;
    }

    // Xử lý Cooldown sau scan
    if (now < cooldownUntil) {
      setCountdownProgress(0);
      scan.disabled = true;
      // Rút giấy ra -> giải phóng cooldown ngay
      if (found.size === 0) {
        cooldownUntil = 0;
      } else {
        const cooldownLeft = Math.ceil((cooldownUntil - now) / 1000);
        setBadge('Scan xong', 'ready');
        message(`Đã scan xong! Rút giấy ra hoặc đổi giấy mới (${cooldownLeft}s)...`, 'success');
        return;
      }
    }

    // Trường hợp 1: Nhận diện ĐỦ 4 marker
    if (data.readyToScan) {
      lastSeenCompleteAt = now;
      const currentVariant = data.variant || 'template';

      if (lastSeenVariant !== currentVariant || !stableStartAt) {
        stableStartAt = now;
        lastSeenVariant = currentVariant;
      }

      const elapsed = now - stableStartAt;
      const progressRatio = Math.min(1, elapsed / AUTO_SCAN_DURATION_MS);
      const remainingSec = Math.max(0, Math.ceil((AUTO_SCAN_DURATION_MS - elapsed) / 1000));

      scan.disabled = false;

      if (autoScanEnabled) {
        setCountdownProgress(progressRatio * 100);
        setBadge(`Tự scan ${remainingSec}s · ${data.variantLabel || 'Ready'}`, 'ready');
        scan.textContent = `Scan ngay (${remainingSec}s)`;
        message(`Giữ yên giấy! Tự động scan sau ${remainingSec}s... (hoặc bấm Scan ngay)`, 'success');

        if (elapsed >= AUTO_SCAN_DURATION_MS) {
          doScan(true);
          return;
        }
      } else {
        setCountdownProgress(0);
        setBadge(`Ready · ${data.variantLabel || 'Template'}`, 'ready');
        scan.textContent = 'Scan lantern';
        message(`Đủ marker cho mẫu ${data.variantLabel || ''}. Có thể scan lantern.`);
      }
      return;
    }

    // Trường hợp 2: Chập chờn mất marker trong khoảng thời gian ngắn
    const timeSinceComplete = lastSeenCompleteAt ? now - lastSeenCompleteAt : Infinity;
    if (timeSinceComplete < FLICKER_GRACE_PERIOD_MS && stableStartAt && autoScanEnabled) {
      const elapsed = lastSeenCompleteAt - stableStartAt;
      const progressRatio = Math.min(1, elapsed / AUTO_SCAN_DURATION_MS);
      const remainingSec = Math.max(1, Math.ceil((AUTO_SCAN_DURATION_MS - elapsed) / 1000));
      setCountdownProgress(progressRatio * 100);
      setBadge(`Đang giữ nét · ${remainingSec}s`, 'ready');
      message('Đang giữ vị trí... Hãy để phẳng giấy.', '');
      scan.disabled = false;
      return;
    }

    // Trường hợp 3: Mất hoàn toàn marker
    stableStartAt = null;
    lastSeenVariant = null;
    setCountdownProgress(0);
    scan.disabled = true;
    scan.textContent = 'Scan lantern';

    const foundExpected = requiredIds.filter((id) => found.has(id)).length;
    setBadge(requiredIds.length ? `Markers ${foundExpected}/4` : 'Find template');
    message('Đặt toàn bộ template trong khung hình và không che bốn marker góc.');
  } catch (error) {
    stableStartAt = null;
    setCountdownProgress(0);
    scan.disabled = true;
    scan.textContent = 'Scan lantern';
    meta.textContent = 'Server disconnected';
    templateMeta.textContent = 'Waiting for server...';
    setBadge('Disconnected', 'error');
    setPreviewState('unavailable', 'Server disconnected', 'Make sure the Lantern Sky app is still running.');
    message('Không kết nối được server.', 'error');
  }
}

scan.onclick = () => doScan(false);

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

connectControlWs();
fetchCameras();
fetchRecentLanterns();
poll();
setInterval(poll, 250);



