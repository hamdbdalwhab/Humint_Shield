/**
 * Module 1 UI contract: the Create Template dialog must call the real AI
 * endpoint, show a loading state, and autofill the three generated fields. The
 * test never mocks a template client-side; it asserts the endpoint payload.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { aiApi, employeesApi, templatesApi } from '@/api/endpoints';
import { TemplatesPage } from '@/pages/TemplatesPage';
import type { AIGeneratedTemplate } from '@/types';

jest.mock('@/api/endpoints', () => ({
  aiApi: { generateTemplate: jest.fn() },
  employeesApi: { list: jest.fn() },
  templatesApi: {
    list: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
    remove: jest.fn(),
    preview: jest.fn(),
  },
}));

jest.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ organizationId: 'org-1' }),
}));

const aiMock = aiApi.generateTemplate as jest.Mock;
const templatesListMock = templatesApi.list as jest.Mock;
const employeesListMock = employeesApi.list as jest.Mock;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TemplatesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('TemplatesPage AI generation', () => {
  beforeEach(() => {
    templatesListMock.mockResolvedValue([]);
    employeesListMock.mockResolvedValue({ items: [], total: 0, page: 1, per_page: 200 });
  });

  it('calls the AI endpoint, shows loading, and autofills the form', async () => {
    let resolveGenerate!: (value: AIGeneratedTemplate) => void;
    aiMock.mockReturnValue(
      new Promise<AIGeneratedTemplate>((resolve) => {
        resolveGenerate = resolve;
      }),
    );

    renderPage();
    fireEvent.click(screen.getByRole('button', { name: /قالب جديد/i }));

    const generateButton = await screen.findByRole('button', {
      name: /Generate with AI/i,
    });
    expect(generateButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText('القسم المستهدف'), {
      target: { value: 'Finance' },
    });
    fireEvent.change(screen.getByLabelText('السيناريو المطلوب'), {
      target: { value: 'Urgent invoice from a known supplier' },
    });
    expect(generateButton).toBeEnabled();

    fireEvent.click(generateButton);
    expect(await screen.findByText('جارٍ توليد القالب…')).toBeInTheDocument();
    expect(aiMock).toHaveBeenCalledWith({
      target_department: 'Finance',
      scenario: 'Urgent invoice from a known supplier',
      channel: 'email',
    });

    await act(async () => {
      resolveGenerate({
        subject: 'فاتورة عاجلة مطلوبة',
        body_html: '<p>مرحباً {{first_name}}</p><a href="{{tracking_url}}">مراجعة</a>',
        difficulty_level: 8,
        provider: 'test',
        model: 'test-model',
      });
    });

    await waitFor(() =>
      expect(screen.getByLabelText(/موضوع الرسالة/)).toHaveValue('فاتورة عاجلة مطلوبة'),
    );
    expect(screen.getByLabelText('جسم الرسالة (HTML)')).toHaveValue(
      '<p>مرحباً {{first_name}}</p><a href="{{tracking_url}}">مراجعة</a>',
    );
    expect(screen.getByRole('slider')).toHaveAttribute('aria-valuenow', '8');
    expect(screen.getByLabelText(/اسم القالب/)).toHaveValue('فاتورة عاجلة مطلوبة');
  });
});
