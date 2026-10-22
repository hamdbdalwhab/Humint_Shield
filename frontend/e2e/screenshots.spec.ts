/**
 * Documentation screenshot capture.
 *
 * Drives the running application with headless Chromium and writes full-page
 * PNGs for the README / release evidence. Not an assertion suite — it fails only
 * if a page does not render.
 *
 *   E2E_BASE_URL=http://127.0.0.1:5173 \
 *   E2E_ADMIN_USER=admin E2E_ADMIN_PASSWORD=ChangeMe123! \
 *   npx playwright test e2e/screenshots.spec.ts
 */
import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT_DIR = fileURLToPath(new URL('../../docs/screenshots/', import.meta.url));
const USERNAME = process.env.E2E_ADMIN_USER ?? 'admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'ChangeMe123!';

/** Wait until rendering and data fetching have settled. */
async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(800);
}

test.describe.configure({ mode: 'serial' });

test('capture the administrative pages', async ({ page }) => {
  await page.goto('/login');
  await settle(page);
  await page.screenshot({ path: path.join(OUT_DIR, '01-login.png'), fullPage: true });

  await page.getByLabel('Username').fill(USERNAME);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

  const routes: Array<[string, string]> = [
    ['/', '02-dashboard'],
    ['/employees', '03-employees'],
    ['/templates', '04-templates'],
    ['/campaigns', '05-campaigns'],
    ['/campaigns/new', '06-new-campaign-wizard'],
    ['/training-library', '07-training-library'],
    ['/assignments', '08-assignments'],
    ['/my-training', '09-my-training'],
    ['/report-inbox', '10-report-inbox'],
    ['/settings', '11-settings'],
  ];

  for (const [route, name] of routes) {
    await page.goto(route);
    await settle(page);
    await page.screenshot({ path: path.join(OUT_DIR, `${name}.png`), fullPage: true });
  }

  // Campaign results/analytics detail (first campaign in the list, if any).
  await page.goto('/campaigns');
  await settle(page);
  const firstCampaign = page.locator('table tbody tr a').first();
  if ((await firstCampaign.count()) > 0) {
    await firstCampaign.click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(OUT_DIR, '05b-campaign-detail.png'), fullPage: true });
  }
});

test('capture the recipient micro-learning page', async ({ page }) => {
  const uuid = process.env.E2E_TRACKING_UUID;
  const backend = process.env.E2E_BACKEND_URL;
  test.skip(!uuid || !backend, 'E2E_TRACKING_UUID and E2E_BACKEND_URL are required');

  await page.goto(`${backend}/training/${uuid}`);
  await settle(page);
  await page.screenshot({ path: path.join(OUT_DIR, '12-training-page.png'), fullPage: true });
});
