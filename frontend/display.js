const canvas = document.querySelector('#sky');
const ctx = canvas.getContext('2d', { alpha: false });
const statusEl = document.querySelector('#connectionStatus');
const totalEl = document.querySelector('#lanternTotal');
const fsBtn = document.querySelector('#fullscreenButton');
const hideBtn = document.querySelector('#hideHudButton');
const hud = document.querySelector('#displayHud');

const LANE_CONFIG = [
  { key: 'classic', direction: -1, speed: 24 },
  { key: 'balloon', direction: 1, speed: 19 },
  { key: 'round', direction: -1, speed: 28 },
  { key: 'rectangle', direction: 1, speed: 21 },
];
// Visual density only: this is how many lantern positions should fit in the
// viewport at once. It is never a retention limit for lane.records or storage.
const VISIBLE_SLOT_COUNT = 10;
// Bitmap decoding is bounded for memory, but metadata/history stays complete
// and an evicted bitmap is simply loaded again when that lantern loops back.
const MAX_IMAGE_CACHE = 72;

let W = innerWidth;
let H = innerHeight;
let D = 1;
let last = performance.now();
let backgroundImg = null;
let totalCount = 0;

const stars = [];
const lanternIds = new Set();
const imageCache = new Map();
const lanes = Object.fromEntries(
  LANE_CONFIG.map((config) => [config.key, { ...config, records: [], distance: 0 }])
);

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function mod(value, divisor) {
  return ((value % divisor) + divisor) % divisor;
}

