/**
 * The simulated sign-in page is the first step of every email simulation.
 *
 * These tests protect the 1-2-3-4 sequence: tracked email link -> sign-in form
 * -> attack-chain reveal -> awareness/training. They also cover the migration
 * case where a recipient completed the training page under an older build that
 * skipped the form; those recipients must still see the form once.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { trackingApi } from '@/api/endpoints';
import { PhishingLandingPage } from '@/pages/PhishingLandingPage';
import type { TrackingContext } from '@/types';

jest.mock('@/api/endpoints', () => ({
  trackingApi: {
    context: jest.fn(),
    formViewed: jest.fn(),
    submit: jest.fn(),
    report: jest.fn(),
  },
}));

const TRACKING_UUID = '2f1c9a1e-6f2a-4f2e-9d3a-1b2c3d4e5f60';

const contextMock = trackingApi.context as jest.Mock;
const formViewedMock = trackingApi.formViewed as jest.Mock;
const submitMock = trackingApi.submit as jest.Mock;

const BASE_CONTEXT: TrackingContext = {
  found: true,
  first_name: 'Test',
  last_name: 'Employee',
  email: 'employee@example.com',
  company_name: 'Acme Corporation',
  template_name: 'Urgent Password Change',
  subject: 'Urgent: Your password must be changed',
  campaign_name: 'Security test',
  channel: 'email',
  skin: 'microsoft',
  form_submitted: false,
  already_completed: false,
  is_reported_safe: false,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/phish/${TRACKING_UUID}`]}>
        <Routes>
          <Route path="/phish/:trackingUuid" element={<PhishingLandingPage />} />
          <Route path="/hacked/:trackingUuid" element={<div>hacked-page</div>} />
          <Route
            path="/training-experience/:trackingUuid"
            element={<div>training-experience-page</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  formViewedMock.mockResolvedValue(undefined);
  submitMock.mockResolvedValue({ success: true, first_time: true, message: 'ok' });
  contextMock.mockResolvedValue(BASE_CONTEXT);
});

describe('PhishingLandingPage', () => {
  it('shows the sign-in form when a legacy training completion exists without a submission', async () => {
    contextMock.mockResolvedValue({
      ...BASE_CONTEXT,
      already_completed: true,
      form_submitted: false,
    });

    renderPage();

    expect(await screen.findByPlaceholderText('Password')).toBeInTheDocument();
    expect(screen.queryByText('training-experience-page')).not.toBeInTheDocument();
  });

  it('skips the form when the recipient already submitted it', async () => {
    contextMock.mockResolvedValue({
      ...BASE_CONTEXT,
      already_completed: true,
      form_submitted: true,
    });

    renderPage();

    await waitFor(() =>
      expect(screen.getByText('training-experience-page')).toBeInTheDocument(),
    );
  });

  it('moves to the attack-chain reveal after credentials are submitted', async () => {
    renderPage();

    const password = await screen.findByPlaceholderText('Password');
    fireEvent.change(password, { target: { value: 'TestPassword123!' } });
    fireEvent.click(screen.getByRole('button', { name: /^Sign in$/i }));

    await waitFor(
      () => expect(screen.getByText('hacked-page')).toBeInTheDocument(),
      { timeout: 3_000 },
    );
    expect(submitMock).toHaveBeenCalledWith(
      TRACKING_UUID,
      expect.objectContaining({ identifier: 'employee@example.com' }),
    );
  });
});
