const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');
const RUNTIME = path.join(ROOT, 'runtime', 'e2e');
const LANTERNS = path.join(RUNTIME, 'lanterns');
const SAMPLE = path.join(ROOT, 'frontend', 'sample_lantern.png');
const VARIANTS = ['classic', 'balloon', 'round', 'rectangle'];

function seedLanterns() {
  fs.rmSync(RUNTIME, { recursive: true, force: true });
  fs.mkdirSync(LANTERNS, { recursive: true });
  VARIANTS.forEach((variant, index) => {
    fs.copyFileSync(SAMPLE, path.join(LANTERNS, `20260906_12000${index}_e2e0000__${variant}.png`));
  });
}

function seedLongHistory(classicCount = 16) {
  fs.rmSync(RUNTIME, { recursive: true, force: true });
  fs.mkdirSync(LANTERNS, { recursive: true });
  const baseTime = Date.UTC(2026, 8, 6, 12, 0, 0) / 1000;
  let sequence = 0;

  for (let index = 0; index < classicCount; index += 1) {
    const file = path.join(LANTERNS, `history_${String(index).padStart(4, '0')}__classic.png`);
    fs.copyFileSync(SAMPLE, file);
    const timestamp = baseTime + sequence++;
    fs.utimesSync(file, timestamp, timestamp);
  }

  for (const variant of VARIANTS.slice(1)) {
    const file = path.join(LANTERNS, `history_${String(sequence).padStart(4, '0')}__${variant}.png`);
    fs.copyFileSync(SAMPLE, file);
    const timestamp = baseTime + sequence++;
    fs.utimesSync(file, timestamp, timestamp);
  }
}

function hashText(text = '') {
  let hash = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
}

function laneIndexForId(id) {
  return Math.min(VARIANTS.length - 1, Math.floor(hashText(id) * VARIANTS.length));
}

function seedOneClassicPerRandomLane() {
  fs.rmSync(RUNTIME, { recursive: true, force: true });
  fs.mkdirSync(LANTERNS, { recursive: true });
  const selected = new Map();

  for (let index = 0; index < 5000 && selected.size < 4; index += 1) {
    const id = `random_lane_${String(index).padStart(4, '0')}`;
    const laneIndex = laneIndexForId(id);
    if (!selected.has(laneIndex)) selected.set(laneIndex, id);
  }
  if (selected.size !== 4) throw new Error('Could not find one stable id per display lane');

  const baseTime = Date.UTC(2026, 8, 6, 12, 0, 0) / 1000;
  return [...selected.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([laneIndex, id], sequence) => {
      const file = path.join(LANTERNS, `${id}__classic.png`);
      fs.copyFileSync(SAMPLE, file);
      const timestamp = baseTime + sequence;
      fs.utimesSync(file, timestamp, timestamp);
      return { laneIndex, id };
    });
}

async function installCanvasProbe(page) {
  await page.addInitScript(() => {
    window.__lanternDraws = [];
    const original = CanvasRenderingContext2D.prototype.drawImage;
    CanvasRenderingContext2D.prototype.drawImage = function patchedDrawImage(image, ...args) {
      try {
        const src = image && image.src ? String(image.src) : '';
        if (src.includes('/generated/lanterns/') || src.includes('/static/sample_lantern.png')) {
          const transform = this.getTransform();
          window.__lanternDraws.push({ src, x: transform.e, y: transform.f, at: performance.now() });
          if (window.__lanternDraws.length > 4000) window.__lanternDraws.splice(0, 2000);
        }
      } catch {}
      return original.call(this, image, ...args);
    };
  });
}

function recentPosition(draws, variantOrPath) {
  const matches = draws.filter((draw) => draw.src.includes(variantOrPath));
  return matches.length ? matches[matches.length - 1] : null;
}

test.beforeEach(async () => {
  seedLanterns();
});

test.afterEach(async () => {
  fs.rmSync(RUNTIME, { recursive: true, force: true });
});

