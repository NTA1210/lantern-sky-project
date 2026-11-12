const { test, expect } = require('@playwright/test');

const USERNAME = process.env.LANTERN_CONTROL_USER || 'e2e_admin';
const PASSWORD = process.env.LANTERN_CONTROL_PASSWORD || 'e2e_secret_password_123';

async function loginToControl(page) {
  await page.goto('/control');
  await expect(page).toHaveURL(/\/login/);
  await page.locator('#username').fill(USERNAME);
  await page.locator('#password').fill(PASSWORD);
  await page.locator('#loginSubmitBtn').click();
  await expect(page).toHaveURL(/\/control$/);
  await expect(page.getByRole('heading', { name: 'Trung Tâm Điều Khiển' })).toBeVisible();
}

async function assertDialogFitsViewport(page, dialogSelector, keyControls = []) {
  const viewport = page.viewportSize();
  const dialog = page.locator(dialogSelector);
  await expect(dialog).toBeVisible();

  const box = await dialog.boundingBox();
  expect(box, `${dialogSelector} should have boundingBox`).toBeTruthy();
  expect(box.x, `${dialogSelector} left edge >= 0`).toBeGreaterThanOrEqual(0);
  expect(box.y, `${dialogSelector} top edge >= 0`).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width, `${dialogSelector} right edge <= viewport width`).toBeLessThanOrEqual(viewport.width + 0.5);
  expect(box.y + box.height, `${dialogSelector} bottom edge <= viewport height`).toBeLessThanOrEqual(viewport.height + 0.5);

  // Verify no horizontal overflow inside the dialog scroll container
  const overflowCheck = await dialog.evaluate((el) => {
    const scrollArea = el.querySelector('.modal-body-scroll');
    return {
      dialogClientWidth: el.clientWidth,
      dialogScrollWidth: el.scrollWidth,
      bodyClientWidth: scrollArea ? scrollArea.clientWidth : 0,
      bodyScrollWidth: scrollArea ? scrollArea.scrollWidth : 0,
    };
  });
  expect(overflowCheck.dialogScrollWidth).toBeLessThanOrEqual(overflowCheck.dialogClientWidth + 1);
  expect(overflowCheck.bodyScrollWidth).toBeLessThanOrEqual(overflowCheck.bodyClientWidth + 2);

  for (const selector of keyControls) {
    const control = page.locator(selector);
    await expect(control).toBeVisible();
    const cBox = await control.boundingBox();
    expect(cBox, `${selector} should have boundingBox`).toBeTruthy();
    expect(cBox.y).toBeGreaterThanOrEqual(0);
    expect(cBox.y + cBox.height).toBeLessThanOrEqual(viewport.height + 0.5);
    expect(cBox.x).toBeGreaterThanOrEqual(0);
    expect(cBox.x + cBox.width).toBeLessThanOrEqual(viewport.width + 0.5);
  }
}

test('unauthenticated requests to control redirect to login while display remains public', async ({ page, request }) => {
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/control');
  await expect(page).toHaveURL(/\/login\?next=(%2F|\/)control/);
  await expect(page.getByRole('heading', { name: 'Đăng Nhập Control' })).toBeVisible();

  const apiStatus = await request.get('/api/status');
  expect(apiStatus.status()).toBe(401);

  const apiSettings = await request.get('/api/settings');
  expect(apiSettings.status()).toBe(401);

  const apiStream = await request.get('/api/camera/stream');
  expect(apiStream.status()).toBe(401);

  // Display remains accessible without login
  await page.goto('/display');
  await expect(page.locator('#sky')).toBeVisible();
  await expect(page.locator('#connectionStatus')).toHaveText('Live');
  expect(pageErrors).toEqual([]);
});

