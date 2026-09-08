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
const autoScanLabel = document.querySelector('#autoScanLabel');
const countdownTrack = document.querySelector('#countdownTrack');
const countdownBar = document.querySelector('#countdownBar');
const markers = [...document.querySelectorAll('.marker')];

// Elements quản lý lồng đèn
const lanternManageMeta = document.querySelector('#lanternManageMeta');
const toggleSequentialBtn = document.querySelector('#toggleSequentialBtn');
const deleteAllBtn = document.querySelector('#deleteAllBtn');
const recentGallery = document.querySelector('#recentGallery');
const deleteQtyInput = document.querySelector('#deleteQtyInput');
const qtyAllBtn = document.querySelector('#qtyAllBtn');
const qtyMinusBtn = document.querySelector('#qtyMinusBtn');
const qtyPlusBtn = document.querySelector('#qtyPlusBtn');

// Elements Popup Cài đặt thông số (Settings Modal)
const openSettingsBtn = document.querySelector('#openSettingsBtn');
const settingsModal = document.querySelector('#settingsModal');
const settingsModalCloseBtn = document.querySelector('#settingsModalCloseBtn');
const cancelSettingsBtn = document.querySelector('#cancelSettingsBtn');
const saveSettingsBtn = document.querySelector('#saveSettingsBtn');
const resetSettingsBtn = document.querySelector('#resetSettingsBtn');

const conveyorSpeedInput = document.querySelector('#conveyorSpeedInput');
const conveyorSpeedSlider = document.querySelector('#conveyorSpeedSlider');
const swayAmpInput = document.querySelector('#swayAmpInput');
const swayAmpSlider = document.querySelector('#swayAmpSlider');
const swaySpeedInput = document.querySelector('#swaySpeedInput');
const swaySpeedSlider = document.querySelector('#swaySpeedSlider');
const autoScanTimeInput = document.querySelector('#autoScanTimeInput');
const autoScanTimeSlider = document.querySelector('#autoScanTimeSlider');
const scanQualityInput = document.querySelector('#scanQualityInput');
const scanQualitySlider = document.querySelector('#scanQualitySlider');
const cameraFlipToggle = document.querySelector('#cameraFlipToggle');

// Elements Popup Hướng dẫn kết nối (Guide Modal)
const openGuideBtn = document.querySelector('#openGuideBtn');
const guideModal = document.querySelector('#guideModal');
const guideModalCloseBtn = document.querySelector('#guideModalCloseBtn');
const guideModalDoneBtn = document.querySelector('#guideModalDoneBtn');

// Elements Background Preview
const stagePreviewImg = document.querySelector('#stagePreviewImg');
const stagePreviewFallback = document.querySelector('#stagePreviewFallback');
const currentBgLabel = document.querySelector('#currentBgLabel');
const resetBackgroundBtn = document.querySelector('#resetBackgroundBtn');

// Elements Popup Background Preview Modal
const bgPreviewModal = document.querySelector('#bgPreviewModal');
const bgPreviewModalCloseBtn = document.querySelector('#bgPreviewModalCloseBtn');
const bgModalCancelBtn = document.querySelector('#bgModalCancelBtn');
const bgModalApplyBtn = document.querySelector('#bgModalApplyBtn');
const bgModalPreviewImg = document.querySelector('#bgModalPreviewImg');
const bgModalFileName = document.querySelector('#bgModalFileName');
const bgModalFileSize = document.querySelector('#bgModalFileSize');

// Elements Confirm Modal
const confirmModal = document.querySelector('#confirmModal');
const modalTitle = document.querySelector('#modalTitle');
const modalMessage = document.querySelector('#modalMessage');
const modalCancelBtn = document.querySelector('#modalCancelBtn');
const modalConfirmBtn = document.querySelector('#modalConfirmBtn');

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
let pendingBackgroundFile = null;
let pendingBackgroundUrl = null;

let currentSettings = {
  conveyor_speed: 1.0,
  sway_amplitude: 1.0,
  sway_speed: 1.0,
  auto_scan_seconds: 2.0,
  camera_flip_horizontal: false,
  scan_quality_threshold: 65,
};

function message(text, type = '') {
  if (text === lastMessage) return;
  lastMessage = text;
  msg.textContent = text;
  msg.className = `message ${type}`;
}

