/**
 * The training page is the educational payoff of the attack-chain reveal. It
 * must show the simulated assets the recipient put at risk, in Arabic with an
 * English secondary label, without ever exposing the typed password.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { trackingApi } from '@/api/endpoints';
import { TrainingExperiencePage } from '@/pages/TrainingExperiencePage';
import type { TrackingContext } from '@/types';

jest.mock('@/api/endpoints', () => ({
  trackingApi: {
    context: jest.fn(),
    complete: jest.fn(),
    report: jest.fn(),
  },
}));

const TRACKING_UUID = '2f1c9a1e-6f2a-4f2e-9d3a-1b2c3d4e5f60';
const contextMock = trackingApi.context as jest.Mock;

const CONTEXT: TrackingContext = {
  found: true,
  first_name: 'Test',
  last_name: 'Employee',
  email: 'employee@example.com',
  company_name: 'Acme Corporation',
  template_name: 'HR Portal · Employee Records Review',
  subject: 'Update your employee information',
  campaign_name: 'Security test',
  channel: 'email',
  skin: 'hr',
  form_submitted: true,
  already_completed: false,
  is_reported_safe: false,
  compromised_assets: [
    'كلمة مرور بريدك الإلكتروني',
    'الوصول إلى ملفات الموارد البشرية',
  ],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/training-experience/${TRACKING_UUID}`]}>
        <Routes>
          <Route
            path="/training-experience/:trackingUuid"
            element={<TrainingExperiencePage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TrainingExperiencePage compromised assets', () => {
  it('lists the simulated assets with English secondary labels', async () => {
    contextMock.mockResolvedValue(CONTEXT);
    renderPage();

    expect(await screen.findByText('ما الذي حصل عليه المهاجم؟')).toBeInTheDocument();
    expect(screen.getByText('كلمة مرور بريدك الإلكتروني')).toBeInTheDocument();
    expect(screen.getByText('Your Email Password')).toBeInTheDocument();
    expect(screen.getByText('الوصول إلى ملفات الموارد البشرية')).toBeInTheDocument();
    expect(screen.getByText('Access to HR Files')).toBeInTheDocument();
    expect(screen.getByText('محاكاة — لا ضرر فعلي')).toBeInTheDocument();
  });
});
