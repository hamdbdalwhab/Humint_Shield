/**
 * New campaign wizard: Details → Targets → Review → Launch.
 *
 * Each step is self-contained and validates before advancing:
 *
 * 1. **Details** — name, template (with a sandboxed visual preview) and
 *    difficulty.
 * 2. **Targets** — filterable audience with per-department counts, bulk
 *    selection of everything that matches the current filters, and a removable
 *    selection summary. Chosen employees are kept in a map so the review step can
 *    list them even after the filters change.
 * 3. **Review** — the exact campaign, the exact recipients and an explicit
 *    "this sends real email" confirmation before anything leaves the server.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Checkbox from '@mui/material/Checkbox';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import FormControlLabel from '@mui/material/FormControlLabel';
import LinearProgress from '@mui/material/LinearProgress';
import Link from '@mui/material/Link';
import MenuItem from '@mui/material/MenuItem';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import Step from '@mui/material/Step';
import StepLabel from '@mui/material/StepLabel';
import Stepper from '@mui/material/Stepper';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import DownloadIcon from '@mui/icons-material/Download';
import CloseIcon from '@mui/icons-material/Close';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { campaignsApi, diagnosticsApi, employeesApi, templatesApi } from '@/api/endpoints';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import type { CooldownBlockedEmployee, Employee, QrLureType } from '@/types';

const STEPS = ['التفاصيل', 'المستهدفون', 'المراجعة'];
const QR_STEPS = ['التفاصيل وإعداد الملصق', 'المراجعة والإطلاق'];
const USB_STEPS = ['إعداد طعم فلاشة الـ USB الميداني', 'المراجعة والإطلاق'];

export const USB_SCENARIOS = [
  {
    id: 'salaries',
    title: 'كشف الرواتب والمكافآت السنوية (Salaries & Bonuses Q4)',
    volume: 'HR_SALARIES',
    lureFile: 'كشف_رواتب_الموظفين_والزيادات_2026.xlsx',
    badge: 'طمع مالي وفضول عالي',
    description: 'ملف إكسل مموه ككشف رواتب وحوافز استثنائية لجميع الموظفين، يثير الفضول المالي فوراً.',
  },
  {
    id: 'layoffs',
    title: 'تقييمات الأداء وقوائم إنهاء الخدمات (Confidential Restructuring)',
    volume: 'CONFIDENTIAL',
    lureFile: 'قائمة_الموظفين_المشمولين_بالتصفيات_Q4.pdf',
    badge: 'دافع القلق والأمان الوظيفي',
    description: 'ملف بصيغة PDF يوحي بوجود قرارات سرية بإعادة هيكلة وتخفيض موظفين، يستهدف خوف الموظف على وظيفته.',
  },
  {
    id: 'ceo_backup',
    title: 'نسخة احتياطية خاصة للمدير التنفيذي (CEO Private Backup)',
    volume: 'CEO_BACKUP',
    lureFile: 'ملاحظات_اجتماع_مجلس_الإدارة_2026.docx',
    badge: 'طعم VIP حساس وسري',
    description: 'فلاشة خاصة بالإدارة العليا توهم الموظف بأنه عثر على ملفات ومراسلات استراتيجية حساسة.',
  },
  {
    id: 'finance_audit',
    title: 'فواتير ومستحقات مالية عاجلة (Pending Invoices & Audits)',
    volume: 'FINANCE_AUDIT',
    lureFile: 'فواتير_مستعجلة_للصرف_2026.pdf',
    badge: 'استعجال وضغط مالي',
    description: 'ملفات تدقيق ومطالبات مالية متأخرة تتطلب المراجعة الفورية.',
  },
  {
    id: 'it_tools',
    title: 'أدوات الدعم الفني وتحديثات الـ VPN (IT Support & Network Tools)',
    volume: 'IT_SUPPORT',
    lureFile: 'تحديث_شهادات_الأمان_والشبكة_VPN.bat',
    badge: 'ثقة الإدارة التقنية',
    description: 'حزمة أدوات تدعي أنها تحديث أمني عاجل لشهادات الدخول والاتصال بالشبكة الداخلية.',
  },
];

export const USB_DROP_LOCATIONS = [
  'مواقف سيارات الموظفين — Corporate Parking Lot',
  'كافتيريا واستراحة الشركة — Employee Cafeteria',
  'مصعد الطابق التنفيذي — Executive Elevator',
  'مكتب الاستقبال الرئيسي — Main Reception Desk',
  'قاعة الاجتماعات والمؤتمرات — Executive Boardroom',
  'الممرات وقرب دورات المياه — Restrooms / Hallway',
];

type WizardChannel =
  | 'email'
  | 'sms'
  | 'whatsapp'
  | 'qr'
  | 'vishing'
  | 'pretexting'
  | 'usb'
  | 'voice';

const CHANNEL_LABELS: Record<WizardChannel, string> = {
  email: 'البريد الإلكتروني — Brevo',
  sms: 'رسائل SMS — Smishing (TextBee)',
  whatsapp: 'واتساب — Smishing (WA-AKG)',
  qr: 'رمز QR — Quishing (طباعة يدوية)',
  vishing: 'مكالمة صوتية — Vishing (رابط يدوي)',
  pretexting: 'محادثة CEO — Pretexting (رابط يدوي)',
  usb: 'فلاشة USB — HTML/PDF توعوي (توزيع يدوي)',
  voice: 'مكالمة صوتية حقيقية — IllyVoIP',
};

const DEFAULT_VOICE_SCRIPT =
  'Hello, this is the IT security desk. We detected a suspicious sign-in on your account. Please confirm the verification code you just received so we can secure it.';

/** Delivered-length budget for one SMS segment. */
const SMS_MAX_LENGTH = 170;
/** Stand-in for `{{link}}` when counting, matching the real short URL shape. */
const SMS_SAMPLE_LINK = 'https://hument.link/s/AbCdEf';

const SMS_LANDING_PAGES = [
  { value: 'auto', label: 'تلقائي — حسب القسم والكلمات المفتاحية' },
  { value: 'cisco_vpn', label: 'Cisco AnyConnect — VPN' },
  { value: 'supplier_portal', label: 'Supplier Portal — الفواتير' },
  { value: 'hr_portal', label: 'HR Portal — السياسات' },
  { value: 'teams_invite', label: 'Microsoft Teams — اجتماع' },
  { value: 'microsoft_login', label: 'Microsoft 365 — تسجيل دخول' },
  { value: 'general_login', label: 'بوابة عامة — General login' },
];

const SMS_DEPARTMENTS = [
  { value: '', label: 'كل الأقسام — بدون تخصيص' },
  { value: 'it', label: 'IT — تقنية المعلومات' },
  { value: 'finance', label: 'Finance — المالية' },
  { value: 'hr', label: 'HR — الموارد البشرية' },
  { value: 'executive', label: 'Executive — الإدارة العليا' },
];

/** Mirrors the backend LandingPageResolver keyword rules for live feedback. */
const SMS_KEYWORD_RULES: Array<[string, string[]]> = [
  ['cisco_vpn', ['vpn', 'anyconnect', 'certificate', 'network', 'firewall', 'remote access']],
  ['supplier_portal', ['invoice', 'payment', 'supplier', 'purchase order', 'remittance', 'wire']],
  ['hr_portal', ['policy', 'hr', 'sign', 'handbook', 'acknowledg', 'benefits', 'payroll']],
  ['teams_invite', ['meeting', 'teams', 'board', 'calendar', 'invite', 'conference']],
  ['microsoft_login', ['password', 'login', 'log in', 'sign in', 'account', 'mfa', '2fa', 'otp']],
];

function detectSmsLandingPage(message: string): string | null {
  const text = message.toLowerCase();
  for (const [page, keywords] of SMS_KEYWORD_RULES) {
    if (keywords.some((keyword) => text.includes(keyword))) return page;
  }
  return null;
}

function smsDeliveredLength(message: string): number {
  return message.replaceAll('{{link}}', SMS_SAMPLE_LINK).trim().length;
}

const QR_TEMPLATE_LURES: Record<string, string> = {
  'قهوة مجانية': 'coffee',
  'مكافأة مالية': 'bonus',
  'ترشيح لأفضل موظف': 'nomination',
  'تحديث بيانات HR': 'hr',
  'شبكة الواي فاي': 'wifi',
};

const QR_LURES: { value: string; label: string; hint: string }[] = [
  {
    value: 'coffee',
    label: 'قهوة مجانية — Free Coffee',
    hint: 'قسيمة مشروب مجاني من كافتيريا الشركة. مناسبة للأماكن المشتركة.',
  },
  {
    value: 'bonus',
    label: 'مكافأة مالية — Salary Raise / Bonus',
    hint: 'إقرار مكافأة أداء من الإدارة المالية مع طلب تأكيد البيانات.',
  },
  {
    value: 'nomination',
    label: 'ترشيح لأفضل موظف — Top Employee',
    hint: 'ترشيح شهري رسمي. يتطلب تحديد الشهر الظاهر على الملصق.',
  },
  {
    value: 'hr',
    label: 'تحديث بيانات الموارد البشرية — HR Update',
    hint: 'بوابة الموارد البشرية تطلب تحديث بيانات الموظف.',
  },
  {
    value: 'wifi',
    label: 'تسجيل دخول الواي فاي — Wi-Fi Access',
    hint: 'بوابة شبكة ضيوف تتطلب التحقق من الهوية مرة واحدة.',
  },
];

/** Strict E.164: country code plus 8-15 digits, no separators. */
const E164_PATTERN = /^\+[1-9]\d{7,14}$/;

function hasValidPhone(phone: string | null | undefined): boolean {
  return Boolean(phone && E164_PATTERN.test(phone.trim()));
}

function difficultyLabel(value: number): string {
  if (value <= 3) return 'سهل — مؤشرات واضحة';
  if (value <= 6) return 'متوسط — واقعي لكن قابل للكشف';
  return 'صعب — خفيّ ومستعجل';
}

