/**
 * The attack-chain reveal must be a real five-second interruption, not an
 * instant redirect, and it must hand the recipient to the training page only
 * after the red stop banner is visible.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { trackingApi } from '@/api/endpoints';
import { HackedPage } from '@/pages/HackedPage';

jest.mock('@/api/endpoints', () => ({
  trackingApi: {
    context: jest.fn(),
  },
}));

const TRACKING_UUID = '2f1c9a1e-6f2a-4f2e-9d3a-1b2c3d4e5f60';
const contextMock = trackingApi.context as jest.Mock;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/hacked/${TRACKING_UUID}`]}>
        <Routes>
          <Route path="/hacked/:trackingUuid" element={<HackedPage />} />
          <Route
            path="/training-experience/:trackingUuid"
            element={<div>training-page</div>}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  contextMock.mockResolvedValue({
    found: true,
    first_name: 'Test',
    last_name: 'Employee',
    email: 'employee@example.com',
    company_name: 'Acme Corporation',
    template_name: 'HR Portal',
    subject: 'Update your information',
    campaign_name: 'Security test',
    channel: 'email',
    skin: 'hr',
    form_submitted: true,
    already_completed: false,
    is_reported_safe: false,
    compromised_assets: ['كلمة مرور بريدك الإلكتروني'],
  });
});

describe('HackedPage', () => {
  it('types the attack chain and interrupts it with the red stop banner', async () => {
    renderPage();

    expect(
      await screen.findByText(/Bypassing firewall/i, undefined, { timeout: 3_000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/STOP! This was a simulation/i)).not.toBeInTheDocument();

    await waitFor(
      () =>
        expect(
          screen.getByText(
            /STOP! This was a simulation\. In a real attack, your credentials would have caused this damage\./i,
          ),
        ).toBeInTheDocument(),
      { timeout: 8_000 },
    );

    expect(screen.getByText(/Accessing HR database/i)).toBeInTheDocument();
    expect(screen.getByText(/Downloading 5GB of files/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /متابعة إلى التدريب/i }));
    await waitFor(() => expect(screen.getByText('training-page')).toBeInTheDocument());
  }, 15_000);
});
