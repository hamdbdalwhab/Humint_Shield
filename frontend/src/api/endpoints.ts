/**
 * Typed API surface. Every backend endpoint used by the UI is wrapped here so
 * components never build URLs by hand.
 */
import { http } from '@/api/client';
import type {
  AccessTokenResponse,
  AIGeneratedTemplate,
  AIGenerateTemplateRequest,
  Assignment,
  Branding,
  BrandingUpdate,
  BrevoVerification,
  BulkImportResult,
  Campaign,
  CampaignActivity,
  CampaignCreate,
  CampaignRecipientDetail,
  CampaignResults,
  DashboardSummary,
  EmailDesign,
  EmailTemplate,
  EmailTemplateCreate,
  EmailTemplateUpdate,
  Employee,
  EmployeeCreate,
  EmployeeDossier,
  EmployeeUpdate,
  HealthReport,
  LaunchResult,
  LiveBoard,
  Paginated,
  PhishingReport,
  QRScan,
  QRSubmissionPayload,
  QRSubmissionResult,
  RuntimeConfig,
  ReportSafeResponse,
  SimulationChoiceResponse,
  SimulationVisitResponse,
  TemplatePreview,
  TemplateTestSendRequest,
  TemplateTestSendResult,
  TimelineEvent,
  TokenResponse,
  TrackingCompletePayload,
  TrackingCompleteResponse,
  TrackingContext,
  TrackingSubmission,
  TrainingModule,
  User,
  VonageVerification,
} from '@/types';

export interface EmployeeListParams {
  page?: number;
  per_page?: number;
  search?: string;
  department?: string;
  is_active?: boolean;
}

export const authApi = {
  async login(username: string, password: string): Promise<TokenResponse> {
    const { data } = await http.post<TokenResponse>('/api/v1/auth/login', { username, password });
    return data;
  },
  async refresh(refreshToken: string): Promise<AccessTokenResponse> {
    const { data } = await http.post<AccessTokenResponse>('/api/v1/auth/refresh', {
      refresh_token: refreshToken,
    });
    return data;
  },
  async logout(): Promise<void> {
    await http.post('/api/v1/auth/logout');
  },
  async me(): Promise<User> {
    const { data } = await http.get<User>('/api/v1/auth/me');
    return data;
  },
};

