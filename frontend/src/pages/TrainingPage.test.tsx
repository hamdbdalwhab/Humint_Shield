/**
 * Behavioural tests for the micro-learning page: it must disclose the exercise,
 * lock completion behind the 60-second countdown, and record completion through
 * the public tracking endpoint.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { TrainingPage } from '@/pages/TrainingPage';

const TRACKING_UUID = '2f1c9a1e-6f2a-4f2e-9d3a-1b2c3d4e5f60';

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/training/${TRACKING_UUID}`]}>
      <Routes>
        <Route path="/training/:trackingUuid" element={<TrainingPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('TrainingPage', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('discloses that the message was an authorized exercise', () => {
    renderPage();
    expect(screen.getByText(/this was a training exercise/i)).toBeInTheDocument();
    expect(screen.getByText(/no data was compromised/i)).toBeInTheDocument();
  });

  it('lists the red flags and the protective best practices', () => {
    renderPage();
    expect(screen.getByText(/red flags you may have missed/i)).toBeInTheDocument();
    expect(screen.getByText(/how to protect yourself/i)).toBeInTheDocument();
  });

  it('keeps completion locked until the countdown elapses', () => {
    renderPage();
    expect(screen.getByRole('button', { name: /please wait 60s/i })).toBeDisabled();
  });

  it('unlocks completion after the countdown and records it through the API', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        already_completed: false,
        message: 'Training completed. Thank you — +5 awareness points.',
      }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    renderPage();

    await act(async () => {
      jest.advanceTimersByTime(60_000);
    });

    const button = screen.getByRole('button', { name: /mark as complete/i });
    expect(button).toBeEnabled();

    await act(async () => {
      fireEvent.click(button);
    });

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/training completed/i),
    );

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/track/complete/${TRACKING_UUID}`,
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('surfaces an error when the API responds with a failure status', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: false, status: 500 });
    global.fetch = fetchMock as unknown as typeof fetch;

    renderPage();

    await act(async () => {
      jest.advanceTimersByTime(60_000);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /mark as complete/i }));
    });

    await waitFor(() => expect(screen.getByText(/500/)).toBeInTheDocument());
  });
});
