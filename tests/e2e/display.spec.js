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

test('display hydrates four template strings and animates in alternating directions', async ({ page }) => {
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

  const laneYs = VARIANTS.map((variant) => secondPositions[variant].y);
  expect(laneYs[0]).toBeLessThan(laneYs[1]);
  expect(laneYs[1]).toBeLessThan(laneYs[2]);
  expect(laneYs[2]).toBeLessThan(laneYs[3]);

  expect(secondPositions.classic.x).toBeLessThan(firstPositions.classic.x);
  expect(secondPositions.balloon.x).toBeGreaterThan(firstPositions.balloon.x);
  expect(secondPositions.round.x).toBeLessThan(firstPositions.round.x);
  expect(secondPositions.rectangle.x).toBeGreaterThan(firstPositions.rectangle.x);

  const movement = Object.fromEntries(VARIANTS.map((variant) => [
    variant,
    Math.abs(secondPositions[variant].x - firstPositions[variant].x),
  ]));
  expect(movement.round).toBeGreaterThan(movement.classic);
  expect(movement.classic).toBeGreaterThan(movement.rectangle);
  expect(movement.rectangle).toBeGreaterThan(movement.balloon);

  const canvas = page.locator('#sky');
  const firstFrame = await canvas.screenshot();
  await page.waitForTimeout(350);
  const secondFrame = await canvas.screenshot();
  expect(Buffer.compare(firstFrame, secondFrame)).not.toBe(0);
  expect(pageErrors).toEqual([]);
});

test('websocket demo is pushed into the matching classic string without changing persisted total', async ({ page, request }) => {
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
  const classic = recentPosition(draws, '__classic.png');
  const demo = recentPosition(draws, '/static/sample_lantern.png');
  expect(classic).toBeTruthy();
  expect(demo).toBeTruthy();
  expect(Math.abs(classic.y - demo.y)).toBeLessThan(12);
  await expect(page.locator('#lanternTotal')).toHaveText('4');
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