test('login form validates, toggles password, logs in, persists, and logs out', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await page.goto('/login');
  await expect(page.locator('#username')).toHaveAttribute('autocomplete', 'username');
  await expect(page.locator('#password')).toHaveAttribute('autocomplete', 'current-password');

  // Toggle password visibility
  await page.locator('#password').fill('wrong-password');
  await expect(page.locator('#password')).toHaveAttribute('type', 'password');
  await page.locator('#togglePasswordBtn').click();
  await expect(page.locator('#password')).toHaveAttribute('type', 'text');
  await expect(page.locator('#togglePasswordBtn')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('#togglePasswordBtn').click();
  await expect(page.locator('#password')).toHaveAttribute('type', 'password');

  // Invalid login shows alert and stays on /login
  await page.locator('#username').fill(USERNAME);
  await page.locator('#loginSubmitBtn').click();
  await expect(page.locator('#loginError')).toBeVisible();
  await expect(page).toHaveURL(/\/login/);

  // Valid login enters /control
  await page.locator('#password').fill(PASSWORD);
  await page.locator('#loginSubmitBtn').click();
  await expect(page).toHaveURL(/\/control$/);
  await expect(page.getByRole('heading', { name: 'Trung Tâm Điều Khiển' })).toBeVisible();

  // Reload stays authenticated
  await page.reload();
  await expect(page).toHaveURL(/\/control$/);

  // Logout returns to /login and blocks /control again
  await page.locator('#logoutBtn').click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto('/control');
  await expect(page).toHaveURL(/\/login/);
  expect(pageErrors).toEqual([]);
});

test('settings and other modals stay completely inside viewport across screen sizes', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', (err) => pageErrors.push(err.message));

  await loginToControl(page);

  const viewports = [
    { name: 'desktop-large', width: 1600, height: 900 },
    { name: 'laptop-short-dpi', width: 1280, height: 640 },
    { name: 'laptop-1366x768', width: 1366, height: 768 },
    { name: 'mobile-portrait', width: 390, height: 664 },
  ];

  for (const vp of viewports) {
    await page.setViewportSize({ width: vp.width, height: vp.height });

    // 1. Settings modal fits viewport with header & footer pinned
    await page.locator('#openSettingsBtn').click();
    await assertDialogFitsViewport(page, '#settingsModal', [
      '#settingsModalCloseBtn',
      '#resetSettingsBtn',
      '#cancelSettingsBtn',
      '#saveSettingsBtn',
    ]);

    // On short screens, verify internal scroll container actually scrolls without moving dialog off-screen
    if (vp.height <= 680) {
      const scrollStats = await page.locator('#settingsModal .modal-body-scroll').evaluate((el) => {
        el.scrollTop = 200;
        return { scrollHeight: el.scrollHeight, clientHeight: el.clientHeight, scrollTop: el.scrollTop };
      });
      expect(scrollStats.scrollHeight).toBeGreaterThan(scrollStats.clientHeight);
      expect(scrollStats.scrollTop).toBeGreaterThan(0);
    }

    // Escape closes dialog
    await page.keyboard.press('Escape');
    await expect(page.locator('#settingsModal')).not.toBeVisible();

    // 2. Guide modal fits viewport
    await page.locator('#openGuideBtn').click();
    await assertDialogFitsViewport(page, '#guideModal', [
      '#guideModalCloseBtn',
      '#guideModalDoneBtn',
    ]);
    await page.locator('#guideModalDoneBtn').click();
    await expect(page.locator('#guideModal')).not.toBeVisible();

    // 3. Change password modal fits viewport
    await page.locator('#openChangePasswordBtn').click();
    await assertDialogFitsViewport(page, '#changePasswordModal', [
      '#changePasswordCloseBtn',
      '#changePasswordCancelBtn',
      '#changePasswordSubmitBtn',
    ]);
    await page.locator('#changePasswordCloseBtn').click();
    await expect(page.locator('#changePasswordModal')).not.toBeVisible();
  }

  // Verify saving settings persists through authenticated API
  await page.setViewportSize({ width: 1280, height: 640 });
  await page.locator('#openSettingsBtn').click();
  await page.locator('#conveyorSpeedInput').fill('1.8');
  await page.locator('#conveyorSpeedInput').dispatchEvent('input');
  await page.locator('#saveSettingsBtn').click();
  await expect(page.locator('#settingsModal')).not.toBeVisible();

  await page.reload();
  await page.locator('#openSettingsBtn').click();
  await expect(page.locator('#conveyorSpeedInput')).toHaveValue('1.8');
  await page.locator('#settingsModalCloseBtn').click();

  expect(pageErrors).toEqual([]);
});
