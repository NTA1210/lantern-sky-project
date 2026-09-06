const canvas = document.querySelector('#sky');
const ctx = canvas.getContext('2d', { alpha: false });
const statusEl = document.querySelector('#connectionStatus');
const fsBtn = document.querySelector('#fullscreenButton');
const hideBtn = document.querySelector('#hideHudButton');
const hud = document.querySelector('#displayHud');

let W = innerWidth;
let H = innerHeight;
let D = 1;
let last = performance.now();
let backgroundImg = null;

const lanterns = [];
const lanternIds = new Set();
const stars = [];
const MAX = 60;

function resize() {
  const oldWidth = W || innerWidth;
  const oldHeight = H || innerHeight;
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
  if (oldWidth > 0 && oldHeight > 0) {
    lanterns.forEach((lantern) => { lantern.y *= H / oldHeight; });
  }
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
    stars.push({ x: random() * W, y: random() * H * 0.78, r: 0.45 + random() * 1.25, a: 0.18 + random() * 0.68, p: random() * Math.PI * 2 });
  }
}

async function load(url) {
  const img = new Image();
  img.decoding = 'async';
  img.src = url;
  if (img.decode) {
    try { await img.decode(); return img; } catch {}
  }
  return new Promise((resolve, reject) => { img.onload = () => resolve(img); img.onerror = reject; });
}

async function setBackground(url) {
  if (!url) { backgroundImg = null; return; }
  try { backgroundImg = await load(url); } catch (error) { console.error(error); }
}

function drawCoverImage(img) {
  const scale = Math.max(W / img.naturalWidth, H / img.naturalHeight);
  const width = img.naturalWidth * scale;
  const height = img.naturalHeight * scale;
  ctx.drawImage(img, (W - width) / 2, (H - height) / 2, width, height);
}

function drawDefaultSky(t) {
  const gradient = ctx.createLinearGradient(0, 0, 0, H);
  gradient.addColorStop(0, '#050817');
  gradient.addColorStop(0.55, '#0a1730');
  gradient.addColorStop(1, '#162342');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, W, H);
  const glow = ctx.createRadialGradient(W * 0.5, H * 1.02, 0, W * 0.5, H * 1.02, W * 0.75);
  glow.addColorStop(0, 'rgba(84,102,155,.20)');
  glow.addColorStop(1, 'rgba(84,102,155,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);
  for (const star of stars) {
    ctx.globalAlpha = star.a * (0.72 + 0.28 * Math.sin(t * 0.85 + star.p));
    ctx.fillStyle = '#dfe8ff';
    ctx.beginPath(); ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function bg(t) { if (backgroundImg) drawCoverImage(backgroundImg); else drawDefaultSky(t); }

async function add(url, restored = false, id = null) {
  if (id && lanternIds.has(id)) return;
  if (id) lanternIds.add(id);
  try {
    const img = await load(`${url}${url.includes('?') ? '&' : '?'}v=${Date.now()}`);
    const random = Math.random;
    const width = Math.min(210, Math.max(105, W * (0.075 + random() * 0.035)));
    const height = width * img.naturalHeight / Math.max(1, img.naturalWidth);
    lanterns.push({ id, img, baseX: W * (0.10 + random() * 0.80), y: restored ? H * (0.22 + random() * 0.72) : H + height * 0.75, width, height, speed: 30 + random() * 34, drift: 16 + random() * 34, freq: 0.38 + random() * 0.50, phase: random() * Math.PI * 2, rotAmp: 0.025 + random() * 0.045, rotFreq: 0.34 + random() * 0.45, age: restored ? random() * 7 : 0, opacity: restored ? 1 : 0 });
    while (lanterns.length > MAX) lanterns.shift();
  } catch (error) {
    if (id) lanternIds.delete(id);
    console.error(error);
  }
}

function update(dt) {
  for (const lantern of lanterns) {
    lantern.age += dt; lantern.y -= lantern.speed * dt; lantern.opacity = Math.min(1, lantern.age / 0.75);
    if (lantern.y < -lantern.height * 0.1) lantern.opacity = Math.max(0, Math.min(lantern.opacity, (lantern.y + lantern.height) / (lantern.height * 0.9)));
  }
  for (let i = lanterns.length - 1; i >= 0; i -= 1) {
    if (lanterns[i].y < -lanterns[i].height * 1.2 || lanterns[i].opacity <= 0) lanterns.splice(i, 1);
  }
}

function draw(lantern) {
  const x = lantern.baseX + Math.sin(lantern.age * lantern.freq * Math.PI * 2 + lantern.phase) * lantern.drift;
  const rotation = Math.sin(lantern.age * lantern.rotFreq * Math.PI * 2 + lantern.phase) * lantern.rotAmp;
  const quality = lanterns.length <= 28 ? 1 : 0.45;
  ctx.save(); ctx.globalAlpha = lantern.opacity; ctx.translate(x, lantern.y); ctx.rotate(rotation);
  ctx.shadowColor = `rgba(255,167,72,${0.58 * quality})`; ctx.shadowBlur = 28 * quality;
  ctx.drawImage(lantern.img, -lantern.width / 2, -lantern.height / 2, lantern.width, lantern.height); ctx.restore();
}

function frame(ts) {
  const dt = Math.min(0.05, Math.max(0, (ts - last) / 1000)); last = ts;
  update(dt); bg(ts / 1000); [...lanterns].sort((a, b) => a.width - b.width).forEach(draw); requestAnimationFrame(frame);
}

async function syncState() {
  try {
    const response = await fetch('/api/display-state', { cache: 'no-store' });
    if (!response.ok) throw Error(`Display state ${response.status}`);
    const state = await response.json();
    if (state.backgroundUrl) await setBackground(state.backgroundUrl);
    for (const item of state.lanterns || []) await add(item.url, true, item.id);
  } catch (error) { console.error(error); }
}

function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws`);
  ws.onopen = async () => { statusEl.textContent = 'Live'; await syncState(); ws.send('display-ready'); };
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === 'lantern_created' && payload.url) add(payload.url, false, payload.id || null);
      if (payload.type === 'background_changed') setBackground(payload.url || null);
    } catch (error) { console.error(error); }
  };
  ws.onclose = () => { statusEl.textContent = 'Reconnecting...'; setTimeout(connect, 1000); };
  ws.onerror = () => ws.close();
}

fsBtn.onclick = async () => { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); else await document.exitFullscreen(); };
hideBtn.onclick = () => hud.classList.add('hidden');
addEventListener('keydown', (event) => { if (event.key.toLowerCase() === 'h') hud.classList.toggle('hidden'); if (event.key.toLowerCase() === 'f') fsBtn.click(); });
addEventListener('resize', resize);
resize(); syncState(); connect(); requestAnimationFrame(frame);