function setPreviewState(state, title, detail) {
  cameraWrap.classList.toggle('is-loading', state === 'loading');
  cameraWrap.classList.toggle('is-unavailable', state === 'unavailable');
  if (title) {
    cameraEmpty.innerHTML = `<div class="empty-spinner"></div><strong>${title}</strong><span>${detail || ''}</span>`;
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

// -------------------------------------------------------------
// SETTINGS POPUP MODAL & STEPPERS
// -------------------------------------------------------------
function syncInputAndSlider(inputEl, sliderEl, decimals = 1) {
  if (!inputEl || !sliderEl) return;
  sliderEl.oninput = () => {
    inputEl.value = parseFloat(sliderEl.value).toFixed(decimals);
  };
  inputEl.oninput = () => {
    let val = parseFloat(inputEl.value);
    const min = parseFloat(sliderEl.min);
    const max = parseFloat(sliderEl.max);
    if (Number.isFinite(val)) {
      val = Math.max(min, Math.min(max, val));
      sliderEl.value = val;
    }
  };
}

syncInputAndSlider(conveyorSpeedInput, conveyorSpeedSlider, 1);
syncInputAndSlider(swayAmpInput, swayAmpSlider, 1);
syncInputAndSlider(swaySpeedInput, swaySpeedSlider, 1);
syncInputAndSlider(autoScanTimeInput, autoScanTimeSlider, 1);
syncInputAndSlider(scanQualityInput, scanQualitySlider, 0);

document.querySelectorAll('.step-btn').forEach((btn) => {
  btn.onclick = () => {
    const targetId = btn.getAttribute('data-target');
    const step = parseFloat(btn.getAttribute('data-step') || '0.1');
    const targetInput = document.getElementById(targetId);
    if (!targetInput) return;

    const min = parseFloat(targetInput.min || '0');
    const max = parseFloat(targetInput.max || '10');
    let currentVal = parseFloat(targetInput.value) || 0;
    currentVal = Math.round((currentVal + step) * 10) / 10;
    currentVal = Math.max(min, Math.min(max, currentVal));

    targetInput.value = (step % 1 === 0 && Number.isInteger(currentVal)) ? currentVal.toString() : currentVal.toFixed(1);
    targetInput.dispatchEvent(new Event('input'));
  };
});

function applySettingsToForm(settings) {
  currentSettings = { ...currentSettings, ...settings };

  if (conveyorSpeedInput && conveyorSpeedSlider) {
    const val = Number(currentSettings.conveyor_speed).toFixed(1);
    conveyorSpeedInput.value = val;
    conveyorSpeedSlider.value = val;
  }
  if (swayAmpInput && swayAmpSlider) {
    const val = Number(currentSettings.sway_amplitude).toFixed(1);
    swayAmpInput.value = val;
    swayAmpSlider.value = val;
  }
  if (swaySpeedInput && swaySpeedSlider) {
    const val = Number(currentSettings.sway_speed).toFixed(1);
    swaySpeedInput.value = val;
    swaySpeedSlider.value = val;
  }
  if (autoScanTimeInput && autoScanTimeSlider) {
    const val = Number(currentSettings.auto_scan_seconds).toFixed(1);
    autoScanTimeInput.value = val;
    autoScanTimeSlider.value = val;
  }
  if (scanQualityInput && scanQualitySlider) {
    const val = Math.round(Number(currentSettings.scan_quality_threshold ?? 65));
    scanQualityInput.value = val;
    scanQualitySlider.value = val;
  }
  if (cameraFlipToggle) {
    cameraFlipToggle.checked = Boolean(currentSettings.camera_flip_horizontal);
  }
  if (autoScanLabel) {
    autoScanLabel.textContent = `Tự động Scan (${Number(currentSettings.auto_scan_seconds).toFixed(1)}s)`;
  }
}

async function fetchSettings() {
  try {
    const res = await fetch('/api/settings', { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      applySettingsToForm(data);
    }
  } catch (err) {
    console.warn('Failed to fetch settings', err);
  }
}

function openSettings() {
  applySettingsToForm(currentSettings);
  settingsModal.classList.remove('hidden');
}

function closeSettings() {
  settingsModal.classList.add('hidden');
}

if (openSettingsBtn) openSettingsBtn.onclick = openSettings;
if (settingsModalCloseBtn) settingsModalCloseBtn.onclick = closeSettings;
if (cancelSettingsBtn) cancelSettingsBtn.onclick = closeSettings;

if (saveSettingsBtn) {
  saveSettingsBtn.onclick = async () => {
    const payload = {
      conveyor_speed: parseFloat(conveyorSpeedInput.value),
      sway_amplitude: parseFloat(swayAmpInput.value),
      sway_speed: parseFloat(swaySpeedInput.value),
      auto_scan_seconds: parseFloat(autoScanTimeInput.value),
      scan_quality_threshold: parseInt(scanQualityInput.value, 10),
      camera_flip_horizontal: Boolean(cameraFlipToggle?.checked),
    };

    saveSettingsBtn.disabled = true;
    saveSettingsBtn.textContent = 'Đang lưu...';

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Lưu cài đặt thất bại');

      applySettingsToForm(data.settings || payload);
      closeSettings();
      showToast('Đã lưu và áp dụng cài đặt mới!', 'success');
      message('Đã cập nhật thông số hiệu ứng & camera.', 'success');
    } catch (e) {
      showToast(e.message, 'error');
    } finally {
      saveSettingsBtn.disabled = false;
      saveSettingsBtn.textContent = '💾 Lưu & Áp dụng';
    }
  };
}

if (resetSettingsBtn) {
  resetSettingsBtn.onclick = () => {
    showConfirm(
      'Khôi phục cài đặt mặc định?',
      'Bạn có chắc muốn đưa toàn bộ thông số tốc độ, độ rung lắc và thời gian scan về chuẩn ban đầu?',
      async () => {
        try {
          const res = await fetch('/api/settings/reset', { method: 'POST' });
          if (res.ok) {
            const data = await res.json();
            applySettingsToForm(data.settings || data);
            closeSettings();
            showToast('Đã khôi phục cài đặt mặc định!', 'success');
            message('Đã khôi phục cài đặt mặc định.', 'success');
          }
        } catch (e) {
          showToast('Lỗi khôi phục cài đặt', 'error');
        }
      }
    );
  };
}

// -------------------------------------------------------------
// GUIDE MODAL
// -------------------------------------------------------------
function openGuide() {
  guideModal.classList.remove('hidden');
}

function closeGuide() {
  guideModal.classList.add('hidden');
}

if (openGuideBtn) openGuideBtn.onclick = openGuide;
if (guideModalCloseBtn) guideModalCloseBtn.onclick = closeGuide;
if (guideModalDoneBtn) guideModalDoneBtn.onclick = closeGuide;

// -------------------------------------------------------------
// STAGE BACKGROUND PREVIEW
// -------------------------------------------------------------
function setStageBackground(url) {
  if (url) {
    stagePreviewImg.src = url;
    stagePreviewImg.style.display = 'block';
    stagePreviewFallback.style.display = 'none';
    currentBgLabel.textContent = 'Nền hiện tại: Ảnh tùy chỉnh (Đang áp dụng)';
  } else {
    stagePreviewImg.src = '';
    stagePreviewImg.style.display = 'none';
    stagePreviewFallback.style.display = 'flex';
    currentBgLabel.textContent = 'Nền hiện tại: Mặc định (Bầu trời đêm & Sao)';
  }
}

async function fetchCurrentBackground() {
  try {
    const res = await fetch('/api/display-state', { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      setStageBackground(data.backgroundUrl);
      if (data.settings) {
        applySettingsToForm(data.settings);
      }
      latestTotalCount = data.totalCount ?? 0;
      updateTotalMeta();
    }
  } catch (e) {
    console.warn('Failed to load display state', e);
  }
}

backgroundInput.onchange = () => {
  const file = backgroundInput.files && backgroundInput.files[0];
  if (!file) return;

  pendingBackgroundFile = file;
  if (pendingBackgroundUrl) {
    URL.revokeObjectURL(pendingBackgroundUrl);
  }
  pendingBackgroundUrl = URL.createObjectURL(file);

  if (bgModalPreviewImg) {
    bgModalPreviewImg.src = pendingBackgroundUrl;
  }
  if (bgModalFileName) {
    bgModalFileName.textContent = file.name;
  }
  if (bgModalFileSize) {
    const sizeMb = (file.size / (1024 * 1024)).toFixed(2);
    bgModalFileSize.textContent = `${sizeMb} MB`;
  }

  if (bgModalApplyBtn) {
    bgModalApplyBtn.disabled = false;
    bgModalApplyBtn.textContent = '✅ Áp Dụng Lên Màn Chiếu';
  }
  if (bgPreviewModal) {
    bgPreviewModal.classList.remove('hidden');
  }
};

function closeBgPreviewModal() {
  if (bgPreviewModal) {
    bgPreviewModal.classList.add('hidden');
  }
  pendingBackgroundFile = null;
  if (pendingBackgroundUrl) {
    URL.revokeObjectURL(pendingBackgroundUrl);
    pendingBackgroundUrl = null;
  }
  backgroundInput.value = '';
}

if (bgPreviewModalCloseBtn) bgPreviewModalCloseBtn.onclick = closeBgPreviewModal;
if (bgModalCancelBtn) bgModalCancelBtn.onclick = closeBgPreviewModal;

if (bgModalApplyBtn) {
  bgModalApplyBtn.onclick = async () => {
    if (!pendingBackgroundFile) return;

    const file = pendingBackgroundFile;
    bgModalApplyBtn.disabled = true;
    bgModalApplyBtn.textContent = 'Đang tải lên...';
    backgroundMessage.textContent = 'Đang upload ảnh nền...';
    backgroundMessage.className = 'muted small';

    try {
      const response = await fetch('/api/background', {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
      });
      const data = await response.json();
      if (!response.ok) throw Error(data.detail || 'Upload failed');

      setStageBackground(data.url);
      backgroundMessage.textContent = 'Đã đổi background. Display đã cập nhật!';
      backgroundMessage.className = 'muted small success-text';
      showToast('Đã đổi Background màn hình chiếu thành công!', 'success');
      closeBgPreviewModal();
    } catch (error) {
      backgroundMessage.textContent = error.message;
      backgroundMessage.className = 'muted small error-text';
      showToast(error.message, 'error');
      bgModalApplyBtn.disabled = false;
      bgModalApplyBtn.textContent = '✅ Thử lại';
      fetchCurrentBackground();
    }
  };
}

if (resetBackgroundBtn) {
  resetBackgroundBtn.onclick = () => {
    showConfirm(
      'Khôi phục nền mặc định',
      'Bạn có muốn xóa ảnh nền tùy chỉnh và quay về nền bầu trời sao mặc định không?',
      async () => {
        try {
          const res = await fetch('/api/background', { method: 'DELETE' });
          if (res.ok) {
            setStageBackground(null);
            backgroundMessage.textContent = 'Đã về nền mặc định.';
            backgroundMessage.className = 'muted small success-text';
            showToast('Đã quay về nền mặc định.', 'success');
          }
        } catch (e) {
          backgroundMessage.textContent = 'Lỗi xóa nền.';
          backgroundMessage.className = 'muted small error-text';
        }
      }
    );
  };
}

// -------------------------------------------------------------
// RECENT LANTERNS & MANAGEMENT
// -------------------------------------------------------------
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
      if (payload.type === 'settings_updated' && payload.settings) {
        applySettingsToForm(payload.settings);
      }
      if (payload.type === 'background_changed') {
        setStageBackground(payload.url);
      }
      if (payload.type === 'sequential_delete_completed') {
        isSequentialDeleting = false;
        updateDeleteButtonsUI();
        if (Number.isFinite(Number(payload.totalCount))) {
          latestTotalCount = payload.totalCount;
          updateTotalMeta();
        }
        showToast('Đã hoàn tất xóa lần lượt lồng đèn!', 'success');
        message('Đã hoàn tất xóa lần lượt lồng đèn.', 'success');
        fetchRecentLanterns();
      }
      if (payload.type === 'all_lanterns_fading_out' || payload.type === 'lanterns_cleared') {
        isSequentialDeleting = false;
        updateDeleteButtonsUI();
        latestTotalCount = 0;
        updateTotalMeta();
        fetchRecentLanterns();
        showToast('Đã xóa toàn bộ lồng đèn!', 'success');
      }
      if (payload.type === 'batch_lanterns_fading_out') {
        if (Number.isFinite(Number(payload.totalCount))) {
          latestTotalCount = payload.totalCount;
          updateTotalMeta();
        }
        fetchRecentLanterns();
      }
      if (payload.type === 'lantern_fading_out' || payload.type === 'pop_oldest_lantern') {
        if (Number.isFinite(Number(payload.totalCount))) {
          latestTotalCount = payload.totalCount;
          updateTotalMeta();
        }
        fetchRecentLanterns();
      }
      if (payload.type === 'lantern_created') {
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

function getDeleteQuantity() {
  if (!deleteQtyInput) return null;
  const val = parseInt(deleteQtyInput.value, 10);
  return (Number.isInteger(val) && val > 0) ? val : null;
}

function updateDeleteButtonsUI() {
  const qty = getDeleteQuantity();
  const isAll = qty === null;

  if (qtyAllBtn) {
    qtyAllBtn.classList.toggle('active', isAll);
  }

  if (toggleSequentialBtn) {
    if (isSequentialDeleting) {
      toggleSequentialBtn.textContent = '⏹ Dừng xóa lần lượt';
      toggleSequentialBtn.className = 'button danger-outline full-w-btn';
    } else {
      toggleSequentialBtn.textContent = isAll ? '▶ Xóa lần lượt (1s/đèn)' : `▶ Xóa lần lượt (${qty} đèn)`;
      toggleSequentialBtn.className = 'button secondary full-w-btn';
    }
  }

  if (deleteAllBtn) {
    deleteAllBtn.textContent = isAll ? 'Xóa tất cả lồng đèn' : `Xóa ${qty} lồng đèn (cũ nhất)`;
  }
}

if (qtyAllBtn) {
  qtyAllBtn.onclick = () => {
    if (deleteQtyInput) deleteQtyInput.value = '';
    updateDeleteButtonsUI();
  };
}

if (qtyMinusBtn) {
  qtyMinusBtn.onclick = () => {
    let current = getDeleteQuantity() || 1;
    current = Math.max(1, current - 1);
    if (deleteQtyInput) deleteQtyInput.value = current;
    updateDeleteButtonsUI();
  };
}

if (qtyPlusBtn) {
  qtyPlusBtn.onclick = () => {
    let current = getDeleteQuantity() || 0;
    current = Math.min(999, current + 1);
    if (deleteQtyInput) deleteQtyInput.value = current;
    updateDeleteButtonsUI();
  };
}

if (deleteQtyInput) {
  deleteQtyInput.oninput = () => {
    updateDeleteButtonsUI();
  };
}

async function startSequentialDelete() {
  const qty = getDeleteQuantity();
  try {
    message(qty ? `Đang bắt đầu xóa lần lượt ${qty} lồng đèn (1s/đèn)...` : 'Đang bắt đầu xóa lần lượt từng lồng đèn (1s/đèn)...');
    const res = await fetch('/api/lanterns/sequential-delete/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count: qty || null }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Không thể bắt đầu xóa');
    isSequentialDeleting = true;
    updateDeleteButtonsUI();
    showToast(qty ? `Đang xóa lần lượt ${qty} đèn (1s/đèn)...` : 'Đang xóa lần lượt từng đèn (1s/đèn)...', 'info');
    message(qty ? `Đang xóa lần lượt ${qty} đèn (1s/đèn)...` : 'Đang xóa lần lượt từng đèn (1s/đèn)...', 'success');
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
    updateDeleteButtonsUI();
    showToast('Đã dừng xóa lần lượt.', 'info');
    message('Đã dừng xóa lần lượt.', 'success');
    await fetchRecentLanterns();
  } catch (e) {
    message(e.message, 'error');
  }
}

toggleSequentialBtn.onclick = () => {
  if (isSequentialDeleting) {
    stopSequentialDelete();
  } else {
    const qty = getDeleteQuantity();
    const title = qty ? `Bắt đầu xóa lần lượt ${qty} lồng đèn?` : 'Bắt đầu xóa lần lượt?';
    const text = qty
      ? `Hệ thống sẽ làm mờ và xóa lần lượt ${qty} lồng đèn cũ nhất (cách nhau 1 giây). Bạn có chắc muốn bắt đầu không?`
      : 'Hệ thống sẽ làm mờ và xóa lần lượt từng lồng đèn (cách nhau 1 giây) từ cũ nhất đến mới nhất. Bạn có chắc muốn bắt đầu không?';
    showConfirm(title, text, startSequentialDelete);
  }
};

async function deleteLanternsBatchOrAll() {
  const qty = getDeleteQuantity();
  try {
    message(qty ? `Đang xóa ${qty} lồng đèn cũ nhất...` : 'Đang làm mờ và xóa toàn bộ lồng đèn...');
    const url = qty ? `/api/lanterns?count=${qty}` : '/api/lanterns';
    const res = await fetch(url, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Không thể xóa');
    if (Number.isFinite(Number(data.totalCount))) {
      latestTotalCount = data.totalCount;
      updateTotalMeta();
    }
    showToast(qty ? `Đã xóa ${data.deletedCount || qty} lồng đèn!` : 'Đã xóa toàn bộ lồng đèn!', 'success');
    message(qty ? `Đã xóa ${data.deletedCount || qty} lồng đèn.` : 'Đã xóa toàn bộ lồng đèn.', 'success');
    await fetchRecentLanterns();
  } catch (e) {
    message(e.message, 'error');
  }
}

deleteAllBtn.onclick = () => {
  const qty = getDeleteQuantity();
  const title = qty ? `Xóa ${qty} lồng đèn cũ nhất?` : 'Xóa toàn bộ lồng đèn?';
  const text = qty
    ? `Hành động này sẽ làm mờ và xóa ngay ${qty} lồng đèn cũ nhất khỏi màn hình chiếu. Bạn có chắc chắn không?`
    : 'Hành động này sẽ làm mờ và xóa sạch TẤT CẢ lồng đèn trên bầu trời và trong bộ nhớ. Bạn có chắc chắn không?';
  showConfirm(title, text, deleteLanternsBatchOrAll);
};

function updateTotalMeta() {
  if (lanternManageMeta) {
    lanternManageMeta.textContent = `Đang chiếu: ${latestTotalCount} lồng đèn`;
  }
}

async function doScan(isAuto = false) {
  if (isScanning || Date.now() < cooldownUntil) return;

  isScanning = true;
  scan.disabled = true;
  setCountdownProgress(0);
  setBadge('Đang xử lý...', 'busy');
  message(isAuto ? 'Đang tự động chụp và nhận diện ArUco...' : 'Đang chụp và tách nền lồng đèn...');

  try {
    const response = await fetch('/api/scan', { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || 'Scan failed');

    result.src = `${data.lanternUrl}?t=${Date.now()}`;
    const label = data.variantLabel ? ` (${data.variantLabel})` : '';
    const autoNote = isAuto ? ' [Tự động]' : '';
    message(`Scan thành công${label}${autoNote}! Đã phát sang Display.`, 'success');
    showToast(`Đã quét thành công lồng đèn${label}!`, 'success');
    setBadge('Scan OK', 'ready');
    latestTotalCount = data.totalCount ?? latestTotalCount + 1;
    updateTotalMeta();
    await fetchRecentLanterns();

    cooldownUntil = Date.now() + POST_SCAN_COOLDOWN_MS;
    stableStartAt = null;
    lastSeenVariant = null;
  } catch (error) {
    message(error.message, 'error');
    showToast(error.message, 'error');
    setBadge('Error', 'error');
  } finally {
    isScanning = false;
  }
}

async function poll() {
  if (isScanning) return;

  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) throw Error('Status unavailable');

    const data = await response.json();
    const requiredIds = Array.isArray(data.requiredMarkerIds) ? data.requiredMarkerIds : [];
    const found = new Set(data.markerIds || []);

    updateMarkerSlots(requiredIds, found);

    if (!data.cameraOpen) {
      stableStartAt = null;
      lastSeenVariant = null;
      setCountdownProgress(0);
      scan.disabled = true;
      scan.innerHTML = '<span class="btn-icon">⚡</span> Scan Lồng Đèn';
      meta.textContent = `Camera #${data.cameraIndex} (Offline)`;
      if (templateMeta) templateMeta.textContent = 'Đang tìm thiết bị...';
      setBadge('Offline', 'error');
      setPreviewState('unavailable', 'Camera không khả dụng', data.error || 'Kiểm tra cáp kết nối hoặc quyền camera.');
      message(data.error || 'Camera offline. Kiểm tra kết nối thiết bị.', 'error');
      return;
    }

    setPreviewState('ready');
    const [w, h] = data.resolution || [0, 0];
    const fps = Number(data.fps || 0).toFixed(1);
    meta.textContent = `Camera #${data.cameraIndex} · ${w}x${h} · ${fps} fps`;
    if (templateMeta) {
      templateMeta.textContent = data.variantLabel
        ? `Đã nhận diện: ${data.variantLabel} (markers: ${requiredIds.join(', ')})`
        : 'Đưa template lồng đèn vào khung hình...';
    }

    const now = Date.now();
    const autoScanEnabled = autoScanToggle.checked;
    const autoScanDurationMs = Math.max(500, (currentSettings.auto_scan_seconds || 2.0) * 1000);

    if (now < cooldownUntil) {
      const waitRemainingSec = Math.ceil((cooldownUntil - now) / 1000);
      scan.disabled = true;
      scan.innerHTML = `<span class="btn-icon">⏳</span> Chờ đổi giấy (${waitRemainingSec}s)`;
      setBadge(`Chờ ${waitRemainingSec}s`, 'busy');
      setCountdownProgress(0);
      message(`Vừa scan xong. Vui lòng đổi giấy mới (${waitRemainingSec}s)...`);
      return;
    }

    if (data.readyToScan) {
      lastSeenCompleteAt = now;
      const currentVariant = data.variant || 'template';

      if (lastSeenVariant !== currentVariant || !stableStartAt) {
        stableStartAt = now;
        lastSeenVariant = currentVariant;
      }

      const elapsed = now - stableStartAt;
      const progressRatio = Math.min(1, elapsed / autoScanDurationMs);
      const remainingSec = Math.max(0, ((autoScanDurationMs - elapsed) / 1000).toFixed(1));

      scan.disabled = false;

      if (autoScanEnabled) {
        setCountdownProgress(progressRatio * 100);
        setBadge(`Tự scan ${remainingSec}s · ${data.variantLabel || 'Ready'}`, 'ready');
        scan.innerHTML = `<span class="btn-icon">⚡</span> Scan Ngay (${remainingSec}s)`;
        message(`Giữ yên giấy! Tự động chụp sau ${remainingSec}s... (hoặc bấm Scan ngay)`, 'success');

        if (elapsed >= autoScanDurationMs) {
          doScan(true);
          return;
        }
      } else {
        setCountdownProgress(0);
        setBadge(`Sẵn sàng · ${data.variantLabel || 'Template'}`, 'ready');
        scan.innerHTML = '<span class="btn-icon">⚡</span> Scan Lồng Đèn';
        message(`Đủ marker cho mẫu ${data.variantLabel || ''}. Có thể bấm Scan.`);
      }
      return;
    }

    const timeSinceComplete = lastSeenCompleteAt ? now - lastSeenCompleteAt : Infinity;
    if (timeSinceComplete < FLICKER_GRACE_PERIOD_MS && stableStartAt && autoScanEnabled) {
      const elapsed = lastSeenCompleteAt - stableStartAt;
      const progressRatio = Math.min(1, elapsed / autoScanDurationMs);
      const remainingSec = Math.max(0.1, ((autoScanDurationMs - elapsed) / 1000).toFixed(1));
      setCountdownProgress(progressRatio * 100);
      setBadge(`Đang giữ nét · ${remainingSec}s`, 'ready');
      message('Đang giữ vị trí... Hãy để phẳng giấy.', '');
      scan.disabled = false;
      return;
    }

    stableStartAt = null;
    lastSeenVariant = null;
    setCountdownProgress(0);
    scan.disabled = true;
    scan.innerHTML = '<span class="btn-icon">⚡</span> Scan Lồng Đèn';

    const foundExpected = requiredIds.filter((id) => found.has(id)).length;
    setBadge(requiredIds.length ? `Markers ${foundExpected}/4` : 'Tìm template');
    message('Đặt toàn bộ template trong khung hình và không che bốn marker góc.');
  } catch (error) {
    stableStartAt = null;
    setCountdownProgress(0);
    scan.disabled = true;
    scan.innerHTML = '<span class="btn-icon">⚡</span> Scan Lồng Đèn';
    meta.textContent = 'Mất kết nối server';
    if (templateMeta) templateMeta.textContent = 'Đang chờ server...';
    setBadge('Disconnected', 'error');
    setPreviewState('unavailable', 'Mất kết nối server', 'Vui lòng kiểm tra lại tiến trình ứng dụng.');
    message('Không kết nối được server.', 'error');
  }
}

scan.onclick = () => doScan(false);

demo.onclick = async () => {
  try {
    const response = await fetch('/api/demo', { method: 'POST' });
    if (!response.ok) throw Error('Demo failed');
    message('Đã gửi demo lantern sang Display.', 'success');
    showToast('Đã gửi lồng đèn Demo sang màn hình chiếu!', 'info');
  } catch (error) {
    message(error.message, 'error');
  }
};

connectControlWs();
fetchCameras();
fetchRecentLanterns();
fetchSettings();
fetchCurrentBackground();
poll();
setInterval(poll, 250);
