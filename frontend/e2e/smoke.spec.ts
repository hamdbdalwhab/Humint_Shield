/**
 * End-to-end smoke test for the awareness platform.
 *
 * Prerequisite: a running backend + frontend with the bootstrap admin seeded
 * (see docker-compose.yml). Credentials are read from the environment so the
 * suite never hard-codes secrets.
 *
 *   E2E_BASE_URL=http://localhost:8080 \
 *   E2E_ADMIN_USER=admin E2E_ADMIN_PASSWORD=ChangeMe123! npx playwright test
 */
import { expect, test, type Page } from '@playwright/test';

const USERNAME = process.env.E2E_ADMIN_USER ?? 'admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'ChangeMe123!';

/**
 * Sign in and wait until the authenticated shell has rendered.
 *
 * The wait matters: navigating away before the login request settles aborts it,
 * leaving the session unauthenticated and every later assertion meaningless.
 */
async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill(USERNAME);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
}

test.describe('HUMINT Shield', () => {
  test('rejects anonymous access and shows the sign-in page', async ({ page }) => {
    await page.goto('/campaigns');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: /HUMINT Shield/i })).toBeVisible();
  });

  test('administrator can sign in and reach the dashboard', async ({ page }) => {
    await signIn(page);
    await expect(page.getByText(/Open rate/i)).toBeVisible();
  });

  test('campaign, template and LMS pages render for an authenticated admin', async ({ page }) => {
    await signIn(page);

    for (const [path, heading] of [
      ['/templates', 'Templates'],
      ['/campaigns', 'Campaigns'],
      ['/employees', 'Employees'],
      ['/training-library', 'Training Library'],
      ['/assignments', 'Assignments'],
      ['/report-inbox', 'Report Inbox'],
      ['/settings', 'Settings'],
    ] as const) {
      await page.goto(path);
      await expect(page.getByRole('heading', { name: heading, level: 1 })).toBeVisible();
    }
  });

  test('unknown training link shows the standalone disclosure page', async ({ page }) => {
    const response = await page.goto('/training/00000000-0000-0000-0000-000000000000');
    expect(response?.status()).toBe(200);
    await expect(page.getByText(/Training link not recognised/i)).toBeVisible();
  });

  test('seeded phishing templates are listed', async ({ page }) => {
    await signIn(page);

    await page.goto('/templates');
    await expect(page.getByText(/built-in/i).first()).toBeVisible();
    await expect(page.getByText('Urgent Password Change')).toBeVisible();
  });
});