test('display hydrates all templates and keeps the canvas animated', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await installCanvasProbe(page);

  await page.goto('/display');
  await expect(page.getByRole('heading', { name: 'PHỐ ĐÈN KÝ ỨC' })).toBeVisible();
  await expect(page.locator('#lanternTotal')).toHaveText('4');
  await expect(page.locator('#connectionStatus')).toHaveText('Live');

  await page.waitForFunction(() => {
    const draws = window.__lanternDraws || [];
    return ['classic', 'balloon', 'round', 'rectangle'].every((variant) =>
      draws.some((draw) => draw.src.includes(`__${variant}.png`))
    );
  });

  const first = await page.evaluate(() => window.__lanternDraws.slice());
  await page.waitForTimeout(700);
  const second = await page.evaluate(() => window.__lanternDraws.slice());

  const firstPositions = Object.fromEntries(VARIANTS.map((variant) => [variant, recentPosition(first, `__${variant}.png`)]));
  const secondPositions = Object.fromEntries(VARIANTS.map((variant) => [variant, recentPosition(second, `__${variant}.png`)]));

  for (const variant of VARIANTS) {
    expect(firstPositions[variant], `${variant} should render`).toBeTruthy();
    expect(secondPositions[variant], `${variant} should keep rendering`).toBeTruthy();
  }

  const canvas = page.locator('#sky');
  const firstFrame = await canvas.screenshot();
  await page.waitForTimeout(350);
  const secondFrame = await canvas.screenshot();
  expect(Buffer.compare(firstFrame, secondFrame)).not.toBe(0);
  expect(pageErrors).toEqual([]);
});

test('websocket demo is pushed into a display lane without changing persisted total', async ({ page, request }) => {
  await installCanvasProbe(page);
  await page.goto('/display');
  await expect(page.locator('#lanternTotal')).toHaveText('4');
  await expect(page.locator('#connectionStatus')).toHaveText('Live');

  const response = await request.post('/api/demo');
  expect(response.ok()).toBeTruthy();

  await page.waitForFunction(() =>
    (window.__lanternDraws || []).some((draw) => draw.src.includes('/static/sample_lantern.png'))
  );

  const draws = await page.evaluate(() => window.__lanternDraws.slice());
  const demo = recentPosition(draws, '/static/sample_lantern.png');
  expect(demo).toBeTruthy();
  await expect(page.locator('#lanternTotal')).toHaveText('4');
});

test('same template lanterns are distributed across stable random lanes', async ({ page }) => {
  const seeded = seedOneClassicPerRandomLane();
  await installCanvasProbe(page);
  await page.goto('/display');
  await expect(page.locator('#lanternTotal')).toHaveText('4');

  await page.waitForFunction((ids) => {
    const draws = window.__lanternDraws || [];
    return ids.every((id) => draws.some((draw) => draw.src.includes(`${id}__classic.png`)));
  }, seeded.map((entry) => entry.id));

  const draws = await page.evaluate(() => window.__lanternDraws.slice());
  const positions = seeded.map((entry) => recentPosition(draws, `${entry.id}__classic.png`));
  positions.forEach((position) => expect(position).toBeTruthy());
  expect(positions[0].y).toBeLessThan(positions[1].y);
  expect(positions[1].y).toBeLessThan(positions[2].y);
  expect(positions[2].y).toBeLessThan(positions[3].y);
});

test('visible slots do not cap persisted or looping lantern history', async ({ page, request }) => {
  seedLongHistory(16);
  await installCanvasProbe(page);

  const response = await request.get('/api/display-state');
  expect(response.ok()).toBeTruthy();
  const state = await response.json();
  expect(state.totalCount).toBe(19);
  expect(state.lanterns.filter((item) => item.variant === 'classic')).toHaveLength(16);

  await page.goto('/display');
  await expect(page.locator('#lanternTotal')).toHaveText('19');
  await page.waitForFunction(() =>
    (window.__lanternDraws || []).some((draw) => draw.src.includes('history_0011__classic.png'))
  );
});

test('control exposes all four printable templates and survives missing camera', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto('/control', { waitUntil: 'domcontentloaded' });

  await expect(page.getByRole('heading', { name: 'Scanner Control' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Classic' })).toHaveAttribute('href', '/templates/lantern_template.png');
  await expect(page.getByRole('link', { name: 'Balloon' })).toHaveAttribute('href', '/templates/lantern_template_balloon.png');
  await expect(page.getByRole('link', { name: 'Round' })).toHaveAttribute('href', '/templates/lantern_template_round.png');
  await expect(page.getByRole('link', { name: 'Rectangle' })).toHaveAttribute('href', '/templates/lantern_template_rectangle.png');
  await expect(page.locator('#readyBadge')).toContainText(/Camera error|Camera warning|Checking/);
  expect(pageErrors).toEqual([]);
});