function hashText(text = '') {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

function laneKeyForRecord(id) {
  const laneIndex = Math.min(
    LANE_CONFIG.length - 1,
    Math.floor(hashText(id) * LANE_CONFIG.length),
  );
  return LANE_CONFIG[laneIndex].key;
}

function setTotal(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return;
  totalCount = Math.max(0, Math.floor(numeric));
  totalEl.textContent = totalCount.toLocaleString('vi-VN');
}

function resize() {
  W = innerWidth;
  H = innerHeight;
  D = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.floor(W * D);
  canvas.height = Math.floor(H * D);
  canvas.style.width = `${W}px`;
  canvas.style.height = `${H}px`;
  ctx.setTransform(D, 0, 0, D, 0, 0);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  buildStars();
}

function rnd(seed) {
  return () => {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

function buildStars() {
  stars.length = 0;
  const random = rnd(42371);
  const count = Math.min(190, Math.max(70, Math.round(W * H / 12000)));
  for (let i = 0; i < count; i += 1) {
    stars.push({
      x: random() * W,
      y: random() * H * 0.88,
      r: 0.45 + random() * 1.25,
      a: 0.18 + random() * 0.68,
      p: random() * Math.PI * 2,
    });
  }
}

async function loadBackground(url) {
  if (!url) {
    backgroundImg = null;
    return;
  }
  const img = new Image();
  img.decoding = 'async';
  try {
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
      img.src = url;
    });
    backgroundImg = img;
  } catch (error) {
    console.error(error);
  }
}

function drawCoverImage(img) {
  const scale = Math.max(W / img.naturalWidth, H / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  ctx.drawImage(img, (W - width) / 2, (H - height) / 2, width, height);
  ctx.fillStyle = 'rgba(2,7,20,.20)';
  ctx.fillRect(0, 0, W, H);
}

function drawDefaultSky(t) {
  const gradient = ctx.createLinearGradient(0, 0, 0, H);
  gradient.addColorStop(0, '#020714');
  gradient.addColorStop(0.54, '#07142b');
  gradient.addColorStop(1, '#121d32');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, W, H);

  const moonX = W * 0.82;
  const moonY = H * 0.09;
  const moonRadius = clamp(W * 0.018, 18, 34);
  const moonGlow = ctx.createRadialGradient(moonX, moonY, 0, moonX, moonY, moonRadius * 2.7);
  moonGlow.addColorStop(0, 'rgba(255,226,166,.40)');
  moonGlow.addColorStop(1, 'rgba(255,226,166,0)');
  ctx.fillStyle = moonGlow;
  ctx.beginPath(); ctx.arc(moonX, moonY, moonRadius * 2.7, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#ead09a';
  ctx.globalAlpha = 0.88;
  ctx.beginPath(); ctx.arc(moonX, moonY, moonRadius, 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = 1;

  for (const star of stars) {
    ctx.globalAlpha = star.a * (0.72 + 0.28 * Math.sin(t * 0.85 + star.p));
    ctx.fillStyle = '#dfe8ff';
    ctx.beginPath(); ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = 1;

  const horizon = ctx.createLinearGradient(0, H * 0.78, 0, H);
  horizon.addColorStop(0, 'rgba(7,12,20,0)');
  horizon.addColorStop(0.55, 'rgba(3,8,14,.65)');
  horizon.addColorStop(1, 'rgba(2,5,10,.96)');
  ctx.fillStyle = horizon;
  ctx.fillRect(0, H * 0.72, W, H * 0.28);

  ctx.globalAlpha = 0.7;
  for (let x = 0; x < W; x += 38) {
    const flicker = 0.55 + 0.45 * Math.sin(t * 1.4 + x * 0.07);
    ctx.fillStyle = `rgba(255,165,62,${0.18 * flicker})`;
    ctx.beginPath();
    ctx.arc(x + 12, H * 0.91 + Math.sin(x * 0.11) * 5, 4, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawBackground(t) {
  if (backgroundImg) drawCoverImage(backgroundImg);
  else drawDefaultSky(t);

  const topShade = ctx.createLinearGradient(0, 0, 0, H * 0.28);
  topShade.addColorStop(0, 'rgba(1,5,16,.56)');
  topShade.addColorStop(1, 'rgba(1,5,16,0)');
  ctx.fillStyle = topShade;
  ctx.fillRect(0, 0, W, H * 0.28);
}

function laneGeometry(index) {
  const top = H * 0.245;
  const bottom = H * 0.79;
  const gap = (bottom - top) / (LANE_CONFIG.length - 1);
  return { y: top + gap * index, gap };
}

function ropeY(index, x, t) {
  const { y } = laneGeometry(index);
  const sag = clamp(H * 0.038 + index * 3.5, 22, 52);
  const wave = Math.sin((x / Math.max(W, 1)) * Math.PI * 2 + index * 0.9 + t * 0.08) * 0.8;
  const normalized = (x / Math.max(W, 1)) * 2 - 1;
  return y + sag * (1 - normalized * normalized) + wave;
}

function drawRope(index, t) {
  ctx.save();
  ctx.lineWidth = clamp(W / 950, 1.4, 2.6);
  ctx.strokeStyle = 'rgba(151,91,34,.88)';
  ctx.shadowColor = 'rgba(255,150,52,.22)';
  ctx.shadowBlur = 5;
  ctx.beginPath();
  for (let x = -40; x <= W + 40; x += 30) {
    const y = ropeY(index, x, t);
    if (x === -40) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  const bulbGap = clamp(W / 32, 32, 62);
  for (let x = bulbGap * 0.5; x < W; x += bulbGap) {
    const y = ropeY(index, x, t) + 4;
    ctx.fillStyle = 'rgba(255,190,92,.95)';
    ctx.shadowColor = 'rgba(255,151,50,.95)';
    ctx.shadowBlur = 12;
    ctx.beginPath(); ctx.arc(x, y, 2.1, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
}

function touchImage(record) {
  let entry = imageCache.get(record.url);
  if (entry) {
    entry.lastUsed = performance.now();
    return entry;
  }

  const img = new Image();
  img.decoding = 'async';
  entry = { img: null, loading: true, lastUsed: performance.now() };
  imageCache.set(record.url, entry);

  img.onload = () => {
    entry.img = img;
    entry.loading = false;
    entry.lastUsed = performance.now();
    trimImageCache();
  };
  img.onerror = () => {
    imageCache.delete(record.url);
  };
  img.src = record.url;
  trimImageCache();
  return entry;
}

function trimImageCache() {
  if (imageCache.size <= MAX_IMAGE_CACHE) return;
  const candidates = [...imageCache.entries()]
    .filter(([, entry]) => !entry.loading)
    .sort((a, b) => a[1].lastUsed - b[1].lastUsed);
  while (imageCache.size > MAX_IMAGE_CACHE && candidates.length) {
    const [url] = candidates.shift();
    imageCache.delete(url);
  }
}

function drawLoadingLantern(x, y) {
  ctx.save();
  ctx.fillStyle = 'rgba(255,184,82,.42)';
  ctx.shadowColor = 'rgba(255,153,45,.7)';
  ctx.shadowBlur = 18;
  ctx.beginPath();
  ctx.ellipse(x, y + 34, 17, 25, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function drawLantern(record, x, index, t, pitch) {
  const entry = touchImage(record);
  const anchorY = ropeY(index, x, t);
  const phase = hashText(record.id || record.url) * Math.PI * 2;
  const bob = Math.sin(t * 1.15 + phase) * 2.8;
  const rotation = Math.sin(t * 0.8 + phase) * 0.025;

  if (!entry.img) {
    drawLoadingLantern(x, anchorY + 10 + bob);
    return;
  }

  const image = entry.img;
  const { gap } = laneGeometry(index);
  const maxHeight = clamp(gap * 0.62, 72, 132);
  const maxWidth = pitch * 0.72;
  const scale = Math.min(maxWidth / image.naturalWidth, maxHeight / image.naturalHeight);
  const width = Math.max(24, image.naturalWidth * scale);
  const height = Math.max(36, image.naturalHeight * scale);
  const top = anchorY + 14 + bob;

  ctx.save();
  ctx.strokeStyle = 'rgba(125,82,46,.88)';
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(x, anchorY + 1);
  ctx.lineTo(x, top + 4);
  ctx.stroke();

  const ageMs = performance.now() - (record.addedAt || 0);
  const newGlow = record.addedAt && ageMs < 5000 ? 1 - ageMs / 5000 : 0;
  ctx.translate(x, top + height / 2);
  ctx.rotate(rotation);
  ctx.shadowColor = `rgba(255,147,50,${0.52 + newGlow * 0.35})`;
  ctx.shadowBlur = 18 + newGlow * 24;
  ctx.drawImage(image, -width / 2, -height / 2, width, height);
  ctx.restore();
}

function drawLane(lane, index, dt, t) {
  drawRope(index, t);
  if (!lane.records.length) return;

  const pitch = clamp(W / VISIBLE_SLOT_COUNT, 112, 220);
  const count = lane.records.length;

  // Sparse lanes must use a closed-loop spacing. Rounding records into integer
  // slots leaves an oversized last-to-first seam (for example 9 records in
  // 10 slots), which makes the animation visibly jump at the wrap point.
  if (count < VISIBLE_SLOT_COUNT) {
    const cycleWidth = VISIBLE_SLOT_COUNT * pitch;
    const spacing = cycleWidth / count;
    lane.distance = mod(lane.distance + lane.speed * dt, cycleWidth);
    const signedDistance = lane.direction < 0 ? -lane.distance : lane.distance;

    for (let recordIndex = 0; recordIndex < count; recordIndex += 1) {
      const baseX = mod(recordIndex * spacing + signedDistance, cycleWidth);

      // Usually one copy is enough. Wrapped copies keep spacing identical on
      // very wide displays where the configured cycle is narrower than W.
      for (let x = baseX; x <= W + pitch; x += cycleWidth) {
        if (x >= -pitch) drawLantern(lane.records[recordIndex], x, index, t, spacing);
      }
      for (let x = baseX - cycleWidth; x >= -pitch; x -= cycleWidth) {
        if (x <= W + pitch) drawLantern(lane.records[recordIndex], x, index, t, spacing);
      }
    }
    return;
  }

  const cycleSlots = count;
  const cycleWidth = cycleSlots * pitch;
  lane.distance = mod(lane.distance + lane.speed * dt, cycleWidth);
  const cell = Math.floor(lane.distance / pitch);
  const fraction = lane.distance % pitch;
  const slots = Math.ceil(W / pitch) + 2;

  for (let slot = -1; slot <= slots; slot += 1) {
    let x;
    let cycleSlot;
    if (lane.direction < 0) {
      x = slot * pitch - fraction;
      cycleSlot = mod(cell + slot, cycleSlots);
    } else {
      x = slot * pitch + fraction;
      cycleSlot = mod(slot - cell, cycleSlots);
    }
    if (x < -pitch || x > W + pitch) continue;
    const record = lane.records[cycleSlot];
    if (record) drawLantern(record, x, index, t, pitch);
  }
}

function addRecord(item, restored = false) {
  if (!item || !item.url) return;
  const id = item.id || `${item.url}:${item.variant || 'classic'}`;
  if (lanternIds.has(id)) return;

  const variant = item.variant || 'classic';
  const laneKey = laneKeyForRecord(id);
  lanternIds.add(id);
  // Never trim this array to the visible slot count. Every event lantern must
  // remain in its assigned lane so off-screen records can cycle back later.
  // Lane assignment is intentionally independent from template type. Hashing
  // the stable record id gives a random-looking distribution that survives
  // reload/reconnect without needing another persisted field.
  lanes[laneKey].records.push({
    id,
    url: item.url,
    variant,
    laneKey,
    createdAt: item.createdAt || null,
    addedAt: restored ? 0 : performance.now(),
  });
}

function frame(ts) {
  const dt = Math.min(0.05, Math.max(0, (ts - last) / 1000));
  last = ts;
  const t = ts / 1000;
  drawBackground(t);
  LANE_CONFIG.forEach((config, index) => drawLane(lanes[config.key], index, dt, t));
  requestAnimationFrame(frame);
}

async function syncState() {
  try {
    const response = await fetch('/api/display-state', { cache: 'no-store' });
    if (!response.ok) throw Error(`Display state ${response.status}`);
    const state = await response.json();
    await loadBackground(state.backgroundUrl || null);
    for (const item of state.lanterns || []) addRecord(item, true);
    setTotal(state.totalCount ?? lanternIds.size);
  } catch (error) {
    console.error(error);
  }
}

function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
  ws.onopen = async () => {
    statusEl.textContent = 'Live';
    await syncState();
    ws.send('display-ready');
  };
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'lantern_created' && payload.url) {
        addRecord(payload, false);
        if (Number.isFinite(Number(payload.totalCount))) setTotal(payload.totalCount);
        else if (!payload.demo) setTotal(totalCount + 1);
      }
      if (payload.type === 'background_changed') loadBackground(payload.url || null);
    } catch (error) {
      console.error(error);
    }
  };
  ws.onclose = () => {
    statusEl.textContent = 'Reconnecting...';
    setTimeout(connect, 1000);
  };
  ws.onerror = () => ws.close();
}

fsBtn.onclick = async () => {
  if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
  else await document.exitFullscreen();
};
hideBtn.onclick = () => hud.classList.add('hidden');
addEventListener('keydown', (event) => {
  if (event.key.toLowerCase() === 'h') hud.classList.toggle('hidden');
  if (event.key.toLowerCase() === 'f') fsBtn.click();
});
addEventListener('resize', resize);

resize();
syncState();
connect();
requestAnimationFrame(frame);