export const employeesApi = {
  async list(orgId: string, params: EmployeeListParams = {}): Promise<Paginated<Employee>> {
    const { data } = await http.get<Paginated<Employee>>(
      `/api/v1/organizations/${orgId}/employees`,
      { params },
    );
    return data;
  },
  async get(orgId: string, id: string): Promise<Employee> {
    const { data } = await http.get<Employee>(`/api/v1/organizations/${orgId}/employees/${id}`);
    return data;
  },
  async create(orgId: string, payload: EmployeeCreate): Promise<Employee> {
    const { data } = await http.post<Employee>(
      `/api/v1/organizations/${orgId}/employees`,
      payload,
    );
    return data;
  },
  async update(orgId: string, id: string, payload: EmployeeUpdate): Promise<Employee> {
    const { data } = await http.put<Employee>(
      `/api/v1/organizations/${orgId}/employees/${id}`,
      payload,
    );
    return data;
  },
  async remove(orgId: string, id: string): Promise<void> {
    await http.delete(`/api/v1/organizations/${orgId}/employees/${id}`);
  },
  async bulkImport(orgId: string, file: File): Promise<BulkImportResult> {
    const form = new FormData();
    form.append('file', file);
    const { data } = await http.post<BulkImportResult>(
      `/api/v1/organizations/${orgId}/employees/bulk`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return data;
  },
  async timeline(orgId: string, id: string): Promise<TimelineEvent[]> {
    const { data } = await http.get<TimelineEvent[]>(
      `/api/v1/organizations/${orgId}/employees/${id}/timeline`,
    );
    return data;
  },
  async dossier(orgId: string, id: string): Promise<EmployeeDossier> {
    const { data } = await http.get<EmployeeDossier>(
      `/api/v1/organizations/${orgId}/employees/${id}/dossier`,
    );
    return data;
  },
};

export const templatesApi = {
  async list(orgId: string, params: { search?: string; is_active?: boolean; channel?: string } = {}) {
    const { data } = await http.get<EmailTemplate[]>(
      `/api/v1/organizations/${orgId}/email-templates`,
      { params },
    );
    return data;
  },
  async create(orgId: string, payload: EmailTemplateCreate): Promise<EmailTemplate> {
    const { data } = await http.post<EmailTemplate>(
      `/api/v1/organizations/${orgId}/email-templates`,
      payload,
    );
    return data;
  },
  async update(orgId: string, id: string, payload: EmailTemplateUpdate): Promise<EmailTemplate> {
    const { data } = await http.put<EmailTemplate>(
      `/api/v1/organizations/${orgId}/email-templates/${id}`,
      payload,
    );
    return data;
  },
  async remove(orgId: string, id: string): Promise<void> {
    await http.delete(`/api/v1/organizations/${orgId}/email-templates/${id}`);
  },
  async preview(orgId: string, id: string, employeeId: string): Promise<TemplatePreview> {
    const { data } = await http.post<TemplatePreview>(
      `/api/v1/organizations/${orgId}/email-templates/${id}/preview`,
      { employee_id: employeeId },
    );
    return data;
  },
  async design(orgId: string, id: string): Promise<EmailDesign> {
    const { data } = await http.get<EmailDesign>(
      `/api/v1/organizations/${orgId}/email-templates/${id}/design`,
    );
    return data;
  },
  async sendTest(
    orgId: string,
    payload: TemplateTestSendRequest,
  ): Promise<TemplateTestSendResult> {
    const { data } = await http.post<TemplateTestSendResult>(
      `/api/v1/organizations/${orgId}/email-templates/test-send`,
      payload,
    );
    return data;
  },
};

export const brandingApi = {
  async get(orgId: string): Promise<Branding> {
    const { data } = await http.get<Branding>(`/api/v1/organizations/${orgId}/branding`);
    return data;
  },
  async update(orgId: string, payload: BrandingUpdate): Promise<Branding> {
    const { data } = await http.put<Branding>(
      `/api/v1/organizations/${orgId}/branding`,
      payload,
    );
    return data;
  },
  async uploadLogo(orgId: string, file: File): Promise<Branding> {
    const form = new FormData();
    form.append('file', file);
    const { data } = await http.post<Branding>(
      `/api/v1/organizations/${orgId}/branding/logo`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return data;
  },
  async removeLogo(orgId: string): Promise<Branding> {
    const { data } = await http.delete<Branding>(
      `/api/v1/organizations/${orgId}/branding/logo`,
    );
    return data;
  },
};

export const aiApi = {
  async generateTemplate(payload: AIGenerateTemplateRequest): Promise<AIGeneratedTemplate> {
    const { data } = await http.post<AIGeneratedTemplate>(
      '/api/v1/ai/generate-template',
      payload,
    );
    return data;
  },
};

export const campaignsApi = {
  async list(orgId: string, status?: string): Promise<Campaign[]> {
    const { data } = await http.get<Campaign[]>(
      `/api/v1/organizations/${orgId}/email-campaigns`,
      { params: status ? { status } : {} },
    );
    return data;
  },
  async get(orgId: string, id: string): Promise<Campaign> {
    const { data } = await http.get<Campaign>(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}`,
    );
    return data;
  },
  async create(orgId: string, payload: CampaignCreate): Promise<Campaign> {
    const { data } = await http.post<Campaign>(
      `/api/v1/organizations/${orgId}/email-campaigns`,
      payload,
    );
    return data;
  },
  async remove(orgId: string, id: string): Promise<void> {
    await http.delete(`/api/v1/organizations/${orgId}/email-campaigns/${id}`);
  },
  async update(
    orgId: string,
    id: string,
    payload: Partial<CampaignCreate>,
  ): Promise<Campaign> {
    const { data } = await http.put<Campaign>(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}`,
      payload,
    );
    return data;
  },
  async launch(orgId: string, id: string): Promise<LaunchResult> {
    const { data } = await http.post<LaunchResult>(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}/launch`,
    );
    return data;
  },
  async results(orgId: string, id: string): Promise<CampaignResults> {
    const { data } = await http.get<CampaignResults>(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}/results`,
    );
    return data;
  },
  async live(orgId: string, id: string): Promise<LiveBoard> {
    const { data } = await http.get<LiveBoard>(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}/live`,
    );
    return data;
  },
  async recipient(
    orgId: string,
    campaignId: string,
    employeeId: string,
  ): Promise<CampaignRecipientDetail> {
    const { data } = await http.get<CampaignRecipientDetail>(
      `/api/v1/organizations/${orgId}/email-campaigns/${campaignId}/recipients/${employeeId}`,
    );
    return data;
  },
  async activity(orgId: string, campaignId: string, limit = 1000): Promise<CampaignActivity> {
    const { data } = await http.get<CampaignActivity>(
      `/api/v1/organizations/${orgId}/email-campaigns/${campaignId}/activity`,
      { params: { limit } },
    );
    return data;
  },
  exportUrl(orgId: string, id: string): string {
    return `/api/v1/organizations/${orgId}/email-campaigns/${id}/export`;
  },
  async exportCsv(orgId: string, id: string): Promise<Blob> {
    const { data } = await http.get(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}/export`,
      { responseType: 'blob' },
    );
    return data as Blob;
  },
  async generateQrPosters(id: string): Promise<Blob> {
    const { data } = await http.post(
      `/api/v1/campaigns/${id}/generate-qr`,
      {},
      { responseType: 'blob' },
    );
    return data as Blob;
  },
  async scans(orgId: string, id: string): Promise<QRScan[]> {
    const { data } = await http.get<QRScan[]>(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}/scans`,
    );
    return data;
  },
  async getCampaignScans(campaignId: string): Promise<QRScan[]> {
    const { data } = await http.get<QRScan[]>(
      `/api/v1/campaigns/${campaignId}/scans`,
    );
    return data;
  },
  async assignScan(
    orgId: string,
    id: string,
    scanId: string,
    employeeId: string,
  ): Promise<{ success: boolean; message: string; scan: QRScan | null }> {
    const { data } = await http.post(
      `/api/v1/organizations/${orgId}/email-campaigns/${id}/scans/${scanId}/assign`,
      { employee_id: employeeId },
    );
    return data;
  },
  async generateUsbPdf(id: string, employeeId?: string): Promise<Blob> {
    const { data } = await http.post(
      `/api/v1/campaigns/${id}/generate-usb-pdf`,
      {},
      {
        params: employeeId ? { employee_id: employeeId } : {},
        responseType: 'blob',
      },
    );
    return data as Blob;
  },
  async generateUsbHtml(id: string, employeeId?: string): Promise<Blob> {
    const { data } = await http.post(
      `/api/v1/campaigns/${id}/generate-usb-html`,
      {},
      {
        params: employeeId ? { employee_id: employeeId } : {},
        responseType: 'blob',
      },
    );
    return data as Blob;
  },
  async generateUsbTestPayload(id: string): Promise<{
    success: boolean;
    campaign_id: string;
    tracking_uuid: string;
    organization_name: string;
    assets: Array<{
      filename: string;
      content_base64: string;
      type: string;
      size: number;
      description: string;
    }>;
  }> {
    const { data } = await http.get(`/api/v1/campaigns/${id}/generate-test-payload`);
    return data;
  },
  async generateHidScript(id: string): Promise<{
    success: boolean;
    campaign_id: string;
    tracking_uuid: string;
    organization_name: string;
    target_url: string;
    ducky_script: string;
    pico_circuitpython: string;
    digispark_arduino: string;
  }> {
    const { data } = await http.get(`/api/v1/campaigns/${id}/generate-hid-script`);
    return data;
  },
  async getUsbAgentStatus(): Promise<{
    online: boolean;
    agent?: string;
    version?: string;
    drives: Array<{
      drive: string;
      label: string;
      fs_type: string;
      is_removable: boolean;
      is_system?: boolean;
      type_name: string;
      free_gb: number;
      total_gb: number;
    }>;
  }> {
    const { data } = await http.get('/api/v1/campaigns/usb-agent/status');
    return data;
  },
  async deployUsbAgentAssets(payload: {
    drive: string;
    assets: any[];
  }): Promise<{
    type: string;
    drive?: string;
    files?: string[];
    message?: string;
  }> {
    const { data } = await http.post('/api/v1/campaigns/usb-agent/deploy', payload);
    return data;
  },
};

export const reportsApi = {
  async executivePdf(campaignId: string): Promise<Blob> {
    const { data } = await http.get('/api/v1/reports/executive-pdf', {
      params: { campaign_id: campaignId },
      responseType: 'blob',
    });
    return data as Blob;
  },
  async generateUsbTestPayload(id: string): Promise<{
    success: boolean;
    campaign_id: string;
    tracking_uuid: string;
    organization_name: string;
    assets: Array<{
      filename: string;
      content_base64: string;
      type: string;
      size: number;
      description: string;
    }>;
  }> {
    const { data } = await http.get(`/api/v1/campaigns/${id}/generate-test-payload`);
    return data;
  },
};

export const securityApi = {
  async playbook(): Promise<Blob> {
    const { data } = await http.get('/api/v1/security/playbook', {
      responseType: 'blob',
    });
    return data as Blob;
  },
  async usbGuide(): Promise<Blob> {
    const { data } = await http.get('/api/v1/security/usb-guide', {
      responseType: 'blob',
    });
    return data as Blob;
  },
  async generateUsbTestPayload(id: string): Promise<{
    success: boolean;
    campaign_id: string;
    tracking_uuid: string;
    organization_name: string;
    assets: Array<{
      filename: string;
      content_base64: string;
      type: string;
      size: number;
      description: string;
    }>;
  }> {
    const { data } = await http.get(`/api/v1/campaigns/${id}/generate-test-payload`);
    return data;
  },
};

export const lmsApi = {
  async dashboard(orgId: string): Promise<DashboardSummary> {
    const { data } = await http.get<DashboardSummary>(
      `/api/v1/organizations/${orgId}/dashboard`,
    );
    return data;
  },
  async modules(orgId: string): Promise<TrainingModule[]> {
    const { data } = await http.get<TrainingModule[]>(
      `/api/v1/organizations/${orgId}/training-modules`,
    );
    return data;
  },
  async assignments(orgId: string, params: { status?: string; employee_id?: string } = {}) {
    const { data } = await http.get<Assignment[]>(
      `/api/v1/organizations/${orgId}/assignments`,
      { params },
    );
    return data;
  },
  async createAssignment(
    orgId: string,
    payload: { module_id: string; employee_id?: string; due_date?: string; notes?: string },
  ): Promise<Assignment> {
    const { data } = await http.post<Assignment>(
      `/api/v1/organizations/${orgId}/assignments`,
      payload,
    );
    return data;
  },
  async completeAssignment(orgId: string, id: string): Promise<Assignment> {
    const { data } = await http.post<Assignment>(
      `/api/v1/organizations/${orgId}/assignments/${id}/complete`,
    );
    return data;
  },
  async reports(orgId: string, status?: string): Promise<PhishingReport[]> {
    const { data } = await http.get<PhishingReport[]>(
      `/api/v1/organizations/${orgId}/reports`,
      { params: status ? { status } : {} },
    );
    return data;
  },
  async updateReport(
    orgId: string,
    id: string,
    payload: { status?: string; triage_notes?: string },
  ): Promise<PhishingReport> {
    const { data } = await http.put<PhishingReport>(
      `/api/v1/organizations/${orgId}/reports/${id}`,
      payload,
    );
    return data;
  },
};

export const trackingApi = {
  async context(trackingUuid: string): Promise<TrackingContext> {
    const { data } = await http.get<TrackingContext>(
      `/api/v1/track/context/${trackingUuid}`,
    );
    return data;
  },
  async qrCampaignContext(campaignId: string): Promise<TrackingContext> {
    const { data } = await http.get<TrackingContext>(
      `/api/v1/track/qr/campaign/${campaignId}/context`,
    );
    return data;
  },
  async submitQr(payload: QRSubmissionPayload): Promise<QRSubmissionResult> {
    const { data } = await http.post<QRSubmissionResult>(
      '/api/v1/track/qr/submit',
      payload,
    );
    return data;
  },
  async formViewed(trackingUuid: string): Promise<void> {
    await http.post(`/api/v1/track/form-view/${trackingUuid}`);
  },
  async submit(trackingUuid: string, payload: TrackingSubmission) {
    const { data } = await http.post<{ success: boolean; first_time: boolean; message: string }>(
      `/api/v1/track/submit/${trackingUuid}`,
      payload,
    );
    return data;
  },
  async submitOtp(trackingUuid: string, otpCode: string) {
    const { data } = await http.post<{ success: boolean; first_time: boolean; message: string }>(
      `/api/v1/track/otp/${trackingUuid}`,
      { otp_code: otpCode },
    );
    return data;
  },
  async complete(
    trackingUuid: string,
    payload: TrackingCompletePayload,
  ): Promise<TrackingCompleteResponse> {
    const { data } = await http.post<TrackingCompleteResponse>(
      `/api/v1/track/complete/${trackingUuid}`,
      payload,
    );
    return data;
  },
  async report(trackingUuid: string) {
    const { data } = await http.post<{ success: boolean; message: string }>(
      `/api/v1/track/report/${trackingUuid}`,
    );
    return data;
  },
  async reportSafe(trackingUuid: string): Promise<ReportSafeResponse> {
    const { data } = await http.post<ReportSafeResponse>(
      `/api/v1/track/report-safe/${trackingUuid}`,
    );
    return data;
  },
  async visit(
    trackingUuid: string,
    channel: 'qr' | 'vishing' | 'pretexting',
  ): Promise<SimulationVisitResponse> {
    const { data } = await http.post<SimulationVisitResponse>(
      `/api/v1/track/visit/${trackingUuid}`,
      undefined,
      { params: { channel } },
    );
    return data;
  },
  async vishingChoice(
    trackingUuid: string,
    choice: 'credential_disclosed' | 'reported_phish',
  ): Promise<SimulationChoiceResponse> {
    const { data } = await http.post<SimulationChoiceResponse>(
      `/api/v1/track/vishing/${trackingUuid}`,
      { choice },
    );
    return data;
  },
  async pretextingChoice(
    trackingUuid: string,
    choice: 'financial_fraud' | 'reported_phish',
  ): Promise<SimulationChoiceResponse> {
    const { data } = await http.post<SimulationChoiceResponse>(
      `/api/v1/track/pretexting/${trackingUuid}`,
      { choice },
    );
    return data;
  },
};

export const diagnosticsApi = {
  async health(): Promise<HealthReport> {
    const { data } = await http.get<HealthReport>('/api/v1/test/health');
    return data;
  },
  async config(): Promise<RuntimeConfig> {
    const { data } = await http.get<RuntimeConfig>('/api/v1/test/config');
    return data;
  },
  async sendTestEmail(toEmail: string) {
    const { data } = await http.post('/api/v1/test/brevo', { to_email: toEmail });
    return data as { success: boolean; message_id: string | null; error: string | null };
  },
  async verifyBrevo(): Promise<BrevoVerification> {
    const { data } = await http.get<BrevoVerification>('/api/v1/test/brevo/verify');
    return data;
  },
  async verifyVonage(channel: 'sms' | 'whatsapp'): Promise<VonageVerification> {
    const { data } = await http.get<VonageVerification>('/api/v1/test/vonage/verify', {
      params: { channel },
    });
    return data;
  },
};


export const containmentApi = {
  async getStatus(): Promise<{
    containment_enabled: boolean;
    entra_id: { configured: boolean; tenant_id: string; client_id: string; high_risk_group_id: string };
    active_directory: { configured: boolean; domain_controller: string; domain: string; strict_password_group: string; powershell_available: boolean };
    soar_webhook: { configured: boolean; webhook_url: string };
    supported_actions: string[];
  }> {
    const { data } = await http.get('/api/v1/containment/status');
    return data;
  },

  async triggerContainment(payload: {
    target_identity: string;
    breach_type: string;
    campaign_id?: string;
    tracking_uuid?: string;
    actions?: string[];
  }): Promise<{
    target_identity: string;
    breach_type: string;
    tracking_uuid: string;
    executed_at: string;
    overall_status: string;
    summary_ar: string;
    summary_en: string;
    results: Array<{
      action: string;
      provider: string;
      status: string;
      message_ar: string;
      message_en: string;
      timestamp: string;
      details: Record<string, any>;
    }>;
  }> {
    const { data } = await http.post('/api/v1/containment/trigger', payload);
    return data;
  },

  async getCampaignLogs(campaignId: string): Promise<any[]> {
    const { data } = await http.get(`/api/v1/containment/campaign-log/${campaignId}`);
    return data;
  },
};
