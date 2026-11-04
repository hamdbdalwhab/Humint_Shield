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
import type { Employee, QrLureType } from '@/types';

const STEPS = ['التفاصيل', 'المستهدفون', 'المراجعة'];
const QR_STEPS = ['التفاصيل وإعداد الملصق', 'المراجعة والإطلاق'];

type WizardChannel = 'email' | 'sms' | 'whatsapp' | 'qr' | 'vishing' | 'pretexting' | 'usb';

const CHANNEL_LABELS: Record<WizardChannel, string> = {
  email: 'البريد الإلكتروني — Brevo',
  sms: 'رسائل SMS — Vonage',
  whatsapp: 'واتساب — Vonage',
  qr: 'رمز QR — Quishing (طباعة يدوية)',
  vishing: 'مكالمة صوتية — Vishing (رابط يدوي)',
  pretexting: 'محادثة CEO — Pretexting (رابط يدوي)',
  usb: 'فلاشة USB — HTML/PDF توعوي (توزيع يدوي)',
};

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
  const [templateId, setTemplateId] = useState('');
  const [difficulty, setDifficulty] = useState(5);
  const [autoRetestFailed, setAutoRetestFailed] = useState(false);
  const [selected, setSelected] = useState<Map<string, Employee>>(new Map());
  const [search, setSearch] = useState('');
  const [department, setDepartment] = useState('');
  const [activeOnly, setActiveOnly] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
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
      : channel === 'usb' || channel === 'vishing' || channel === 'pretexting'
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

  // Verify the outbound path before showing "Launch". Email uses Brevo; SMS
  // and WhatsApp use Vonage. A missing key/sender is surfaced before an
  // operator can assume a real send happened.
  const preflightQuery = useQuery({
    queryKey: ['delivery-preflight', channel],
    queryFn: () =>
      channel === 'email'
        ? diagnosticsApi.verifyBrevo()
        : diagnosticsApi.verifyVonage(channel as 'sms' | 'whatsapp'),
    enabled:
      step === 2 &&
      channel !== 'qr' &&
      channel !== 'usb' &&
      channel !== 'vishing' &&
      channel !== 'pretexting',
    staleTime: 15_000,
    retry: false,
  });

  const launchMutation = useMutation({
    mutationFn: async () => {
      if (!organizationId) throw new Error('No organization');
      if (channel === 'qr' && !qrCompany.trim()) {
        throw new Error('اسم الشركة مطلوب لإنشاء ملصق QR.');
      }
      const targets = channel === 'qr' ? [] : Array.from(selected.keys());
      const channelConfig =
        channel === 'qr'
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
                ? { usb: { document_name: 'راتب_الشهر_القادم.pdf' } }
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
          target_employee_ids: targets,
        });
      }
      return campaignsApi.launch(organizationId, campaignId);
    },
    onSuccess: (result) => {
      setConfirmOpen(false);
      setLaunchError(null);
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
          toast.success(
            `تم تجهيز ${result.total} مستند USB. حمّل ملف HTML أو PDF من صفحة الحملة.`,
          );
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
  const isManualChannel =
    isQrChannel || isUsbChannel || isVishingChannel || isPretextingChannel;
  const isPhoneChannel = channel === 'sms' || channel === 'whatsapp';

  function isSelectable(employee: Employee): boolean {
    return !isPhoneChannel || hasValidPhone(employee.phone);
  }

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

  const departments = useMemo(() => {
    const counts = new Map<string, number>();
    visibleEmployees.forEach((employee) => {
      if (!employee.department) return;
      counts.set(employee.department, (counts.get(employee.department) ?? 0) + 1);
    });
    return Array.from(counts.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [visibleEmployees]);

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

  const canLeaveStepOne = name.trim().length > 0 && templateId.length > 0;
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
        : channel === 'email'
          ? 'Brevo/SMTP'
          : 'Vonage';
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
          activeStep={isQrChannel ? (step === 2 ? 1 : 0) : step}
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
          {(isQrChannel ? QR_STEPS : STEPS).map((label) => (
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
                      ? 'حملة USB لا ترسل رسائل: بعد الإطلاق تُنزّل ملف HTML آمن باسم الرواتب_السرية.html، وتنسخه على فلاشات مصرّح بها. كل ملف يحمل رابط تتبع فريداً. القالب يُستخدم كمرجع للسيناريو فقط.'
                      : isVishingChannel || isPretextingChannel
                        ? 'هذه قناة محاكاة يدوية: لا تُرسل مكالمة أو رسالة حقيقية. بعد الإطلاق تنسخ رابط المحاكاة الفريد لكل موظف من صفحة الحملة. القالب يُستخدم كمرجع للسيناريو فقط.'
                        : 'البريد الإلكتروني يُرسل عبر Brevo، وSMS وواتساب يُرسلان عبر Vonage. أرقام الهاتف يجب أن تكون بصيغة E.164 مثل +966500000000.'
                }
              >
                <MenuItem value="email">البريد الإلكتروني</MenuItem>
                <MenuItem value="sms">SMS — Vonage</MenuItem>
                <MenuItem value="whatsapp">واتساب — Vonage</MenuItem>
                <MenuItem value="qr">رمز QR — Quishing</MenuItem>
                <MenuItem value="vishing">مكالمة صوتية — Vishing</MenuItem>
                <MenuItem value="pretexting">محادثة CEO — Pretexting</MenuItem>
                <MenuItem value="usb">فلاشة USB — HTML/PDF توعوي</MenuItem>
              </TextField>
              {isUsbChannel ? (
                <Alert severity="info">
                  سيتم إنشاء ملف HTML قياسي وآمن باسم{' '}
                  <strong>الرواتب_السرية.html</strong> يعرض تحذيراً أحمر فور فتحه ويسجل
                  الحدث <span dir="ltr" className="mc-mono">usb_opened</span>. يمكنك أيضاً
                  تنزيل نسخة PDF من صفحة الحملة. لا يحتوي أي ملف على برامج أو أوامر تنفيذية،
                  ولا يُشغّل أي شيء تلقائياً. راجع <strong>README_USB.md</strong> قبل التوزيع.
                </Alert>
              ) : null}
              {isVishingChannel || isPretextingChannel ? (
                <Alert severity="info">
                  {isVishingChannel
                    ? 'ستُجهّز صفحة مكالمة واردة تحاكي الدعم الفني، مع تحويل النص إلى كلام في المتصفح. لا تُجرى أي مكالمة هاتفية حقيقية ولا يُطلب رمز حقيقي.'
                    : 'ستُجهّز محادثة واتساب/Teams تحاكي الرئيس التنفيذي وتُعرض رسالتا الطلب تلقائياً. لا تُرسل أي أموال أو رسائل حقيقية.'}
                </Alert>
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

              {selectedTemplate ? (
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

              <Stack direction="row" justifyContent="flex-end">
                <Button
                  variant="contained"
                  disabled={!canLeaveStepOne}
                  onClick={() => setStep(isQrChannel ? 2 : 1)}
                >
                  {isQrChannel ? 'متابعة إلى مراجعة الحملة وإطلاقها' : 'متابعة إلى المستهدفين'}
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {step === 1 && !isQrChannel ? (
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
                  <Typography variant="body2">
                    <strong>إعادة الاختبار التلقائي:</strong>{' '}
                    {autoRetestFailed ? 'مفعل (بعد 72 ساعة للموظفين غير المجتازين)' : 'معطل'}
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

              {isQrChannel ? (
                <Alert severity="info">
                  قناة QR لا تستخدم مزوّد إرسال. سيتم إنشاء صفحة طباعة A4 لكل مستهدف برمز
                  فريد يفتح صفحة دخول جوال تحاكي شبكة الشركة والتأمين الصحي. عند إرسال
                  النموذج يُسجّل الحدثان{' '}
                  <span dir="ltr" className="mc-mono">qr_scanned</span> و{' '}
                  <span dir="ltr" className="mc-mono">credential_submitted</span> وتُخصم 25
                  نقطة Elo مرة واحدة. كلمة المرور لا تُخزَّن أبداً.
                </Alert>
              ) : isUsbChannel ? (
                <Alert severity="info">
                  قناة USB لا تستخدم مزوّد إرسال. سيتم إنشاء ملف HTML آمن باسم{' '}
                  <strong>الرواتب_السرية.html</strong> يعرض تحذيراً أحمر فور فتحه ويسجّل{' '}
                  <span dir="ltr" className="mc-mono">usb_opened</span> ويخصم 30 نقطة Elo مرة
                  واحدة. يمكنك أيضاً تنزيل نسخة PDF من صفحة الحملة. لا يحتوي أي ملف على
                  برنامج أو أمر تنفيذي.
                </Alert>
              ) : isVishingChannel || isPretextingChannel ? (
                <Alert severity="info">
                  {isVishingChannel
                    ? 'قناة Vishing يدوية بالكامل: ستُجهّز رابط مكالمة واردة فريداً لكل مستهدف، مع تحويل النص إلى كلام داخل المتصفح. لا تُجرى مكالمة هاتفية حقيقية. اختيار إعطاء الرمز يخصم 30 نقطة Elo، والإبلاغ يضيف 20 نقطة.'
                    : 'قناة Pretexting يدوية بالكامل: ستُجهّز رابط محادثة CEO فريداً لكل مستهدف، وتُعرض رسالتا طلب بطاقات جوجل بلاي تلقائياً. لا تُرسل أموال أو رسائل حقيقية. الشراء يخصم 30 نقطة Elo، والإبلاغ يضيف 20 نقطة.'}
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
                      {channel === 'email' ? 'فتح إعدادات مزوّد البريد' : 'فتح إعدادات Vonage'}
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
                    : `Vonage (${channel === 'sms' ? 'SMS' : 'WhatsApp'})`}{' '}
                  استلم إعدادات المرسل بنجاح
                  {channel !== 'email' &&
                  typeof preflightQuery.data.detail?.from === 'string' &&
                  preflightQuery.data.detail.from.trim()
                    ? ` — المرسل: ${preflightQuery.data.detail.from}`
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
                  <strong>{qrCompany || 'الشركة'}</strong>. لا يتطلب تحديد موظفين مسبقاً. الملصق يحمل رمزاً ثابتاً يربط برادار الحملة؛ المسح يسجل في الرادار فوراً، وأول إدخال للبيانات يطابق الموظف ويخصم 25 نقطة Elo. كلمة المرور لا تُخزَّن أبداً.
                </Alert>
              ) : isUsbChannel ? (
                <Alert severity="info">
                  سيتم تجهيز <strong>{selected.size} ملف USB آمن</strong> باسم{' '}
                  <strong>الرواتب_السرية.html</strong> (وعند تعدد المستهدفين يُنزَّل ZIP بمجلد
                  لكل موظف). عند أول فتح يسجّل{' '}
                  <span dir="ltr" className="mc-mono">usb_opened</span> ويخصم 30 نقطة Elo ثم
                  يعرض التحذير وزر التدريب. يتوفر ملف PDF احتياطي من صفحة الحملة بعد الإطلاق، ولا
                  توزّع أي ملف إلا ضمن تمرين مصرّح به.
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
                <Button onClick={() => setStep(isQrChannel ? 0 : 1)}>رجوع</Button>
                <Tooltip
                  title={
                    !isQrChannel && selected.size === 0
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
                        (!isQrChannel && selected.size === 0) ||
                        preflightBlocked
                      }
                      onClick={() => setConfirmOpen(true)}
                    >
                      {isQrChannel ? 'إطلاق الحملة وتجهيز الملصق' : 'إطلاق الحملة'}
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
              ? `سيتم تجهيز ${selected.size} ملف USB آمن. عند التوزيع يمكنك تنزيل الرواتب_السرية.html لكل موظف أو حزمة ZIP، مع نسخة PDF اختيارية. لا تُرسل أي رسائل ولا يُنفّذ أي برنامج. بعد الإطلاق نزّل الملف من صفحة الحملة. هل تريد المتابعة؟`
              : isVishingChannel || isPretextingChannel
                ? `سيتم تجهيز ${selected.size} رابط محاكاة فريد. لا تُجرى مكالمة أو محادثة حقيقية ولا تُرسل أي رسالة. بعد الإطلاق افتح صفحة الحملة لعرض الروابط وتعليمات التسليم. هل تريد المتابعة؟`
                : `سيتم إرسال ${selected.size} ${channelNoun} حقيقية عبر ${providerName} إلى الموظفين المحددين. هل تريد المتابعة؟`
        }
        confirmLabel={
          isQrChannel
            ? 'إطلاق وتجهيز الملصق'
            : isUsbChannel
              ? 'تجهيز مستند USB'
              : isVishingChannel || isPretextingChannel
                ? 'تجهيز روابط المحاكاة'
                : 'إرسال الرسائل'
        }
        destructive
        busy={launchMutation.isPending}
        onConfirm={() => launchMutation.mutate()}
        onClose={() => setConfirmOpen(false)}
      />

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
