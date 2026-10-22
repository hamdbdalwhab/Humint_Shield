/**
 * End-to-end coverage for the two "prove exactly what happened" surfaces:
 *
 * * the per-employee dossier page (`/employees/{id}`), and
 * * the per-recipient dialog inside a campaign (`/campaigns/{id}`).
 *
 * Both are read-only, so the tests never send email or mutate data. They skip
 * cleanly on a fresh database without employees or campaigns.
 */
import { expect, test, type Page } from '@playwright/test';

const USERNAME = process.env.E2E_ADMIN_USER ?? 'admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? 'ChangeMe123!';

async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username').fill(USERNAME);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
}

test.describe('Interaction evidence', () => {
  test('employee dossier lists every campaign, event and submission', async ({ page }) => {
    await signIn(page);
    await page.goto('/employees');
    await expect(page.getByRole('heading', { name: 'Employees', level: 1 })).toBeVisible();

    const dossier = page.getByRole('button', { name: 'Full dossier' }).first();
    // The directory is fetched asynchronously: wait for the first action before
    // deciding that the organization really has no employees.
    const hasEmployees = await dossier
      .waitFor({ state: 'visible', timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasEmployees) test.skip(true, 'no employees in this organization');
    await dossier.click();

    await expect(page).toHaveURL(/\/employees\/[0-9a-f-]{36}$/);
    await expect(page.getByRole('tab', { name: /Full activity/ })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Entered data/ })).toBeVisible();

    await page.getByRole('tab', { name: /Full activity/ }).click();
    await expect(
      page.getByText(/Every event is listed in the order the server recorded it/),
    ).toBeVisible();
  });

  test('campaign recipient dialog exposes overview, timeline and typed data', async ({ page }) => {
    await signIn(page);
    await page.goto('/campaigns');
    await expect(page.getByRole('heading', { name: 'Campaigns', level: 1 })).toBeVisible();

    const view = page.getByRole('button', { name: /^View / });
    if ((await view.count()) === 0) test.skip(true, 'no campaigns in this organization');
    await view.first().click();

    const openDossier = page.getByRole('button', { name: /^Open dossier for / }).first();
    await expect(openDossier).toBeVisible();
    await openDossier.click();

    await expect(page.getByRole('tab', { name: 'Overview' })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Timeline/ })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Entered data/ })).toBeVisible();

    await page.getByRole('tab', { name: /Entered data/ }).click();
    await expect(page.getByText(/stored encrypted/i).first()).toBeVisible();
  });
});
