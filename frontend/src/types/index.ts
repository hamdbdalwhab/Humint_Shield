/**
 * Shared API types. These mirror the backend Pydantic schemas exactly.
 */

export type Role = 'admin' | 'manager' | 'viewer';

export type CampaignStatus = 'draft' | 'active' | 'completed' | 'aborted';

/** Delivery channels supported by the campaign engine. */
export type CampaignChannel = 'email' | 'sms' | 'whatsapp' | 'qr' | 'vishing' | 'pretexting' | 'usb';

/** Channels delivered outside an email/SMS provider. */
export type SimulationChannel = 'qr' | 'vishing' | 'pretexting' | 'usb';

/** Credential-page skin selected in the campaign channel configuration. */
export type CredentialProvider = 'microsoft' | 'google' | 'hr';

export type EngagementStatus =
  | 'pending'
  | 'sent'
  | 'opened'
  | 'clicked'
  | 'submitted'
  | 'completed'
  | 'reported_safe'
  | 'failed';

/** Provider delivery receipt state for SMS/WhatsApp. */
export type DeliveryStatus =
  | 'submitted'
  | 'accepted'
  | 'buffered'
  | 'delivered'
  | 'read'
  | 'available'
  | 'failed'
  | 'rejected';

export type BehavioralCategory = 'unaware' | 'hesitant' | 'competent' | 'critical_risk';

/** Four-level badge derived from the independent Elo score. */
export type ThreatLevel = 'low' | 'medium' | 'high' | 'critical';

export interface User {
  id: string;
  username: string;
  email: string;
  role: Role;
  organization_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access: string;
  refresh: string;
  token_type: string;
  user: User;
}

export interface AccessTokenResponse {
  access: string;
  token_type: string;
}