export function NewCampaignPage() {
  const { organizationId } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const preselectId = searchParams.get('employeeId');

  const [step, setStep] = useState(0);
  const [launchedQrId, setLaunchedQrId] = useState<string | null>(null);
  const [downloadingPoster, setDownloadingPoster] = useState(false);
  const [name, setName] = useState('');
  const [channel, setChannel] = useState<WizardChannel>('email');
  const [qrPretext, setQrPretext] = useState('hr');
  const [qrCompany, setQrCompany] = useState('');
  const [qrDepartment, setQrDepartment] = useState('');
  const [qrMonth, setQrMonth] = useState('');
  const [qrPrimary, setQrPrimary] = useState('#0F6CBD');
  const [qrAccent, setQrAccent] = useState('#1F3A5F');
  const [qrLogo, setQrLogo] = useState<string>('');
  const [qrLogoError, setQrLogoError] = useState<string | null>(null);
  const [usbScenario, setUsbScenario] = useState('salaries');
  const [usbDropLocation, setUsbDropLocation] = useState(USB_DROP_LOCATIONS[0]);
  const [usbVolumeLabel, setUsbVolumeLabel] = useState('HR_SALARIES');
  const [usbDrive, setUsbDrive] = useState('');
  const [usbDriveList, setUsbDriveList] = useState<
    Array<{
      drive: string;
      label: string;
      fs_type: string;
      is_removable: boolean;
      is_system: boolean;
      type_name: string;
      free_gb: number;
      total_gb: number;
      writable: boolean;
    }>
  >([]);
  const [usbDrivesLoading, setUsbDrivesLoading] = useState(false);
  const [voiceScript, setVoiceScript] = useState(DEFAULT_VOICE_SCRIPT);
  const [voiceRingOnly, setVoiceRingOnly] = useState(false);
  const [smsMode, setSmsMode] = useState<'template' | 'custom'>('template');
  const [smsMessage, setSmsMessage] = useState(
    'Your VPN session expires today. Please re-authenticate here: {{link}}',
  );
  const [smsDepartment, setSmsDepartment] = useState('');
  const [smsLandingPage, setSmsLandingPage] = useState('auto');
  const [templateId, setTemplateId] = useState('');
  const [difficulty, setDifficulty] = useState(5);
  const [autoRetestFailed, setAutoRetestFailed] = useState(false);
  const [mandatoryTraining, setMandatoryTraining] = useState(false);
  const [selected, setSelected] = useState<Map<string, Employee>>(new Map());
  const [search, setSearch] = useState('');
  const [department, setDepartment] = useState('');
  const [activeOnly, setActiveOnly] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [cooldownOpen, setCooldownOpen] = useState(false);
  const [cooldownBlocked, setCooldownBlocked] = useState<CooldownBlockedEmployee[]>([]);
  // A failed launch (e.g. Brevo temporarily blocking the server IP) leaves the
  // campaign as a draft. Reuse it on retry so the operator never accumulates
  // orphan drafts or sends twice.
  const draftIdRef = useRef<string | null>(null);
  const quickSendRef = useRef(false);
  const [launchError, setLaunchError] = useState<string | null>(null);

  function handleQrLogo(file: File | null): void {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setQrLogoError('اختر ملف صورة (PNG أو JPG أو SVG).');
      return;
    }
    if (file.size > 1_500_000) {
      setQrLogoError('حجم الشعار يجب أن يكون أقل من 1.5 ميغابايت.');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setQrLogo(String(reader.result ?? ''));
      setQrLogoError(null);
    };
    reader.onerror = () => setQrLogoError('تعذّر قراءة ملف الشعار.');
    reader.readAsDataURL(file);
  }

  const templateChannel =
    channel === 'qr'
      ? 'qr'
      : channel === 'usb' ||
          channel === 'vishing' ||
          channel === 'pretexting' ||
          channel === 'voice'
        ? 'email'
        : channel;

  const templatesQuery = useQuery({
    queryKey: ['templates', organizationId, templateChannel],
    queryFn: () =>
      templatesApi.list(organizationId as string, {
        is_active: true,
        channel: templateChannel,
      }),
    enabled: Boolean(organizationId),
  });

  const employeesQuery = useQuery({
    queryKey: ['employees', organizationId, 'wizard', search, department, activeOnly],
    queryFn: () =>
      employeesApi.list(organizationId as string, {
        per_page: 200,
        search: search || undefined,
        department: department || undefined,
        is_active: activeOnly ? true : undefined,
      }),
    enabled: Boolean(organizationId),
  });

  // Opening the wizard from an employee dossier carries `?employeeId=…` so the
  // person the operator just selected is already a target. This matches the
  // expected "select an employee → send a simulation" flow and removes a step
  // where the selection could silently be lost.
  const preselectQuery = useQuery({
    queryKey: ['employee', organizationId, preselectId],
    queryFn: () => employeesApi.get(organizationId as string, preselectId as string),
    enabled: Boolean(organizationId && preselectId),
  });

  useEffect(() => {
    const employee = preselectQuery.data;
    if (!employee) return;
    setName((current) => current || `توعية أمنية · ${employee.first_name || employee.email}`);
    setSelected((current) => {
      if (current.has(employee.id)) return current;
      const next = new Map(current);
      next.set(employee.id, employee);
      return next;
    });
  }, [preselectQuery.data]);

  // A dossier "Send simulation" link is a quick-send flow: pick the default
  // template and go straight to review. Without this the operator lands on an
  // empty first step and can mistake the preselection for a completed send.
  useEffect(() => {
    if (!preselectId || templateId) return;
    const firstTemplate = templatesQuery.data?.[0];
    if (firstTemplate) setTemplateId(firstTemplate.id);
  }, [preselectId, templateId, templatesQuery.data]);

  // Physical USB campaigns: assign first active template behind the scenes for API schema validity
  useEffect(() => {
    if (channel !== 'usb' || templateId) return;
    const firstTemplate = templatesQuery.data?.[0];
    if (firstTemplate) setTemplateId(firstTemplate.id);
  }, [channel, templateId, templatesQuery.data]);

  // QR campaigns only offer QR templates; select the first one automatically
  // so the operator sees a valid scenario immediately after switching channel.
  useEffect(() => {
    if (channel !== 'qr' || templateId) return;
    const firstTemplate = templatesQuery.data?.[0];
    if (firstTemplate) setTemplateId(firstTemplate.id);
  }, [channel, templateId, templatesQuery.data]);

  // Keep the QR lure builder in sync with the selected built-in QR template.
  useEffect(() => {
    if (channel !== 'qr' || !templateId) return;
    const template = templatesQuery.data?.find((item) => item.id === templateId);
    const lure = template ? QR_TEMPLATE_LURES[template.name] : undefined;
    if (lure) setQrPretext(lure);
  }, [channel, templateId, templatesQuery.data]);

  useEffect(() => {
    if (!preselectId || quickSendRef.current) return;
    if (!name || !templateId || !preselectQuery.data) return;
    quickSendRef.current = true;
    setStep(2);
  }, [preselectId, name, templateId, preselectQuery.data]);

  // Verify the outbound path before showing "Launch". Email uses Brevo and
  // SMS uses the TextBee gateway. A missing key/device is surfaced before an
  // operator can assume a real send happened.
  const selectedIds = useMemo(() => Array.from(selected.keys()), [selected]);

  const preflightQuery = useQuery({
    queryKey: ['delivery-preflight', channel],
    queryFn: () =>
      channel === 'email'
        ? diagnosticsApi.verifyBrevo()
        : channel === 'voice'
          ? diagnosticsApi.verifyIllyVoIP()
          : diagnosticsApi.verifySms(),
    enabled:
      step === 2 &&
      channel !== 'qr' &&
      channel !== 'usb' &&
      channel !== 'vishing' &&
      channel !== 'pretexting',
    staleTime: 15_000,
    retry: false,
  });

  // Module 3/4 preview: the backend returns the exact blocked payloads so the
  // wizard can warn before a draft is created or a real send starts.
  const cooldownQuery = useQuery({
    queryKey: [
      'campaign-cooldown',
      organizationId,
      selectedIds.join(','),
      mandatoryTraining,
    ],
    queryFn: () =>
      campaignsApi.cooldownCheck(organizationId as string, {
        employee_ids: selectedIds,
        is_mandatory_training: mandatoryTraining,
      }),
    enabled:
      Boolean(organizationId) &&
      step === 2 &&
      selectedIds.length > 0 &&
      channel !== 'qr' &&
      channel !== 'usb',
    staleTime: 10_000,
    retry: false,
  });

  async function handleLaunchRequest(): Promise<void> {
    if (
      channel !== 'qr' &&
      channel !== 'usb' &&
      !mandatoryTraining &&
      selectedIds.length > 0
    ) {
      try {
        const result = await cooldownQuery.refetch();
        const blocked = result.data?.blocked ?? [];
        if (blocked.length > 0) {
          setCooldownBlocked(blocked);
          setCooldownOpen(true);
          return;
        }
      } catch {
        // The launcher still enforces the guardrail server-side; do not block
        // the operator on a failed preview request.
      }
    }
    setConfirmOpen(true);
  }

  const launchMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId) throw new Error('No organization');
      if (channel === 'qr' && !qrCompany.trim()) {
        throw new Error('اسم الشركة مطلوب لإنشاء ملصق QR.');
      }
      if (channel === 'voice' && !voiceRingOnly && !voiceScript.trim()) {
        throw new Error('نص المكالمة الصوتية مطلوب.');
      }
      if (isMessagingChannel && smsMode === 'custom') {
        const trimmed = smsMessage.trim();
        if (!trimmed) throw new Error('اكتب نص الرسالة المخصصة أولاً.');
        if (smsDeliveredLength(trimmed) > SMS_MAX_LENGTH) {
          throw new Error(`نص الرسالة يتجاوز ${SMS_MAX_LENGTH} حرفًا بعد إضافة الرابط.`);
        }
      }
      const targets = (channel === 'qr' || channel === 'usb') ? [] : Array.from(selected.keys());
      const channelConfig = isMessagingChannel
          ? {
              [channel]: {
                custom_message: smsMode === 'custom' ? smsMessage.trim() : '',
                target_department: smsDepartment,
                selected_landing_page:
                  smsLandingPage === 'auto' ? undefined : smsLandingPage,
              },
            }
          : channel === 'qr'
          ? {
              qr: {
                lure_type: qrPretext as QrLureType,
                company_name: qrCompany.trim(),
                department: qrDepartment.trim(),
                month_label: qrPretext === 'nomination' ? qrMonth : '',
                primary_color: qrPrimary,
                accent_color: qrAccent,
                logo_data_url: qrLogo || undefined,
              },
            }
          : channel === 'vishing'
            ? {
                vishing: {
                  caller_name: 'أحمد — الدعم الفني',
                  script:
                    'مرحباً، أنا أحمد من الدعم الفني. لقد لاحظنا اختراقاً في حسابك. هل يمكنك إعطائي الرمز الذي وصلك في رسالة نصية؟',
                },
              }
            : channel === 'pretexting'
              ? {
                  pretexting: {
                    sender_name: 'محمد العتيبي',
                    message:
                      'أحتاج منك شراء 3 بطاقات جوجل بلاي (100$) وإرسال الأكواد هنا فوراً. سأعوضك لاحقاً.',
                  },
                }
              : channel === 'usb'
                ? {
                    usb: {
                      scenario: usbScenario,
                      drop_location: usbDropLocation,
                      volume_label: usbVolumeLabel,
                      // The document names are derived server-side from the
                      // selected template, so a drop never claims to be a
                      // salary statement when the campaign tells another story.
                      drive: usbDrive,
                    },
                  }
                : channel === 'voice'
                  ? {
                      voice: {
                        ...(voiceRingOnly
                          ? { ring_only: true }
                          : {
                              script: voiceScript.trim(),
                              language: 'en-US',
                              voice: 'illyvoip-emma',
                              answer_timeout_seconds: 45,
                            }),
                      },
                    }
                  : undefined;
      let campaignId = draftIdRef.current;
      if (!campaignId) {
        const campaign = await campaignsApi.create(organizationId, {
          name,
          template_id: templateId,
          channel,
          channel_config: channelConfig,
          difficulty_level: difficulty,
          auto_retest_failed: autoRetestFailed,
          is_mandatory_training: mandatoryTraining,
          target_employee_ids: targets,
        });
        campaignId = campaign.id;
        draftIdRef.current = campaign.id;
      } else {
        // Keep the retried draft in sync with the review step.
        await campaignsApi.update(organizationId, campaignId, {
          name,
          template_id: templateId,
          channel,
          channel_config: channelConfig,
          auto_retest_failed: autoRetestFailed,
          is_mandatory_training: mandatoryTraining,
          target_employee_ids: targets,
        });
      }
      return campaignsApi.launch(organizationId, campaignId, channel === 'voice');
    },
    onSuccess: (result) => {
      setConfirmOpen(false);
      setLaunchError(null);
      if (result.queued) {
        toast.success(
          result.message ??
            'تم إرسال حملة المكالمات الحقيقية إلى قائمة الانتظار. سيتولى Celery تنفيذها.',
        );
        navigate(`/campaigns/${result.campaign_id}`);
        return;
      }
      if (result.blocked_count > 0) {
        toast(
          `تم تخطي ${result.blocked_count} موظفاً بسبب فترة التهدئة أو قائمة الفشل المتكرر.`,
          { icon: '⚠️' },
        );
      }
      if (
        channel === 'qr' ||
        channel === 'usb' ||
        channel === 'vishing' ||
        channel === 'pretexting'
      ) {
        const unit =
          channel === 'usb'
            ? 'مستند USB'
            : channel === 'qr'
              ? 'ملصق QR'
              : 'رابط محاكاة';
        if (result.failed > 0) {
          toast.error(`تم تجهيز ${result.sent} من ${result.total} ${unit}؛ فشل ${result.failed}.`);
        } else if (channel === 'usb') {
          // Copy the generated documents onto the chosen stick automatically:
          // the operator never runs a script or downloads files by hand.
          if (usbDrive) {
            void campaignsApi
              .deployUsbArtifacts(result.campaign_id, usbDrive)
              .then((copy) => {
                toast.success(
                  `تم نسخ ${copy.files.length} ملف إلى ${copy.drive} — الفلاشة جاهزة للاختبار الميداني.`,
                );
              })
              .catch((error: unknown) => {
                toast.error(
                  `تم إنشاء الحملة، لكن فشل النسخ إلى ${usbDrive}: ${errorMessage(error)}`,
                );
              });
          } else {
            toast.success(
              `تم تجهيز ${result.total} مستند USB. اختر فلاشة في الخطوة السابقة لنسخها تلقائيًا.`,
            );
          }
        } else if (channel === 'qr') {
          setLaunchedQrId(result.campaign_id);
          toast.success('تم إطلاق حملة QR بنجاح! جاهزة لتحميل الملصق.');
          return;
        } else {
          toast.success(
            `تم تجهيز ${result.total} ${unit}. افتح صفحة الحملة لعرض الروابط وتعليمات التسليم.`,
          );
        }
        navigate(`/campaigns/${result.campaign_id}`);
        return;
      }
      if (result.failed > 0) {
        toast.error(`أُرسل ${result.sent} من ${result.total}؛ فشل ${result.failed}.`);
      } else {
        toast.success(`أُرسل ${result.sent} من ${result.total} رسالة. المراقبة الحية جاهزة.`);
      }
      navigate(`/campaigns/${result.campaign_id}/live`);
    },
    onError: (error) => {
      setConfirmOpen(false);
      const message = errorMessage(error);
      setLaunchError(message);
      toast.error(message);
    },
  });

  const visibleEmployees = useMemo(
    () => employeesQuery.data?.items ?? [],
    [employeesQuery.data],
  );

  const isQrChannel = channel === 'qr';
  const isUsbChannel = channel === 'usb';
  const isVishingChannel = channel === 'vishing';
  const isPretextingChannel = channel === 'pretexting';
  const isVoiceChannel = channel === 'voice';
  const isManualChannel =
    isQrChannel || isUsbChannel || isVishingChannel || isPretextingChannel;
  const isPhoneChannel =
    channel === 'sms' || channel === 'whatsapp' || channel === 'voice';
  // SMS and WhatsApp share the same composer: a template body or a custom
  // message with a {{link}} placeholder, capped at one 170-character screen.
  const isMessagingChannel = channel === 'sms' || channel === 'whatsapp';

  function isSelectable(employee: Employee): boolean {
    return !isPhoneChannel || hasValidPhone(employee.phone);
  }

  // USB drives are read straight from the machine running this console, so the
  // operator picks the stick here and the files are copied automatically on
  // launch — no companion agent, no manual script.
  async function loadUsbDrives() {
    setUsbDrivesLoading(true);
    try {
      const res = await campaignsApi.usbDrives();
      const removable = (res.drives || []).filter((item) => item.is_removable && item.writable);
      setUsbDriveList(removable);
      setUsbDrive((current) =>
        current && removable.some((item) => item.drive === current)
          ? current
          : removable[0]?.drive ?? '',
      );
    } catch {
      setUsbDriveList([]);
    } finally {
      setUsbDrivesLoading(false);
    }
  }

  useEffect(() => {
    if (!isUsbChannel) return;
    void loadUsbDrives();
    const timer = setInterval(() => void loadUsbDrives(), 5000);
    return () => clearInterval(timer);
  }, [isUsbChannel]);

  // Switching to a phone channel must immediately remove any target that has
  // no number instead of letting the review step hide an invalid recipient.
  useEffect(() => {
    if (!isPhoneChannel) return;
    setSelected((current) => {
      const next = new Map(
        Array.from(current.entries()).filter(([, employee]) => hasValidPhone(employee.phone)),
      );
      return next.size === current.size ? current : next;
    });
  }, [isPhoneChannel]);

  const selectableVisible = useMemo(
    () => visibleEmployees.filter((employee) => isSelectable(employee)),
    // ``isSelectable`` is derived from isPhoneChannel and the employee list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [visibleEmployees, isPhoneChannel],
  );

  // Departments come from the backend so the filter lists every department in
  // the organization, not just the ones on the current page.
  const departmentsQuery = useQuery({
    queryKey: ['departments', organizationId],
    queryFn: () => employeesApi.departments(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const departments = useMemo(() => {
    const serverRows = departmentsQuery.data;
    if (serverRows && serverRows.length > 0) {
      return serverRows.map((row) => [row.department, row.count] as [string, number]);
    }
    const counts = new Map<string, number>();
    visibleEmployees.forEach((employee) => {
      if (!employee.department) return;
      counts.set(employee.department, (counts.get(employee.department) ?? 0) + 1);
    });
    return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [departmentsQuery.data, visibleEmployees]);

  const selectedTemplate = templatesQuery.data?.find((template) => template.id === templateId);
  const allVisibleSelected =
    selectableVisible.length > 0 &&
    selectableVisible.every((employee) => selected.has(employee.id));

  function toggleEmployee(employee: Employee) {
    if (!isSelectable(employee)) return;
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(employee.id)) next.delete(employee.id);
      else next.set(employee.id, employee);
      return next;
    });
  }

  function selectAllVisible() {
    setSelected((current) => {
      const next = new Map(current);
      selectableVisible.forEach((employee) => next.set(employee.id, employee));
      return next;
    });
  }

  function clearAll() {
    setSelected(new Map());
  }

  function removeSelected(id: string) {
    setSelected((current) => {
      const next = new Map(current);
      next.delete(id);
      return next;
    });
  }

  const smsCustomInvalid =
    isMessagingChannel &&
    smsMode === 'custom' &&
    (smsMessage.trim().length === 0 || smsDeliveredLength(smsMessage) > SMS_MAX_LENGTH);
  const canLeaveStepOne =
    name.trim().length > 0 &&
    (channel === 'usb' || templateId.length > 0) &&
    (!isVoiceChannel || voiceScript.trim().length > 0) &&
    !smsCustomInvalid;
  const selectedList = Array.from(selected.values());
  const selectedPhonesValid =
    !isPhoneChannel || selectedList.every((employee) => hasValidPhone(employee.phone));
  const canLeaveStepTwo = selected.size > 0 && selectedPhonesValid;
  const invalidPhoneCount = visibleEmployees.filter(
    (employee) => !hasValidPhone(employee.phone),
  ).length;
  const channelNoun = isQrChannel
    ? 'ملصق QR'
    : isUsbChannel
      ? 'مستند USB'
      : isVishingChannel
        ? 'مكالمة Vishing'
        : isPretextingChannel
          ? 'محادثة CEO'
          : isVoiceChannel
            ? 'مكالمة صوتية حقيقية'
            : channel === 'email'
              ? 'رسالة بريد إلكتروني'
              : channel === 'sms'
                ? 'رسالة SMS'
                : 'رسالة واتساب';
  const providerName = isQrChannel
    ? 'الطباعة اليدوية'
    : isUsbChannel
      ? 'التوزيع اليدوي'
      : isVishingChannel || isPretextingChannel
        ? 'التسليم اليدوي للرابط'
        : isVoiceChannel
          ? 'IllyVoIP Voice API'
          : channel === 'email'
            ? 'Brevo/SMTP'
            : channel === 'sms'
              ? 'TextBee SMS Gateway'
              : channel === 'whatsapp'
                ? 'WA-AKG WhatsApp Gateway'
                : 'غير متاح';
  const preflightBlocked =
    !isManualChannel && Boolean(preflightQuery.data && !preflightQuery.data.valid);

  return (
    <>
      <PageHeader
        title="حملة جديدة"
        subtitle="ثلاث خطوات: التفاصيل، تحديد المستهدفين، ثم مراجعة الإطلاق."
      />

      <Box
        sx={{
          mb: 3,
          p: { xs: 1.5, sm: 2 },
          borderRadius: 4,
          border: '1px solid rgba(0,240,255,.14)',
          background:
            'radial-gradient(circle at 50% 0%, rgba(0,240,255,.10), transparent 55%), linear-gradient(145deg, rgba(21,32,52,.82), rgba(9,15,26,.86))',
          boxShadow: '0 18px 50px rgba(0,0,0,.25)',
        }}
      >
        <Stepper
          alternativeLabel
          activeStep={(isQrChannel || isUsbChannel) ? (step === 2 ? 1 : 0) : step}
          sx={{
            '& .MuiStepLabel-label': { fontWeight: 700, mt: 0.5 },
            '& .MuiStepIcon-root': { color: 'rgba(255,255,255,.10)' },
            '& .MuiStepIcon-root.Mui-active': {
              color: 'primary.main',
              filter: 'drop-shadow(0 0 10px rgba(0,240,255,.85))',
            },
            '& .MuiStepIcon-root.Mui-completed': {
              color: 'success.main',
              filter: 'drop-shadow(0 0 8px rgba(0,230,118,.55))',
            },
            '& .MuiStepConnector-line': { borderColor: 'rgba(255,255,255,.12)' },
          }}
        >
          {(isQrChannel ? QR_STEPS : isUsbChannel ? USB_STEPS : STEPS).map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
      </Box>

      {step === 0 ? (
        <Card>
          <CardContent>
            <Stack spacing={3}>
              <TextField
                label="اسم الحملة"
                required
                fullWidth
                value={name}
                onChange={(event) => setName(event.target.value)}
                helperText="اسم داخلي — لا يظهر للمستهدفين أبداً."
              />
              <TextField
                select
                label="قناة الإرسال"
                value={channel}
                fullWidth
                onChange={(event) => {
                  const nextChannel = event.target.value as WizardChannel;
                  setChannel(nextChannel);
                  setTemplateId('');
                }}
                helperText={
                  isQrChannel
                    ? 'حملة QR لا ترسل رسائل: بعد الإطلاق تُنزّل ملصقاً واحداً (PDF) يحمل رمز QR عاماً للحملة. اطبع نسخة واحدة وعلّقها في الموقع المستهدف. القالب يُستخدم كمرجع للطُعم فقط.'
                    : isUsbChannel
                      ? 'حملة USB الفيزيائية: اختر سيناريو الطُعم وموقع الإسقاط، ثم اضغط إطلاق الحملة لتجهيز وحرق الفلاشات مباشرة عبر محطة التجهيز الميدانية.'
                      : isVishingChannel || isPretextingChannel
                        ? 'هذه قناة محاكاة يدوية: لا تُرسل مكالمة أو رسالة حقيقية. بعد الإطلاق تنسخ رابط المحاكاة الفريد لكل موظف من صفحة الحملة. القالب يُستخدم كمرجع للسيناريو فقط.'
                        : isVoiceChannel
                          ? 'مكالمة هاتفية حقيقية عبر IllyVoIP Voice API مع تحويل النص إلى كلام أصلي. تتطلب مفتاح API وSIP User ID وCaller ID صالحة، ويجب أن يكون الرقم بصيغة E.164. تُنفَّذ الحملة في Celery ولا تُجرى أي مكالمة أثناء الاختبارات.'
                          : channel === 'whatsapp'
                            ? 'الواتساب يُرسل عبر بوابة WA-AKG (جلسة WhatsApp Web مرتبطة بجوال مخصص). امسح رمز QR مرة واحدة من لوحة WA-AKG، ثم ضع المفتاح ورقم الجلسة في backend/.env. أرقام الهاتف بصيغة E.164 مثل +966500000000.'
                            : 'البريد الإلكتروني يُرسل عبر Brevo، والـ SMS عبر بوابة TextBee (الجوال المسجّل). أرقام الهاتف يجب أن تكون بصيغة E.164 مثل +966500000000.'
                }
              >
                <MenuItem value="email">البريد الإلكتروني</MenuItem>
                <MenuItem value="sms">SMS — Smishing (TextBee)</MenuItem>
                <MenuItem value="whatsapp">WhatsApp — Smishing (WA-AKG)</MenuItem>
                <MenuItem value="qr">رمز QR — Quishing</MenuItem>
                <MenuItem value="vishing">مكالمة صوتية — Vishing (رابط يدوي)</MenuItem>
                <MenuItem value="pretexting">محادثة CEO — Pretexting</MenuItem>
                <MenuItem value="usb">فلاشة USB — HTML/PDF توعوي</MenuItem>
                <MenuItem value="voice">مكالمة صوتية حقيقية — IllyVoIP</MenuItem>
              </TextField>

              {isVishingChannel || isPretextingChannel ? (
                <Alert severity="info">
                  {isVishingChannel
                    ? 'ستُجهّز صفحة مكالمة واردة تحاكي الدعم الفني، مع تحويل النص إلى كلام في المتصفح. لا تُجرى أي مكالمة هاتفية حقيقية ولا يُطلب رمز حقيقي.'
                    : 'ستُجهّز محادثة واتساب/Teams تحاكي الرئيس التنفيذي وتُعرض رسالتا الطلب تلقائياً. لا تُرسل أي أموال أو رسائل حقيقية.'}
                </Alert>
              ) : null}
              {isVoiceChannel ? (
                <Stack spacing={1.5}>
                  <Alert severity="warning">
                    هذه القناة تُجري مكالمات هاتفية حقيقية عبر IllyVoIP. استخدمها فقط
                    لموظفيك المصرّح لهم أو لأرقام اختبار مملوكة للمؤسسة. لا يوجد وضع
                    محاكاة، وأي خطأ في النص أو الرقم يُستهلك من رصيد المكالمات.
                  </Alert>
                  <Alert severity="info">
                    كتالوج TTS في Voice API يدعم حالياً <code>en-US</code> فقط. اكتب
                    النص بالإنجليزية، بحد أقصى 2,000 حرف. النص العربي سيُرفض من المزوّد.
                  </Alert>
                  <FormControlLabel
                    control={
                      <Switch
                        checked={voiceRingOnly}
                        onChange={(event) => setVoiceRingOnly(event.target.checked)}
                      />
                    }
                    label="رنة تحقق فقط — Ring only (no audio, no TTS credit)"
                  />
                  {voiceRingOnly ? (
                    <Alert severity="info">
                      سيُطلب الرقم ثم تُقطع المكالمة لحظة أول رنة. لا صوت ولا نص ولا استهلاك
                      لرصيد TTS — تُستخدم لإثبات القناة ووصول الرقم فقط.
                    </Alert>
                  ) : (
                    <TextField
                      label="نص المكالمة — Native TTS script"
                      required
                      fullWidth
                      multiline
                      minRows={4}
                      value={voiceScript}
                      onChange={(event) => setVoiceScript(event.target.value)}
                      inputProps={{ maxLength: 2000 }}
                      helperText={`${voiceScript.length}/2000 حرف — يُقرأ بصوت IllyVoIP الأصلي.`}
                      dir="ltr"
                    />
                  )}
                </Stack>
              ) : null}
              {isQrChannel ? (
                <Box
                  sx={{
                    p: 2,
                    borderRadius: 2,
                    border: '1px solid',
                    borderColor: 'divider',
                    bgcolor: 'action.hover',
                  }}
                >
                  <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 1.5 }}>
                    إعداد الطُعم — Lure Builder
                  </Typography>
                  <Stack spacing={1.8}>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                      <TextField
                        required
                        fullWidth
                        size="small"
                        label="اسم الشركة"
                        value={qrCompany}
                        onChange={(event) => setQrCompany(event.target.value)}
                        placeholder="مثال: شركة النور للتجارة"
                      />
                      <TextField
                        fullWidth
                        size="small"
                        label="القسم المستهدف (اختياري)"
                        value={qrDepartment}
                        onChange={(event) => setQrDepartment(event.target.value)}
                        placeholder="مثال: الموارد البشرية"
                      />
                    </Stack>
                    <TextField
                      select
                      required
                      fullWidth
                      size="small"
                      label="نوع الطُعم — Lure Type"
                      value={qrPretext}
                      onChange={(event) => setQrPretext(event.target.value)}
                      helperText={
                        QR_LURES.find((lure) => lure.value === qrPretext)?.hint ??
                        'اختر القصة التي ستظهر على الملصق المطبوع.'
                      }
                    >
                      {QR_LURES.map((lure) => (
                        <MenuItem key={lure.value} value={lure.value}>
                          {lure.label}
                        </MenuItem>
                      ))}
                    </TextField>
                    {qrPretext === 'nomination' ? (
                      <TextField
                        required
                        fullWidth
                        size="small"
                        type="month"
                        label="شهر الترشيح"
                        value={qrMonth}
                        onChange={(event) => setQrMonth(event.target.value)}
                        InputLabelProps={{ shrink: true }}
                        helperText="يظهر الشهر على الملصق وفي صفحة الترشيح."
                      />
                    ) : null}
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                      <TextField
                        fullWidth
                        size="small"
                        type="color"
                        label="اللون الأساسي"
                        value={qrPrimary}
                        onChange={(event) => setQrPrimary(event.target.value)}
                        InputLabelProps={{ shrink: true }}
                      />
                      <TextField
                        fullWidth
                        size="small"
                        type="color"
                        label="اللون الثانوي"
                        value={qrAccent}
                        onChange={(event) => setQrAccent(event.target.value)}
                        InputLabelProps={{ shrink: true }}
                      />
                    </Stack>
                    <Box
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={(event) => {
                        event.preventDefault();
                        handleQrLogo(event.dataTransfer.files?.[0] ?? null);
                      }}
                      sx={{
                        p: 2,
                        borderRadius: 2,
                        border: '1px dashed',
                        borderColor: 'divider',
                        textAlign: 'center',
                        cursor: 'pointer',
                      }}
                      component="label"
                    >
                      <input
                        hidden
                        type="file"
                        accept="image/png,image/jpeg,image/svg+xml,image/webp"
                        onChange={(event) => handleQrLogo(event.target.files?.[0] ?? null)}
                      />
                      {qrLogo ? (
                        <Stack spacing={1} alignItems="center">
                          <Box
                            component="img"
                            src={qrLogo}
                            alt="شعار الشركة"
                            sx={{ maxHeight: 64, maxWidth: 180, objectFit: 'contain' }}
                          />
                          <Button
                            size="small"
                            color="error"
                            onClick={(event) => {
                              event.preventDefault();
                              setQrLogo('');
                            }}
                          >
                            إزالة الشعار
                          </Button>
                        </Stack>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          اسحب شعار الشركة هنا أو اضغط للاختيار (PNG / JPG / SVG — حتى 1.5MB)
                        </Typography>
                      )}
                    </Box>
                    {qrLogoError ? <Alert severity="error">{qrLogoError}</Alert> : null}
                  </Stack>
                </Box>
              ) : null}
              {isUsbChannel ? (
                <Box
                  sx={{
                    p: 2.5,
                    borderRadius: 2,
                    border: '1px solid rgba(0,240,255,0.25)',
                    bgcolor: 'action.hover',
                  }}
                >
                  <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 1.5 }}>
                    <Box
                      sx={{
                        width: 36,
                        height: 36,
                        borderRadius: 1.5,
                        bgcolor: 'primary.dark',
                        color: 'primary.contrastText',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <span style={{ fontSize: '1.2rem' }}>💾</span>
                    </Box>
                    <div>
                      <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
                        إعداد طُعم فلاشة الـ USB وسيناريو الإسقاط الفيزيائي (Physical Lure Builder)
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        الحملة فيزيائية عامة (Physical Baiting) تستهدف أي موظف يلتقط الفلاشة ويقوم بتشغيلها
                      </Typography>
                    </div>
                  </Stack>

                  <Stack spacing={2}>
                    <TextField
                      select
                      fullWidth
                      size="small"
                      label="سيناريو الطُعم والملفات المموهة (Bait Persona)"
                      value={usbScenario}
                      onChange={(e) => {
                        const val = e.target.value;
                        setUsbScenario(val);
                        const sc = USB_SCENARIOS.find((s) => s.id === val);
                        if (sc) setUsbVolumeLabel(sc.volume);
                      }}
                      helperText={USB_SCENARIOS.find((s) => s.id === usbScenario)?.description}
                    >
                      {USB_SCENARIOS.map((sc) => (
                        <MenuItem key={sc.id} value={sc.id}>
                          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" sx={{ width: '100%' }}>
                            <span>{sc.title}</span>
                            <Chip label={sc.badge} size="small" color="primary" variant="outlined" sx={{ height: 20, fontSize: '0.7rem' }} />
                          </Stack>
                        </MenuItem>
                      ))}
                    </TextField>

                    <TextField
                      select
                      fullWidth
                      size="small"
                      label="موقع الإسقاط الفيزيائي المستهدف (Drop Zone Location)"
                      value={usbDropLocation}
                      onChange={(e) => setUsbDropLocation(e.target.value)}
                      helperText="الموقع الذي سيتم ترك أو إسقاط الفلاشة فيه داخل مقر الشركة"
                    >
                      {USB_DROP_LOCATIONS.map((loc) => (
                        <MenuItem key={loc} value={loc}>
                          {loc}
                        </MenuItem>
                      ))}
                    </TextField>

                    <TextField
                      fullWidth
                      size="small"
                      label="تسمية الفلاشة (USB Volume Label)"
                      value={usbVolumeLabel}
                      onChange={(e) => setUsbVolumeLabel(e.target.value)}
                      helperText="الاسم الذي سيظهر في مستكشف الملفات (Windows Explorer) عند إدخال الفلاشة في الكمبيوتر"
                    />

                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems="flex-start">
                      <TextField
                        select
                        fullWidth
                        size="small"
                        label="الفلاشة التي ستُنقل إليها الملفات"
                        value={usbDrive}
                        onChange={(e) => setUsbDrive(e.target.value)}
                        disabled={usbDrivesLoading || usbDriveList.length === 0}
                        helperText={
                          usbDriveList.length
                            ? 'تُكتشف تلقائيًا من هذا الجهاز، وتُنسخ الملفات فور إطلاق الحملة'
                            : usbDrivesLoading
                              ? 'جاري فحص الأقراص المتصلة...'
                              : 'لم يتم العثور على فلاشة. أدخل الفلاشة وستظهر هنا خلال ثوانٍ'
                        }
                      >
                        {usbDriveList.map((item) => (
                          <MenuItem key={item.drive} value={item.drive}>
                            {`${item.drive}${item.label ? ` — ${item.label}` : ''} · ${item.free_gb} GB متاح`}
                          </MenuItem>
                        ))}
                      </TextField>
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={() => void loadUsbDrives()}
                        disabled={usbDrivesLoading}
                        sx={{ mt: 0.5, whiteSpace: 'nowrap' }}
                      >
                        تحديث الأقراص
                      </Button>
                    </Stack>
                  </Stack>
                </Box>
              ) : null}

              {isMessagingChannel ? (
                <Box
                  sx={{
                    p: 2,
                    borderRadius: 2,
                    border: '1px solid',
                    borderColor: smsMode === 'custom' && smsCustomInvalid ? 'error.main' : 'divider',
                    bgcolor: 'action.hover',
                  }}
                >
                  <Stack spacing={2}>
                    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
                      <Button
                        variant={smsMode === 'template' ? 'contained' : 'outlined'}
                        onClick={() => setSmsMode('template')}
                      >
                        استخدام قالب
                      </Button>
                      <Button
                        variant={smsMode === 'custom' ? 'contained' : 'outlined'}
                        onClick={() => setSmsMode('custom')}
                      >
                        كتابة رسالة مخصصة
                      </Button>
                    </Stack>

                    {smsMode === 'custom' ? (
                      <>
                        <TextField
                          label="نص الرسالة المخصصة"
                          multiline
                          minRows={4}
                          fullWidth
                          value={smsMessage}
                          onChange={(event) => setSmsMessage(event.target.value)}
                          error={smsCustomInvalid}
                          dir="ltr"
                          placeholder="Your VPN session expires today. Please re-authenticate here: {{link}}"
                          helperText={`${smsDeliveredLength(smsMessage)}/${SMS_MAX_LENGTH} حرفًا — استخدم {{link}} لمكان الرابط القصير؛ يُحسب بطول 24 حرفًا.`}
                        />
                        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                          <TextField
                            select
                            fullWidth
                            size="small"
                            label="القسم المستهدف"
                            value={smsDepartment}
                            onChange={(event) => setSmsDepartment(event.target.value)}
                            helperText="للعرض والصياغة؛ التوجيه النهائي يعتمد على قسم الموظف."
                          >
                            {SMS_DEPARTMENTS.map((option) => (
                              <MenuItem key={option.value} value={option.value}>
                                {option.label}
                              </MenuItem>
                            ))}
                          </TextField>
                          <TextField
                            select
                            fullWidth
                            size="small"
                            label="صفحة الهبوط"
                            value={smsLandingPage}
                            onChange={(event) => setSmsLandingPage(event.target.value)}
                          >
                            {SMS_LANDING_PAGES.map((option) => (
                              <MenuItem key={option.value} value={option.value}>
                                {option.label}
                              </MenuItem>
                            ))}
                          </TextField>
                        </Stack>
                        <Alert severity={smsCustomInvalid ? 'error' : 'info'}>
                          {smsLandingPage === 'auto'
                            ? `التوجيه التلقائي: ${
                                SMS_LANDING_PAGES.find(
                                  (option) =>
                                    option.value === (detectSmsLandingPage(smsMessage) ?? 'general_login'),
                                )?.label ?? 'general_login'
                              }`
                            : 'اختيار يدوي لصفحة الهبوط — يتجاوزه قسم الموظف عند الإطلاق (IT→VPN، Finance→Supplier، HR→HR، Executive→Teams).'}
                        </Alert>
                      </>
                    ) : (
                      <Alert severity="info">
                        سيُرسل نص القالب المختار أدناه مع رابط قصير مخصص لكل مستهدف، مع فاصل عشوائي 10–30 ثانية بين الرسائل لتقليل خطر الحظر.
                      </Alert>
                    )}
                  </Stack>
                </Box>
              ) : null}

              {!isUsbChannel ? (
              <TextField
                select
                label="القالب"
                required
                fullWidth
                value={templateId}
                onChange={(event) => {
                  const nextId = event.target.value as string;
                  setTemplateId(nextId);
                  const template = templatesQuery.data?.find((item) => item.id === nextId);
                  if (template) {
                    setDifficulty(template.difficulty_level);
                    const lure = QR_TEMPLATE_LURES[template.name];
                    if (lure) setQrPretext(lure);
                  }
                }}
                disabled={templatesQuery.isLoading}
                helperText={
                  templatesQuery.data && templatesQuery.data.length === 0
                    ? isManualChannel
                      ? 'لا توجد قوالب بريد نشطة — القنوات اليدوية تحتاج قالباً نشطاً كمرجع للسيناريو. أنشئ قالباً أولاً.'
                      : channel === 'email'
                        ? 'لا توجد قوالب بريد نشطة — أنشئ قالباً من صفحة القوالب أولاً.'
                        : `لا توجد قوالب ${channel === 'sms' ? 'SMS' : 'واتساب'} نشطة — أنشئ قالباً من صفحة القوالب واختر القناة الصحيحة.`
                    : channel === 'qr'
                      ? 'قالب QR يُستخدم كمرجع للطُعم والسيناريو فقط؛ لا تُرسل أي رسالة.'
                      : isManualChannel
                        ? 'قالب البريد يُستخدم كمرجع للسيناريو فقط؛ لا تُرسل أي رسالة بريد في هذه الحملة.'
                        : 'القالب يحدد قصة المرسل والموضوع ونص الرسالة.'
                }
              >
                {(templatesQuery.data ?? []).map((template) => (
                  <MenuItem key={template.id} value={template.id}>
                    {template.name} (L{template.difficulty_level})
                  </MenuItem>
                ))}
              </TextField>

              ) : null}

              {selectedTemplate && !isUsbChannel ? (
                <Card variant="outlined">
                  <CardContent>
                    <Stack
                      direction={{ xs: 'column', sm: 'row' }}
                      justifyContent="space-between"
                      alignItems={{ xs: 'flex-start', sm: 'center' }}
                      spacing={1}
                      sx={{ mb: 1 }}
                    >
                      <Box>
                        <Typography variant="subtitle2">معاينة القالب</Typography>
                        <Typography variant="body2" color="text.secondary">
                          الموضوع: {selectedTemplate.subject}
                        </Typography>
                      </Box>
                      <Stack direction="row" spacing={1}>
                        <Chip size="small" label={`الصعوبة ${selectedTemplate.difficulty_level}`} />
                        {selectedTemplate.is_built_in ? (
                          <Chip size="small" variant="outlined" label="أساسي" />
                        ) : null}
                      </Stack>
                    </Stack>
                    <Box
                      component="iframe"
                      title="Template preview"
                      sandbox=""
                      srcDoc={selectedTemplate.body_html}
                      sx={{
                        width: '100%',
                        height: 300,
                        border: '1px solid',
                        borderColor: 'divider',
                        borderRadius: 1,
                        bgcolor: '#ffffff',
                      }}
                    />
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                      المتغيرات المستخدمة:{' '}
                      {selectedTemplate.available_variables.length > 0
                        ? selectedTemplate.available_variables.join(', ')
                        : 'لا يوجد'}
                    </Typography>
                  </CardContent>
                </Card>
              ) : null}

              <Box>
                <Typography variant="body2" gutterBottom>
                  مستوى الصعوبة: {difficulty} — {difficultyLabel(difficulty)}
                </Typography>
                <Slider
                  value={difficulty}
                  min={1}
                  max={10}
                  step={1}
                  marks
                  onChange={(_event, value) => setDifficulty(value as number)}
                />
              </Box>

              <Box
                sx={{
                  p: 2,
                  borderRadius: 2,
                  border: '1px solid',
                  borderColor: 'divider',
                  bgcolor: 'action.hover',
                }}
              >
                <FormControlLabel
                  control={
                    <Switch
                      checked={autoRetestFailed}
                      onChange={(event) => setAutoRetestFailed(event.target.checked)}
                      color="primary"
                    />
                  }
                  label={
                    <Box sx={{ ml: 1 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: '0.92rem' }}>
                        إعادة الاختبار التلقائي للموظفين غير المجتازين (Auto-Retest Failed Employees)
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                        تشغيل حملة تنقيط تلقائية بعد 72 ساعة من انتهاء الحملة تستهدف الموظفين الذين فشلوا (نقروا أو أدخلوا بياناتهم أو تجاهلوا الرسالة) بقالب أعلى صعوبة.
                      </Typography>
                    </Box>
                  }
                />
              </Box>

              <Box
                sx={{
                  p: 2,
                  borderRadius: 2,
                  border: '1px dashed',
                  borderColor: 'error.light',
                  bgcolor: 'rgba(220,38,38,.04)',
                }}
              >
                <FormControlLabel
                  control={
                    <Switch
                      checked={mandatoryTraining}
                      onChange={(event) => setMandatoryTraining(event.target.checked)}
                      color="error"
                    />
                  }
                  label={
                    <Box sx={{ ml: 1 }}>
                      <Typography sx={{ fontWeight: 700, fontSize: '0.92rem' }}>
                        حملة تدريب إلزامي (Mandatory Training)
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                        تتجاوز فترة التهدئة وقائمة الفشل المتكرر. استخدمها فقط لإجبار
                        الموظفين عالي الخطورة على إعادة التدريب.
                      </Typography>
                    </Box>
                  }
                />
              </Box>

              <Stack direction="row" justifyContent="flex-end">
                <Button
                  variant="contained"
                  disabled={!canLeaveStepOne}
                  onClick={() => setStep((isQrChannel || isUsbChannel) ? 2 : 1)}
                >
                  {isQrChannel ? 'متابعة إلى مراجعة الحملة وإطلاقها' : isUsbChannel ? 'متابعة إلى مراجعة الحملة الفيزيائية' : 'متابعة إلى المستهدفين'}
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {step === 1 && !isQrChannel && !isUsbChannel ? (
        <Card>
          <CardContent>
            <Stack spacing={2}>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="center">
                <TextField
                  label="بحث بالاسم أو البريد"
                  size="small"
                  fullWidth
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <TextField
                  select
                  label="القسم"
                  size="small"
                  sx={{ minWidth: 220 }}
                  value={department}
                  onChange={(event) => setDepartment(event.target.value)}
                >
                  <MenuItem value="">كل الأقسام</MenuItem>
                  {departments.map(([value, count]) => (
                    <MenuItem key={value} value={value}>
                      {value} ({count})
                    </MenuItem>
                  ))}
                </TextField>
                <FormControlLabel
                  control={
                    <Switch
                      checked={activeOnly}
                      onChange={(event) => setActiveOnly(event.target.checked)}
                    />
                  }
                  label="الحسابات النشطة فقط"
                />
              </Stack>

              {isPhoneChannel && invalidPhoneCount > 0 ? (
                <Alert severity="info">
                  {invalidPhoneCount} موظفاً في النتائج الحالية بلا رقم هاتف صالح بصيغة E.164؛
                  تم تعطيل تحديدهم لأن قنوات SMS وواتساب تتطلب رقماً دولياً مثل
                  +966500000000. صحّح الرقم من صفحة الموظفين ثم أعد المحاولة.
                </Alert>
              ) : null}

              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                spacing={1}
                alignItems={{ xs: 'stretch', sm: 'center' }}
              >
                <Button size="small" variant="outlined" onClick={selectAllVisible} disabled={selectableVisible.length === 0}>
                  {allVisibleSelected
                    ? 'كل النتائج القابلة للإرسال محددة مسبقاً'
                    : `تحديد كل النتائج (${selectableVisible.length})`}
                </Button>
                <Button size="small" onClick={clearAll} disabled={selected.size === 0}>
                  مسح الكل
                </Button>
                <Box sx={{ flex: 1 }} />
                <Chip color="primary" label={`${selected.size} موظفاً محدداً`} />
              </Stack>

              {selected.size > 0 ? (
                <Box
                  sx={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 1,
                    p: 1.5,
                    borderRadius: 1,
                    bgcolor: 'action.hover',
                  }}
                >
                  {selectedList.slice(0, 40).map((employee) => (
                    <Chip
                      key={employee.id}
                      size="small"
                      label={`${employee.first_name} ${employee.last_name}`.trim() || employee.email}
                      onDelete={() => removeSelected(employee.id)}
                      deleteIcon={<CloseIcon />}
                    />
                  ))}
                  {selected.size > 40 ? (
                    <Chip size="small" variant="outlined" label={`+${selected.size - 40} آخرون`} />
                  ) : null}
                </Box>
              ) : null}

              {employeesQuery.isLoading ? (
                <LoadingState label="جارٍ تحميل الموظفين…" />
              ) : (
                <TableContainer sx={{ maxHeight: 440 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell padding="checkbox">تحديد</TableCell>
                        <TableCell>الاسم</TableCell>
                        <TableCell>البريد</TableCell>
                        {isPhoneChannel ? <TableCell>الهاتف (E.164)</TableCell> : null}
                        <TableCell>القسم</TableCell>
                        <TableCell align="center">مستوى الوصول</TableCell>
                        <TableCell>آخر اختبار</TableCell>
                        <TableCell align="center">المناعة</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {visibleEmployees.map((employee) => (
                        <TableRow
                          key={employee.id}
                          hover={isSelectable(employee)}
                          onClick={() => toggleEmployee(employee)}
                          sx={{
                            cursor: isSelectable(employee) ? 'pointer' : 'not-allowed',
                            opacity: isSelectable(employee) ? 1 : 0.55,
                          }}
                          selected={selected.has(employee.id)}
                        >
                          <TableCell padding="checkbox">
                            <Tooltip
                              title={
                                isSelectable(employee)
                                  ? ''
                                  : employee.phone?.trim()
                                    ? 'رقم الهاتف ليس بصيغة E.164 — صحّحه من ملف الموظف'
                                    : 'أضف رقم هاتف بصيغة E.164 من ملف الموظف أولاً'
                              }
                            >
                              <span>
                                <Checkbox
                                  checked={selected.has(employee.id)}
                                  disabled={!isSelectable(employee)}
                                  onClick={(event) => event.stopPropagation()}
                                  onChange={() => toggleEmployee(employee)}
                                />
                              </span>
                            </Tooltip>
                          </TableCell>
                          <TableCell>
                            {employee.first_name} {employee.last_name}
                          </TableCell>
                          <TableCell>{employee.email}</TableCell>
                          {isPhoneChannel ? (
                            <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                              {employee.phone?.trim() ? employee.phone : 'لا يوجد رقم'}
                            </TableCell>
                          ) : null}
                          <TableCell>{employee.department ?? '—'}</TableCell>
                          <TableCell align="center">{employee.access_level}</TableCell>
                          <TableCell>
                            {employee.last_test_date
                              ? formatDateTime(employee.last_test_date)
                              : 'لم يُختبر'}
                          </TableCell>
                          <TableCell align="center">{employee.immunity_score.toFixed(1)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}

              <Box
                sx={{
                  position: 'sticky',
                  bottom: 16,
                  zIndex: 3,
                  mt: 1,
                  p: 1.5,
                  borderRadius: 3,
                  border: '1px solid rgba(0,240,255,.22)',
                  background: 'linear-gradient(135deg, rgba(19,29,48,.96), rgba(10,16,28,.96))',
                  backdropFilter: 'blur(18px)',
                  boxShadow: '0 24px 60px rgba(0,0,0,.55), 0 0 32px rgba(0,240,255,.08)',
                }}
              >
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ xs: 'stretch', sm: 'center' }}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Box
                      sx={{
                        width: 34,
                        height: 34,
                        borderRadius: 2,
                        display: 'grid',
                        placeItems: 'center',
                        color: 'primary.main',
                        bgcolor: 'rgba(0,240,255,.08)',
                        border: '1px solid rgba(0,240,255,.22)',
                        fontWeight: 800,
                        fontSize: '0.8rem',
                      }}
                    >
                      {selected.size}
                    </Box>
                    <Box>
                      <Typography sx={{ fontWeight: 700, fontSize: '0.82rem', lineHeight: 1.4 }}>
                        {selected.size === 0 ? 'لم يتم اختيار موظفين بعد' : `${selected.size} موظفاً محدداً`}
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.66rem' }}>
                        سيُرسل لكل موظف رابط تتبع فريد
                      </Typography>
                    </Box>
                  </Stack>
                  <Box sx={{ flex: 1 }} />
                  <Stack direction="row" spacing={1}>
                    <Button onClick={() => setStep(0)}>رجوع</Button>
                    <Button
                      variant="contained"
                      disabled={!canLeaveStepTwo}
                      onClick={() => setStep(2)}
                    >
                      متابعة إلى المراجعة
                    </Button>
                  </Stack>
                </Stack>
              </Box>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {step === 2 ? (
        <Card>
          <CardContent>
            <Stack spacing={3}>
              <Box>
                <Typography variant="h3" sx={{ fontSize: '1.05rem' }} gutterBottom>
                  ملخص الحملة
                </Typography>
                <Stack spacing={1}>
                  <Typography variant="body2">
                    <strong>الاسم:</strong> {name}
                  </Typography>
                  <Typography variant="body2">
                    <strong>القناة:</strong> {CHANNEL_LABELS[channel]}
                  </Typography>
                  {isUsbChannel ? (
                    <>
                      <Typography variant="body2">
                        <strong>طبيعة الحملة:</strong> محاكاة فيزيائية ميدانية (Physical USB Baiting)
                      </Typography>
                      <Typography variant="body2">
                        <strong>سيناريو الطُعم:</strong> {USB_SCENARIOS.find((s) => s.id === usbScenario)?.title}
                      </Typography>
                      <Typography variant="body2">
                        <strong>موقع الإسقاط الفيزيائي:</strong> {usbDropLocation}
                      </Typography>
                      <Typography variant="body2">
                        <strong>تسمية الفلاشة (Volume Label):</strong> {usbVolumeLabel}
                      </Typography>
                      <Typography variant="body2">
                        <strong>المستهدفون:</strong> طُعم فيزيائي عام (أي موظف يلتقط الفلاشة ويقوم بتشغيلها)
                      </Typography>
                    </>
                  ) : (
                    <>
                      <Typography variant="body2">
                        <strong>القالب:</strong> {selectedTemplate?.name ?? '—'}
                      </Typography>
                      <Typography variant="body2">
                        <strong>الموضوع:</strong> {selectedTemplate?.subject ?? '—'}
                      </Typography>
                      <Typography variant="body2">
                        <strong>الصعوبة:</strong> {difficulty} — {difficultyLabel(difficulty)}
                      </Typography>
                      <Typography variant="body2">
                        <strong>المستهدفون:</strong>{' '}
                        {isQrChannel
                          ? 'طُعم عام (Generic Lure — أي شخص يقوم بمسح الرمز)'
                          : `${selected.size} موظفاً`}
                      </Typography>
                    </>
                  )}
                  <Typography variant="body2">
                    <strong>إعادة الاختبار التلقائي:</strong>{' '}
                    {autoRetestFailed ? 'مفعل (بعد 72 ساعة للموظفين غير المجتازين)' : 'معطل'}
                  </Typography>
                  <Typography variant="body2">
                    <strong>تدريب إلزامي:</strong>{' '}
                    {mandatoryTraining
                      ? 'مفعل (يتجاوز التهدئة والقائمة السوداء)'
                      : 'معطل'}
                  </Typography>
                </Stack>
              </Box>

              <Divider />

              {isQrChannel ? (
                <Box
                  sx={{
                    p: 2.5,
                    borderRadius: 2,
                    bgcolor: 'action.hover',
                    border: '1px solid',
                    borderColor: 'primary.main',
                  }}
                >
                  <Typography variant="subtitle1" sx={{ fontWeight: 800, color: 'primary.main', mb: 1 }}>
                    حملة طُعم عام (Generic Lure):
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
                    لا تتطلب هذه الحملة تحديد موظفين مسبقاً. فور النقر على زر «إطلاق الحملة وتجهيز الملصق»، سيتم تفعيل الحملة وتجهيز ملصق PDF واحد عام يحمل رمز QR الثابت للحملة (بدون أسماء موظفين). ستتمكن من تحميله فوراً وطباعته وتعليقه في الموقع المطلوب.
                  </Typography>
                </Box>
              ) : isUsbChannel ? (
                <Box
                  sx={{
                    p: 2.5,
                    borderRadius: 2,
                    bgcolor: 'rgba(0, 240, 255, 0.05)',
                    border: '1px solid rgba(0, 240, 255, 0.3)',
                  }}
                >
                  <Typography variant="subtitle1" sx={{ fontWeight: 800, color: 'primary.main', mb: 1 }}>
                    حملة طُعم فيزيائي عام (Physical USB Baiting):
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.8 }}>
                    هذه الحملة لا تتطلب اختيار موظفين مسبقاً؛ بل تعتمد على ترك فلاشات توعية مجهزة في موقع الإسقاط المحدد (<strong>{usbDropLocation}</strong>). فور النقر على زر «إطلاق الحملة والذهاب لمحطة التجهيز»، ستنتقل مباشرة إلى <strong>محطة تجهيز وحرق وسائط الـ USB</strong> لنسخ ملفات السيناريو بنقرة واحدة ورصد أي جهاز مخترق في الرادار المباشر فورياً.
                  </Typography>
                </Box>
              ) : (
                <Box>
                  <Typography variant="h3" sx={{ fontSize: '1.05rem' }} gutterBottom>
                    المستهدفون ({selectedList.length})
                  </Typography>
                  <TableContainer sx={{ maxHeight: 320 }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>الاسم</TableCell>
                          <TableCell>البريد</TableCell>
                          {isPhoneChannel ? <TableCell>الهاتف</TableCell> : null}
                          <TableCell>القسم</TableCell>
                          <TableCell>المسمى الوظيفي</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {selectedList.map((employee) => (
                          <TableRow key={employee.id}>
                            <TableCell>
                              {employee.first_name} {employee.last_name}
                            </TableCell>
                            <TableCell>{employee.email}</TableCell>
                            {isPhoneChannel ? (
                              <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                                {employee.phone ?? '—'}
                              </TableCell>
                            ) : null}
                            <TableCell>{employee.department ?? '—'}</TableCell>
                            <TableCell>{employee.job_title ?? '—'}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {cooldownQuery.data && cooldownQuery.data.blocked.length > 0 && !mandatoryTraining ? (
                <Alert severity="warning">
                  <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
                    تحذير: {cooldownQuery.data.blocked.length} موظفاً داخل فترة التهدئة أو
                    قائمة الفشل المتكرر.
                  </Typography>
                  <Typography variant="body2">
                    سيتم تخطيهم عند الإطلاق. راجع القائمة في نافذة التحذير قبل المتابعة.
                  </Typography>
                </Alert>
              ) : null}

              {isVoiceChannel ? (
                <Alert severity="warning">
                  سيتم إرسال حملة المكالمات الحقيقية إلى Celery. يتطلب التشغيل وجود
                  Redis وCelery worker. لا تغلق الـworker أثناء الحملة، وتأكد من أن
                  جميع الأرقام مصرّح بها. يمكنك متابعة حالة كل مكالمة من صفحة الحملة.
                </Alert>
              ) : null}

              {isQrChannel ? (
                <Alert severity="info">
                  قناة QR لا تستخدم مزوّد إرسال. سيتم إنشاء صفحة طباعة A4 لكل مستهدف برمز
                  فريد يفتح صفحة دخول جوال تحاكي شبكة الشركة والتأمين الصحي. عند إرسال
                  النموذج يُسجّل الحدثان{' '}
                  <span dir="ltr" className="mc-mono">qr_scanned</span> و{' '}
                  <span dir="ltr" className="mc-mono">credential_submitted</span> وتُحسب
                  خصومة Elo وفق وزن قناة QR (200) ومضاعف صعوبة القالب مرة واحدة. كلمة المرور لا تُخزَّن أبداً.
                </Alert>

              ) : isVishingChannel || isPretextingChannel ? (
                <Alert severity="info">
                  {isVishingChannel
                    ? 'قناة Vishing يدوية بالكامل: ستُجهّز رابط مكالمة واردة فريداً لكل مستهدف، مع تحويل النص إلى كلام داخل المتصفح. لا تُجرى مكالمة هاتفية حقيقية. إعطاء الرمز يُحسب كإدخال فاشل والإبلاغ كمكافأة، وفق وزن القناة ومضاعف الصعوبة.'
                    : 'قناة Pretexting يدوية بالكامل: ستُجهّز رابط محادثة CEO فريداً لكل مستهدف، وتُعرض رسالتا طلب بطاقات جوجل بلاي تلقائياً. لا تُرسل أموال أو رسائل حقيقية. الشراء يُحسب كإدخال فاشل والإبلاغ كمكافأة، وفق وزن القناة ومضاعف الصعوبة.'}
                </Alert>
              ) : preflightQuery.isFetching ? (
                <Alert severity="info">جارٍ التحقق من جاهزية الإرسال الحقيقي…</Alert>
              ) : preflightQuery.data && !preflightQuery.data.valid ? (
                <Alert
                  severity="error"
                  action={
                    <Button color="inherit" size="small" onClick={() => preflightQuery.refetch()}>
                      إعادة التحقق
                    </Button>
                  }
                >
                  <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                    الإرسال الحقيقي محجوب — الإطلاق لن يُرسل أي رسالة.
                  </Typography>
                  <Typography variant="body2">
                    {preflightQuery.data.hint ?? preflightQuery.data.error ?? 'فشل فحص الإرسال.'}
                  </Typography>
                  {'missing' in preflightQuery.data &&
                  Array.isArray(preflightQuery.data.missing) &&
                  preflightQuery.data.missing.length > 0 ? (
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', mt: 0.5 }}>
                      إعدادات ناقصة: {preflightQuery.data.missing.join('، ')}
                    </Typography>
                  ) : null}
                  {preflightQuery.data.blocked_ip ? (
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', mt: 0.5 }}>
                      عنوان IP المحجوب: {preflightQuery.data.blocked_ip}
                    </Typography>
                  ) : null}
                  {preflightQuery.data.action_url ? (
                    <Link
                      href={preflightQuery.data.action_url}
                      target="_blank"
                      rel="noreferrer"
                      underline="hover"
                      sx={{ display: 'inline-block', mt: 0.5 }}
                    >
                      {channel === 'email' ? 'فتح إعدادات مزوّد البريد' : 'فتح إعدادات TextBee'}
                    </Link>
                  ) : null}
                </Alert>
              ) : preflightQuery.data?.valid ? (
                <Alert severity="success">
                  الإرسال جاهز —{' '}
                  {channel === 'email'
                    ? preflightQuery.data.detail?.transport === 'smtp'
                      ? 'SMTP'
                      : 'Brevo'
                    : 'TextBee (SMS)'}{' '}
                  استلم إعدادات الإرسال بنجاح
                  {channel === 'sms' &&
                  'device_id' in preflightQuery.data &&
                  preflightQuery.data.device_id
                    ? ` — الجهاز: ${preflightQuery.data.device_id}`
                    : ''}
                  .
                </Alert>
              ) : preflightQuery.error ? (
                <Alert severity="warning">
                  تعذّر التحقق من الإرسال الآن: {errorMessage(preflightQuery.error)}. يمكنك المحاولة،
                  وستظهر النتيجة أدناه.
                </Alert>
              ) : null}

              {launchError ? (
                <Alert
                  severity="error"
                  action={
                    <Button color="inherit" size="small" onClick={() => launchMutation.mutate()}>
                      إعادة المحاولة
                    </Button>
                  }
                >
                  <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                    حُفظت الحملة كمسودة، لكن لم تُرسل أي رسالة.
                  </Typography>
                  <Typography variant="body2">{launchError}</Typography>
                </Alert>
              ) : null}

              {isQrChannel ? (
                <Alert severity="info">
                  سيتم إنشاء <strong>ملصق QR عام واحد (Generic Lure)</strong> بطُعم «
                  {QR_LURES.find((lure) => lure.value === qrPretext)?.label}» لصالح{' '}
                  <strong>{qrCompany || 'الشركة'}</strong>. لا يتطلب تحديد موظفين مسبقاً. الملصق يحمل رمزاً ثابتاً يربط برادار الحملة؛ المسح يسجل في الرادار فوراً، وأول إدخال للبيانات يطابق الموظف ويخصم نقاط Elo وفق وزن القناة والصعوبة. كلمة المرور لا تُخزَّن أبداً.
                </Alert>

              ) : (
                <Alert severity="warning">
                  سيتم إرسال <strong>{selected.size} {channelNoun} حقيقية</strong> عبر {providerName} من
                  المرسل المُعدّ. يجب أن تكون العناوين مملوكة للشركة ومشمولة بسياسة الاستخدام
                  المقبول. يُضاف رابط تتبع فريد لكل مستهدف، وكل فتح ونقرة وقيمة مُدخلة تُسجّل في
                  تقرير الحملة.
                </Alert>
              )}

              <Stack direction="row" justifyContent="space-between">
                <Button onClick={() => setStep((isQrChannel || isUsbChannel) ? 0 : 1)}>رجوع</Button>
                <Tooltip
                  title={
                    !isQrChannel && !isUsbChannel && selected.size === 0
                      ? 'اختر مستهدفاً واحداً على الأقل'
                      : preflightBlocked
                        ? 'الإرسال محجوب حتى تُكمل إعدادات المزوّد'
                        : ''
                  }
                >
                  <span>
                    <Button
                      variant="contained"
                      color="warning"
                      startIcon={
                        launchMutation.isPending ? (
                          <CircularProgress size={18} color="inherit" />
                        ) : null
                      }
                      disabled={
                        launchMutation.isPending ||
                        (!isQrChannel && !isUsbChannel && selected.size === 0) ||
                        preflightBlocked
                      }
                      onClick={() => void handleLaunchRequest()}
                    >
                      {isQrChannel ? 'إطلاق الحملة وتجهيز الملصق' : isUsbChannel ? 'إطلاق الحملة والذهاب لمحطة التجهيز' : 'إطلاق الحملة'}
                    </Button>
                  </span>
                </Tooltip>
              </Stack>

              {launchMutation.isPending ? (
                <Box>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    {isQrChannel
                      ? 'جارٍ إطلاق حملة QR وتجهيز الملصق العام…'
                      : isUsbChannel
                        ? `جارٍ تجهيز ${selected.size} مستند USB…`
                        : isVishingChannel || isPretextingChannel
                          ? `جارٍ تجهيز ${selected.size} رابط محاكاة…`
                          : `جارٍ إرسال ${selected.size} ${channelNoun} عبر ${providerName}…`}
                  </Typography>
                  <LinearProgress />
                </Box>
              ) : null}
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="تأكيد الإطلاق"
        message={
          isQrChannel
            ? 'سيتم إطلاق حملة QR كطُعم عام وتجهيز ملصق PDF جاهز للطباعة بدقة عالية. هل تريد المتابعة؟'
            : isUsbChannel
              ? `سيتم إطلاق حملة الـ USB الميدانية وتوجيهك مباشرة إلى محطة التجهيز المباشرة لنشر ملفات المحاكاة على الفلاشة ورصد الأجهزة في الرادار. هل تريد المتابعة؟`
              : isVishingChannel || isPretextingChannel
                ? `سيتم تجهيز ${selected.size} رابط محاكاة فريد. لا تُجرى مكالمة أو محادثة حقيقية ولا تُرسل أي رسالة. بعد الإطلاق افتح صفحة الحملة لعرض الروابط وتعليمات التسليم. هل تريد المتابعة؟`
                : `سيتم إرسال ${selected.size} ${channelNoun} حقيقية عبر ${providerName} إلى الموظفين المحددين. هل تريد المتابعة؟`
        }
        confirmLabel={
          isQrChannel
            ? 'إطلاق وتجهيز الملصق'
            : isUsbChannel
              ? 'إطلاق والذهاب لمحطة التجهيز'
              : isVishingChannel || isPretextingChannel
                ? 'تجهيز روابط المحاكاة'
                : 'إرسال الرسائل'
        }
        destructive
        busy={launchMutation.isPending}
        onConfirm={() => launchMutation.mutate()}
        onClose={() => setConfirmOpen(false)}
      />

      <Dialog
        open={cooldownOpen}
        onClose={() => setCooldownOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle sx={{ fontWeight: 800 }}>
          تحذير: موظفون خضعوا لاختبار حديث
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            بعض المستهدفين داخل فترة التهدئة ({cooldownQuery.data?.cooldown_days ?? 14} يوماً)
            أو في قائمة الفشل المتكرر. لن تُرسل لهم هذه الحملة، ويمكنك عرض نتيجة الاختبار
            السابق لكل موظف.
          </Alert>
          <Stack spacing={1.5}>
            {cooldownBlocked.map((blocked) => (
              <Box
                key={blocked.employee_id}
                sx={{
                  p: 1.5,
                  borderRadius: 2,
                  border: '1px solid',
                  borderColor:
                    blocked.reason === 'blacklisted_repeated_failure'
                      ? 'error.main'
                      : 'warning.main',
                  bgcolor: 'action.hover',
                }}
              >
                <Stack
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  sx={{ flexWrap: 'wrap', gap: 0.5, mb: 0.5 }}
                >
                  <Typography sx={{ fontWeight: 700 }}>
                    {blocked.name || blocked.email}
                  </Typography>
                  {blocked.reason === 'blacklisted_repeated_failure' ? (
                    <Chip
                      size="small"
                      color="error"
                      label="BLACKLISTED: Repeated Failure"
                      sx={{ fontWeight: 800 }}
                    />
                  ) : (
                    <Chip
                      size="small"
                      color="warning"
                      label={
                        blocked.days_remaining != null
                          ? `${blocked.days_remaining} يوم متبقٍ`
                          : 'فترة تهدئة'
                      }
                    />
                  )}
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 0.75 }}>
                  Employee {blocked.name || blocked.email} was tested recently. Cannot
                  send a new campaign.
                </Typography>
                {blocked.last_campaign_name ? (
                  <Typography variant="caption" color="text.secondary" display="block">
                    آخر حملة: {blocked.last_campaign_name}
                  </Typography>
                ) : null}
                <Button
                  size="small"
                  sx={{ mt: 0.5 }}
                  onClick={() =>
                    navigate(
                      blocked.last_campaign_id
                        ? `/campaigns/${blocked.last_campaign_id}`
                        : `/employees/${blocked.employee_id}`,
                    )
                  }
                >
                  عرض النتيجة السابقة (View Previous Result)
                </Button>
              </Box>
            ))}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCooldownOpen(false)}>إلغاء</Button>
          <Button
            variant="contained"
            color="warning"
            disabled={cooldownBlocked.length >= selected.size}
            onClick={() => {
              setCooldownOpen(false);
              setConfirmOpen(true);
            }}
          >
            إرسال للباقي ({Math.max(0, selected.size - cooldownBlocked.length)})
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(launchedQrId)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 800 }}>تم إطلاق حملة QR بنجاح!</DialogTitle>
        <DialogContent>
          <Stack spacing={2.5} sx={{ mt: 1 }}>
            <Alert severity="success">
              تم تفعيل الحملة بنجاح كطُعم عام وتوليد رمز QR ثابت للحملة يربط بنظام التتبع المباشر.
            </Alert>
            <Typography variant="body2" color="text.secondary">
              اضغط على الزر أدناه لتحميل ملصق الـ PDF الجاهز للطباعة بدقة عالية:
            </Typography>
            <Button
              variant="contained"
              color="primary"
              size="large"
              startIcon={<DownloadIcon />}
              disabled={downloadingPoster}
              onClick={async () => {
                if (!launchedQrId) return;
                try {
                  setDownloadingPoster(true);
                  const blob = await campaignsApi.generateQrPosters(launchedQrId);
                  const url = window.URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `qr-campaign-poster-${launchedQrId.slice(0, 8)}.pdf`;
                  document.body.appendChild(a);
                  a.click();
                  a.remove();
                  window.URL.revokeObjectURL(url);
                  toast.success('تم تنزيل ملصق PDF بنجاح!');
                } catch {
                  toast.error('تعذّر تنزيل الملصق. يمكنك تنزيله من صفحة الحملة.');
                } finally {
                  setDownloadingPoster(false);
                }
              }}
              sx={{ py: 1.5, fontWeight: 800 }}
            >
              {downloadingPoster ? 'جارٍ التحميل…' : 'تحميل ملصق QR المطبوع (Download PDF Poster)'}
            </Button>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              const id = launchedQrId;
              setLaunchedQrId(null);
              navigate(`/campaigns/${id}`);
            }}
          >
            الانتقال إلى لوحة الحملة والرادار المباشر
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