export interface Employee {
  id: string;
  organization_id: string;
  email: string;
  phone: string | null;
  first_name: string;
  last_name: string;
  department: string | null;
  job_title: string | null;
  access_level: number;
  immunity_score: number;
  /** Independent adaptive-difficulty rating; starts at 1000. */
  elo_score: number;
  threat_level: ThreatLevel;
  behavioral_category: BehavioralCategory | null;
  total_tests_received: number;
  total_clicks: number;
  total_reports: number;
  total_credential_submissions: number;
  total_ignores: number;
  last_test_date: string | null;
  next_test_date: string | null;
  is_active: boolean;
  is_on_leave: boolean;
  requires_mandatory_training: boolean;
  under_enhanced_monitoring: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmployeeCreate {
  email: string;
  first_name: string;
  last_name?: string;
  phone?: string | null;
  department?: string | null;
  job_title?: string | null;
  access_level?: number;
  is_active?: boolean;
}

export interface EmployeeUpdate {
  email?: string;
  first_name?: string;
  last_name?: string;
  phone?: string | null;
  department?: string | null;
  job_title?: string | null;
  access_level?: number;
  is_active?: boolean;
  is_on_leave?: boolean;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface BulkImportResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export interface TimelineEvent {
  event_type: string;
  timestamp: string;
  campaign_id: string | null;
  campaign_name: string | null;
  details: Record<string, unknown> | null;
}

export type EmailDesignMode = 'blocks' | 'legacy';

export interface EmailDesignSettings {
  background_color: string;
  content_background_color: string;
  font_family: string;
  text_color: string;
  link_color: string;
  width: number;
  content_padding: number;
  border_radius: number;
  preheader: string;
}

export interface EmailDesignBlockBase {
  id: string;
  type: string;
  padding_top: number;
  padding_bottom: number;
  align: 'left' | 'center' | 'right';
}

export interface EmailTextBlock extends EmailDesignBlockBase {
  type: 'text';
  content: string;
  font_size: number;
  color: string | null;
  font_weight: 'normal' | 'bold';
  line_height: number;
}

export interface EmailImageBlock extends EmailDesignBlockBase {
  type: 'image';
  src: string;
  alt: string;
  link: string;
  width: number;
  border_radius: number;
}

export interface EmailButtonBlock extends EmailDesignBlockBase {
  type: 'button';
  label: string;
  url: string;
  background_color: string;
  text_color: string;
  border_radius: number;
  font_size: number;
  padding_x: number;
  padding_y: number;
}

export interface EmailDividerBlock extends EmailDesignBlockBase {
  type: 'divider';
  color: string;
  thickness: number;
  width_percent: number;
}

export interface EmailSpacerBlock extends EmailDesignBlockBase {
  type: 'spacer';
  height: number;
}

export interface EmailLogoBlock extends EmailDesignBlockBase {
  type: 'logo';
  width: number;
  link: string;
  alt: string;
  show_company_name: boolean;
}

export interface EmailFooterBlock extends EmailDesignBlockBase {
  type: 'footer';
  text: string;
  show_company_name: boolean;
  show_support_email: boolean;
  show_logo: boolean;
  font_size: number;
  color: string;
}

export interface EmailHtmlBlock extends EmailDesignBlockBase {
  type: 'html';
  html: string;
}

export type EmailDesignBlock =
  | EmailTextBlock
  | EmailImageBlock
  | EmailButtonBlock
  | EmailDividerBlock
  | EmailSpacerBlock
  | EmailLogoBlock
  | EmailFooterBlock
  | EmailHtmlBlock;

export interface EmailDesign {
  version: number;
  mode: EmailDesignMode;
  settings: EmailDesignSettings;
  blocks: EmailDesignBlock[];
  legacy_html?: string | null;
}

export interface Branding {
  organization_id: string;
  company_name: string;
  primary_color: string;
  support_email: string | null;
  logo_url: string | null;
  has_logo: boolean;
  updated_at: string | null;
}

export interface BrandingUpdate {
  company_name?: string;
  primary_color?: string;
  support_email?: string | null;
}

export interface EmailTemplate {
  id: string;
  organization_id: string;
  name: string;
  subject: string;
  body_html: string;
  design_json?: EmailDesign | null;
  channel: 'email' | 'sms' | 'whatsapp';
  difficulty_level: number;
  available_variables: string[];
  is_built_in: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmailTemplateCreate {
  name: string;
  subject: string;
  body_html?: string;
  design_json?: EmailDesign;
  channel?: 'email' | 'sms' | 'whatsapp';
  difficulty_level: number;
  is_active?: boolean;
  available_variables?: string[];
}

export interface EmailTemplateUpdate {
  name?: string;
  subject?: string;
  body_html?: string;
  design_json?: EmailDesign;
  channel?: 'email' | 'sms' | 'whatsapp';
  difficulty_level?: number;
  is_active?: boolean;
  available_variables?: string[];
}

export interface TemplateTestSendRequest {
  subject: string;
  body_html?: string;
  design_json?: EmailDesign;
  channel?: 'email' | 'sms' | 'whatsapp';
}

export interface TemplateTestSendResult {
  success: boolean;
  message_id: string | null;
  error: string | null;
  to_email: string;
  preview_html?: string | null;
}

export interface TemplatePreview {
  subject: string;
  html_content: string;
  /** Plain text rendered for SMS/WhatsApp previews. */
  text_content?: string | null;
  missing_variables: string[];
}

export interface AIGenerateTemplateRequest {
  target_department: string;
  scenario: string;
  channel?: 'email' | 'sms' | 'whatsapp';
}

export interface AIGeneratedTemplate {
  subject: string;
  body_html: string;
  difficulty_level: number;
  provider?: string;
  model?: string;
}

export type QrLureType = 'coffee' | 'bonus' | 'nomination' | 'hr' | 'wifi';

export interface QrBranding {
  lure_type: QrLureType;
  company_name: string;
  department: string;
  month_label: string;
  label: string;
  headline: string;
  body: string;
  cta: string;
  primary_color: string;
  accent_color: string;
  logo_url: string | null;
}

export interface QRScan {
  id: string;
  campaign_id: string;
  tracking_id: string | null;
  tracking_uuid: string | null;
  source_employee_id: string | null;
  source_employee_name: string | null;
  source_employee_email: string | null;
  employee_id: string | null;
  employee_name: string | null;
  employee_email: string | null;
  username: string | null;
  email: string | null;
  password_submitted: boolean;
  identity_resolution: string;
  occurred_at: string;
  ip_address: string | null;
  user_agent: string | null;
  fingerprint: Record<string, unknown>;
  fingerprint_hash: string | null;
  elo_delta: number;
  penalty_applied: boolean;
}

export interface QRSubmissionPayload {
  campaign_id: string;
  tracking_uuid?: string;
  username: string;
  email: string;
  password_submitted: boolean;
  fingerprint_data: Record<string, unknown>;
  fields?: Record<string, string>;
}

export interface QRSubmissionResult {
  success: boolean;
  first_time: boolean;
  unknown: boolean;
  message: string;
  identity_resolution: string | null;
  resolved_employee_id: string | null;
  resolved_employee_name: string | null;
  tracking_uuid: string | null;
  elo_delta: number;
  elo_score: number | null;
}

export interface CampaignChannelConfig {
  /** Credential-page skin used by the email landing page. */
  credential_provider?: CredentialProvider;
  /** Quishing poster copy, lure type and branding. */
  qr?: {
    pretext_key?: string;
    lure_type?: QrLureType;
    headline?: string;
    body?: string;
    footer?: string;
    label?: string;
    company_name?: string;
    department?: string;
    month_label?: string;
    primary_color?: string;
    accent_color?: string;
    logo_data_url?: string;
  };
  /** Optional vishing scenario copy; the fixed training script is used when absent. */
  vishing?: {
    caller_name?: string;
    script?: string;
  };
  /** Optional pretexting scenario copy; the fixed CEO message is used when absent. */
  pretexting?: {
    sender_name?: string;
    message?: string;
  };
  /** Safe USB-drop document metadata; the warning itself is fixed server-side. */
  usb?: {
    document_name?: string;
    month_label?: string;
  };
}

export interface Campaign {
  id: string;
  organization_id: string;
  template_id: string | null;
  name: string;
  channel: CampaignChannel;
  channel_config: CampaignChannelConfig | null;
  status: CampaignStatus;
  target_employee_ids: string[];
  total_targets: number;
  sent_count: number;
  failed_count: number;
  opened_count: number;
  clicked_count: number;
  completed_count: number;
  launched_at: string | null;
  completed_at: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface CampaignCreate {
  name: string;
  template_id: string;
  channel?: CampaignChannel;
  channel_config?: CampaignChannelConfig | null;
  difficulty_level: number;
  target_employee_ids: string[];
}

export interface LaunchFailure {
  employee_id: string;
  email: string;
  error: string;
}

export interface LaunchResult {
  campaign_id: string;
  total: number;
  sent: number;
  failed: number;
  failures: LaunchFailure[];
}

export interface CampaignStats {
  total: number;
  sent: number;
  failed: number;
  opened: number;
  clicked: number;
  submitted: number;
  completed: number;
  open_rate: number;
  click_rate: number;
  submission_rate: number;
  completion_rate: number;
}

export interface CampaignEmployeeResult {
  employee_id: string;
  tracking_uuid: string | null;
  name: string;
  email: string;
  phone: string | null;
  channel: CampaignChannel;
  department: string | null;
  job_title: string | null;
  status: EngagementStatus;
  sent_at: string | null;
  delivered_at: string | null;
  delivery_status: DeliveryStatus | null;
  delivery_error: string | null;
  read_at: string | null;
  failed_at: string | null;
  provider_message_id: string | null;
  opened_at: string | null;
  clicked_at: string | null;
  submitted_at: string | null;
  completed_at: string | null;
  form_viewed_at: string | null;
  reported_at: string | null;
  quiz_score: number | null;
  quiz_total: number | null;
  is_reported_safe: boolean;
  open_count: number;
  click_count: number;
  submission_count: number;
  submitted_identifier: string | null;
  submitted_fields: Record<string, string> | null;
  /** Every value the employee typed, decrypted (includes the password). */
  submitted_values: Record<string, string> | null;
  password_length: number | null;
  immunity_score: number | null;
  elo_score: number | null;
  threat_level: ThreatLevel | null;
  template_name: string | null;
  template_difficulty: number | null;
  behavioral_category: BehavioralCategory | null;
  error: string | null;
}

export interface CampaignResults {
  campaign: Campaign;
  stats: CampaignStats;
  employees: CampaignEmployeeResult[];
  /** QR campaigns only: every form submission, including Unknown scans. */
  scans?: QRScan[];
}

/** Live-board funnel status: the engagement funnel plus the form-render stage. */
export type LiveStatus = EngagementStatus | 'form_viewed';

export interface LiveCampaign {
  id: string;
  name: string;
  channel: CampaignChannel;
  status: CampaignStatus;
  template_name: string | null;
  difficulty_level: number | null;
  total_targets: number;
  sent_count: number;
  failed_count: number;
  created_at: string | null;
  launched_at: string | null;
  completed_at: string | null;
  elapsed_seconds: number | null;
}

export interface LiveSummary {
  total: number;
  sent: number;
  delivered: number;
  opened: number;
  clicked: number;
  form_viewed: number;
  submitted: number;
  reported: number;
  completed: number;
  failed: number;
  pending: number;
  active_last_5m: number;
  open_rate: number;
  click_rate: number;
  form_view_rate: number;
  submission_rate: number;
  completion_rate: number;
  avg_seconds_to_open: number | null;
  avg_seconds_to_click: number | null;
  avg_seconds_to_submit: number | null;
}

export interface LiveRecipient {
  employee_id: string;
  tracking_id: string;
  name: string;
  email: string;
  department: string | null;
  job_title: string | null;
  status: LiveStatus;
  reported: boolean;
  sent_at: string | null;
  delivered_at: string | null;
  opened_at: string | null;
  clicked_at: string | null;
  form_viewed_at: string | null;
  submitted_at: string | null;
  reported_at: string | null;
  completed_at: string | null;
  quiz_score: number | null;
  quiz_total: number | null;
  is_reported_safe: boolean;
  open_count: number;
  click_count: number;
  submission_count: number;
  interactions_count: number;
  seconds_to_open: number | null;
  seconds_to_click: number | null;
  seconds_to_form: number | null;
  seconds_to_submit: number | null;
  last_event_at: string | null;
  last_event_type: string | null;
  last_event_label: string | null;
  seconds_since_last_event: number | null;
  last_ip_address: string | null;
  last_user_agent: string | null;
  immunity_score: number | null;
  behavioral_category: BehavioralCategory | null;
  password_length: number | null;
  submitted_identifier: string | null;
}

export interface LiveEvent {
  id: string;
  employee_id: string;
  employee_name: string;
  event_type: string;
  label: string;
  occurred_at: string;
  seconds_ago: number;
  ip_address: string | null;
  user_agent: string | null;
}

export interface LiveBoard {
  campaign: LiveCampaign;
  summary: LiveSummary;
  recipients: LiveRecipient[];
  recent_events: LiveEvent[];
  generated_at: string;
}

/** One append-only ledger entry: what happened and exactly when. */
export interface InteractionEvent {
  id: string;
  event_type: string;
  occurred_at: string;
  ip_address: string | null;
  user_agent: string | null;
  details: Record<string, unknown> | null;
  /** Decrypted payload for submission events. */
  values: Record<string, string> | null;
  employee_id?: string | null;
  employee_name?: string | null;
  employee_email?: string | null;
  department?: string | null;
  campaign_id?: string | null;
  campaign_name?: string | null;
}

/** A single complete credential-form submission. */
export interface Submission {
  occurred_at: string;
  ip_address: string | null;
  user_agent: string | null;
  password_length: number | null;
  client: Record<string, unknown> | null;
  values: Record<string, string>;
  campaign_id?: string | null;
  campaign_name?: string | null;
}

/** Everything one employee did inside one campaign. */
export interface EmployeeCampaignRecord {
  campaign_id: string;
  campaign_name: string;
  campaign_status: CampaignStatus;
  template_name: string | null;
  channel: CampaignChannel;
  tracking_uuid: string;
  status: EngagementStatus;
  sent_at: string | null;
  delivered_at: string | null;
  delivery_status: DeliveryStatus | null;
  delivery_error: string | null;
  read_at: string | null;
  failed_at: string | null;
  provider_message_id: string | null;
  opened_at: string | null;
  clicked_at: string | null;
  form_viewed_at: string | null;
  submitted_at: string | null;
  reported_at: string | null;
  completed_at: string | null;
  quiz_score: number | null;
  quiz_total: number | null;
  is_reported_safe: boolean;
  open_count: number;
  click_count: number;
  submission_count: number;
  submitted_identifier: string | null;
  submitted_fields: Record<string, string> | null;
  submitted_values: Record<string, string> | null;
  client_context: Record<string, unknown> | null;
  events: InteractionEvent[];
  submissions: Submission[];
}

export interface EmployeeSummary {
  campaigns: number;
  emails_sent: number;
  opened: number;
  clicked: number;
  submitted: number;
  reported: number;
  completed: number;
  total_interactions: number;
  first_interaction_at: string | null;
  last_interaction_at: string | null;
}

/** The complete, second-by-second dossier for one employee. */
export interface EmployeeDossier {
  employee: Employee;
  summary: EmployeeSummary;
  campaigns: EmployeeCampaignRecord[];
  events: InteractionEvent[];
  submissions: Submission[];
}

export interface CampaignRecipientDetail {
  campaign: Campaign;
  employee: Employee;
  record: EmployeeCampaignRecord;
}

export interface CampaignActivity {
  campaign: Campaign;
  stats: CampaignStats;
  events: InteractionEvent[];
}

export interface TrainingModule {
  id: string;
  organization_id: string;
  title: string;
  summary: string | null;
  content_html: string;
  category: string | null;
  duration_minutes: number;
  difficulty_level: number;
  is_active: boolean;
  created_at: string;
}

export interface Assignment {
  id: string;
  module_id: string;
  employee_id: string | null;
  status: string;
  due_date: string | null;
  completed_at: string | null;
  notes: string | null;
  created_at: string;
  module_title: string | null;
  employee_name: string | null;
  employee_email: string | null;
}

export interface PhishingReport {
  id: string;
  employee_id: string | null;
  reported_email_subject: string | null;
  reported_sender: string | null;
  description: string | null;
  status: string;
  is_training_simulation: boolean;
  triage_notes: string | null;
  created_at: string;
}

export interface DashboardSummary {
  total_employees: number;
  active_employees: number;
  total_campaigns: number;
  active_campaigns: number;
  total_templates: number;
  total_emails_sent: number;
  total_opened: number;
  total_clicked: number;
  total_submitted: number;
  total_completed: number;
  open_rate: number;
  click_rate: number;
  submission_rate: number;
  reports_pending: number;
  critical_risk_employees: number;
  recent_campaigns: Array<{
    id: string;
    name: string;
    status: CampaignStatus;
    sent: number;
    opened: number;
    clicked: number;
    completed: number;
    created_at: string | null;
  }>;
  recent_events: Array<{
    id: string;
    employee_id: string;
    employee_name: string;
    employee_email: string;
    event_type: string;
    label: string;
    campaign_id: string;
    campaign_name: string;
    occurred_at: string | null;
    ip_address: string | null;
  }>;
  engagement_trend: Array<{
    date: string;
    opens: number;
    clicks: number;
    submissions: number;
    completed: number;
  }>;
}

export interface HealthReport {
  status: string;
  db: { ok: boolean; error: string | null };
  redis: { ok: boolean; error: string | null };
  brevo_configured: boolean;
  email_dry_run: boolean;
  vonage_configured?: boolean;
  vonage_sms_configured?: boolean;
  vonage_whatsapp_configured?: boolean;
}

export interface BrevoVerification {
  valid: boolean;
  error: string | null;
  detail: Record<string, unknown> | null;
  /** Set when Brevo is rejecting this server's egress IP. */
  blocked_ip?: string | null;
  action_required?: 'ip_allowlist' | 'credentials' | 'smtp_credentials' | null;
  action_url?: string | null;
  hint?: string | null;
}

export interface VonageVerification extends BrevoVerification {
  configured?: boolean;
  channel?: 'sms' | 'whatsapp';
  from?: string;
  missing?: string[];
  sms_ready?: boolean;
  whatsapp_ready?: boolean;
  vonage_configured?: boolean;
  vonage_application_configured?: boolean;
  application_configured?: boolean;
  messages_base_url?: string;
  webhook_urls?: {
    sms_dlr: string;
    whatsapp_status: string;
  };
  webhook_token_required?: boolean;
}

export interface TrackingCompleteResponse {
  success: boolean;
  already_completed: boolean;
  message: string;
  quiz_score?: number | null;
  quiz_total?: number | null;
  immunity_score?: number | null;
  behavioral_category?: BehavioralCategory | null;
}

export interface TrackingCompletePayload {
  score: number;
  total: number;
}

export interface ReportSafeResponse {
  success: boolean;
  message: string;
  quiz_score?: number | null;
  quiz_total?: number | null;
  immunity_score?: number | null;
  behavioral_category?: BehavioralCategory | null;
  already_reported_safe?: boolean;
}

export interface TrackingContext {
  found: boolean;
  first_name?: string;
  last_name?: string;
  email?: string;
  company_name?: string;
  template_name?: string;
  subject?: string;
  sender_name?: string;
  campaign_name?: string;
  campaign_id?: string;
  channel?: CampaignChannel;
  channel_config?: CampaignChannelConfig | null;
  /** Resolved lure/branding for the QR landing page. */
  qr_branding?: QrBranding | null;
  skin?: CredentialProvider;
  credential_provider?: CredentialProvider;
  brand_primary_color?: string;
  brand_logo_url?: string | null;
  form_submitted?: boolean;
  already_completed?: boolean;
  quiz_score?: number | null;
  quiz_total?: number | null;
  is_reported_safe?: boolean;
  /** Whether the recipient already chose a vishing/pretexting outcome. */
  reported?: boolean;
  /** Safe, human-readable assets shown on the post-submit reveal. */
  compromised_assets?: string[];
}

export interface TrackingSubmission {
  identifier: string;
  /** The React pages never transmit the typed password. */
  password?: string;
  password_length: number;
  fields: Record<string, string>;
  client: Record<string, unknown>;
  /** Explicitly instruct the backend to discard any secret material. */
  capture_secret?: boolean;
}

export interface SimulationChoiceResponse {
  success: boolean;
  choice: 'credential_disclosed' | 'financial_fraud' | 'reported_phish';
  message: string;
  already_recorded: boolean;
  elo_score: number | null;
  threat_level: ThreatLevel | null;
  redirect_url: string | null;
}

export interface SimulationVisitResponse {
  success: boolean;
  first_time: boolean;
  message: string;
  immunity_score?: number | null;
  behavioral_category?: BehavioralCategory | null;
}

export interface RuntimeConfig {
  base_url: string;
  frontend_url: string;
  from_email: string;
  from_name: string;
  email_transport: 'brevo' | 'smtp';
  brevo_configured: boolean;
  smtp_configured: boolean;
  email_dry_run: boolean;
  vonage_configured?: boolean;
  vonage_sms_configured?: boolean;
  vonage_whatsapp_configured?: boolean;
  vonage_application_configured?: boolean;
  vonage_sms_from?: string;
  vonage_whatsapp_from?: string;
  vonage_webhook_paths?: {
    sms_dlr: string;
    whatsapp_status: string;
  };
  rate_limit_enabled: boolean;
  environment: string;
}
