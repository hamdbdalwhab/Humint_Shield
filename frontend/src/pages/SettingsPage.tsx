/**
 * Settings: runtime configuration, dependency health and a Brevo deliverability
 * self-test. Read-only by design — secrets are never exposed to the browser.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { brandingApi, campaignsApi, diagnosticsApi } from '@/api/endpoints';
import { LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { UsersPermissionsTab } from '@/components/settings/UsersPermissionsTab';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';

const COMPLIANCE = [
  'ISO/IEC 27001 A.7.2.2 — information security awareness, education and training.',
  'NIST SP 800-50 and SP 800-53 AT-2 — literacy training and awareness.',
  'PCI-DSS v4.0 requirement 12.6 — security awareness program.',
  'HIPAA Security Rule 164.308(a)(5) — workforce security awareness training.',
  'GDPR Article 32 — security of processing, including staff awareness.',
];

/** Curated brand colours that all keep white button text legible. */
const BRAND_PALETTE = [
  '#0F6CBD',
  '#0B6B53',
  '#7A1F3D',
  '#4B3FA6',
  '#B45309',
  '#0E7490',
  '#334155',
];

/** WCAG relative luminance of a #rrggbb colour. */
function relativeLuminance(hex: string): number {
  const value = hex.replace('#', '');
  const channels = [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) =>
    channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** Contrast ratio between two colours (1–21). */
function contrastRatio(a: string, b: string): number {
  const first = relativeLuminance(a);
  const second = relativeLuminance(b);
  const [light, dark] = first > second ? [first, second] : [second, first];
  return (light + 0.05) / (dark + 0.05);
}

/** Small helper that renders a boolean dependency state as a chip. */
function StateChip({ ok, label }: { ok: boolean; label: string }) {
  return <Chip size="small" label={label} color={ok ? 'success' : 'error'} variant="outlined" />;
}

function BrandingSettings({ organizationId }: { organizationId: string | null }) {
  const queryClient = useQueryClient();
  const { can } = useAuth();
  const [companyName, setCompanyName] = useState('');
  const [primaryColor, setPrimaryColor] = useState('#0F6CBD');
  const [supportEmail, setSupportEmail] = useState('');
  const canEdit = can('settings.branding');
  const colorValid = /^#[0-9a-f]{6}$/i.test(primaryColor);
  const whiteContrast = colorValid ? contrastRatio(primaryColor, '#FFFFFF') : 0;
  const contrastOk = whiteContrast >= 4.5;

  const brandingQuery = useQuery({
    queryKey: ['branding', organizationId],
    queryFn: () => brandingApi.get(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const dirty =
    Boolean(brandingQuery.data) &&
    (companyName !== brandingQuery.data?.company_name ||
      primaryColor !== brandingQuery.data?.primary_color ||
      supportEmail !== (brandingQuery.data?.support_email ?? ''));

  useEffect(() => {
    const data = brandingQuery.data;
    if (!data) return;
    setCompanyName(data.company_name);
    setPrimaryColor(data.primary_color);
    setSupportEmail(data.support_email ?? '');
  }, [brandingQuery.data]);

  const updateMutation = useMutation({
    mutationFn: () =>
      brandingApi.update(organizationId as string, {
        company_name: companyName.trim(),
        primary_color: primaryColor,
        support_email: supportEmail.trim() || null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['branding', organizationId], data);
      toast.success('تم حفظ الهوية البصرية');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const logoMutation = useMutation({
    mutationFn: (file: File) => brandingApi.uploadLogo(organizationId as string, file),
    onSuccess: (data) => {
      queryClient.setQueryData(['branding', organizationId], data);
      toast.success('تم رفع الشعار');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const removeLogoMutation = useMutation({
    mutationFn: () => brandingApi.removeLogo(organizationId as string),
    onSuccess: (data) => {
      queryClient.setQueryData(['branding', organizationId], data);
      toast.success('تمت إزالة الشعار');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (!organizationId) {
    return <Alert severity="warning">لا يوجد كيان مرتبط بهذا الحساب.</Alert>;
  }
  if (brandingQuery.isLoading) return <LoadingState label="جارٍ تحميل الهوية البصرية…" />;
  if (brandingQuery.error) return <Alert severity="error">{errorMessage(brandingQuery.error)}</Alert>;

  const data = brandingQuery.data;
  const busy =
    updateMutation.isPending || logoMutation.isPending || removeLogoMutation.isPending;

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={7}>
        <Card>
          <CardContent>
            <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 0.5 }}>
              الهوية البصرية للمؤسسة
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              ترث القوالب الجديدة هذه الهوية تلقائياً، ويمكن لكل قالب تجاوز لون الزر من المحرر المرئي.
            </Typography>
            <Stack spacing={2}>
              <TextField
                label="اسم المؤسسة"
                fullWidth
                value={companyName}
                onChange={(event) => setCompanyName(event.target.value)}
                disabled={!canEdit || busy}
                helperText="يُستخدم في التذييل وفي وسم الدمج {{company_name}}."
              />
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <TextField
                  label="اللون الأساسي للعلامة"
                  fullWidth
                  value={primaryColor}
                  onChange={(event) => setPrimaryColor(event.target.value.toUpperCase())}
                  disabled={!canEdit || busy}
                  InputProps={{
                    startAdornment: (
                      <Box
                        component="input"
                        type="color"
                        value={/^#[0-9a-f]{6}$/i.test(primaryColor) ? primaryColor : '#0F6CBD'}
                        onChange={(event) => setPrimaryColor(event.target.value.toUpperCase())}
                        sx={{
                          width: 32,
                          height: 32,
                          p: 0,
                          border: '1px solid rgba(255,255,255,.2)',
                          borderRadius: 1,
                          bgcolor: 'transparent',
                          cursor: 'pointer',
                          mr: 1,
                        }}
                      />
                    ),
                    sx: { fontFamily: 'Consolas, monospace' },
                  }}
                />
                <TextField
                  label="بريد الدعم"
                  type="email"
                  fullWidth
                  value={supportEmail}
                  onChange={(event) => setSupportEmail(event.target.value)}
                  disabled={!canEdit || busy}
                  helperText="يظهر في تذييل البريد."
                />
              </Stack>
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
                  لوحة ألوان جاهزة
                </Typography>
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
                  {BRAND_PALETTE.map((color) => (
                    <Tooltip key={color} title={color}>
                      <Box
                        role="button"
                        tabIndex={0}
                        aria-label={`اختيار اللون ${color}`}
                        onClick={() => canEdit && setPrimaryColor(color)}
                        onKeyDown={(event) => {
                          if ((event.key === 'Enter' || event.key === ' ') && canEdit) {
                            setPrimaryColor(color);
                          }
                        }}
                        sx={{
                          width: 34,
                          height: 34,
                          borderRadius: 1.5,
                          bgcolor: color,
                          cursor: canEdit ? 'pointer' : 'not-allowed',
                          outline:
                            primaryColor.toUpperCase() === color
                              ? '2px solid #fff'
                              : '2px solid transparent',
                          outlineOffset: 2,
                          opacity: canEdit ? 1 : 0.5,
                        }}
                      />
                    </Tooltip>
                  ))}
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                  <Chip
                    size="small"
                    color={contrastOk ? 'success' : 'error'}
                    variant="outlined"
                    label={
                      colorValid
                        ? `تباين نص الزر: ${whiteContrast.toFixed(2)}:1 ${contrastOk ? '✓ AA' : '✗ ضعيف'}`
                        : 'أدخل لوناً صحيحاً'
                    }
                  />
                  {colorValid && !contrastOk ? (
                    <Typography variant="caption" color="error.main">
                      يُنصح باختيار لون أغمق ليقرأ النص الأبيض بوضوح.
                    </Typography>
                  ) : null}
                </Stack>
              </Box>
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
                  الشعار (PNG أو JPEG أو GIF أو WebP — بحد أقصى ٢ ميغابايت)
                </Typography>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap', gap: 1 }}>
                  <Button
                    component="label"
                    variant="outlined"
                    disabled={!canEdit || busy}
                    sx={{ position: 'relative', overflow: 'hidden' }}
                  >
                    {logoMutation.isPending ? 'جارٍ الرفع…' : 'رفع الشعار'}
                    <Box
                      component="input"
                      type="file"
                      accept="image/png,image/jpeg,image/gif,image/webp"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) logoMutation.mutate(file);
                        event.target.value = '';
                      }}
                      sx={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
                    />
                  </Button>
                  {data?.has_logo ? (
                    <Button
                      variant="text"
                      color="error"
                      disabled={!canEdit || busy}
                      onClick={() => removeLogoMutation.mutate()}
                    >
                      إزالة الشعار
                    </Button>
                  ) : null}
                </Stack>
              </Box>
              <Box>
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
                  <Button
                    variant="contained"
                    disabled={!canEdit || busy || !companyName.trim() || !colorValid}
                    startIcon={updateMutation.isPending ? <CircularProgress size={16} color="inherit" /> : null}
                    onClick={() => updateMutation.mutate()}
                  >
                    حفظ الهوية
                  </Button>
                  <Button
                    variant="text"
                    disabled={!canEdit || busy || !dirty}
                    onClick={() => {
                      if (!data) return;
                      setCompanyName(data.company_name);
                      setPrimaryColor(data.primary_color);
                      setSupportEmail(data.support_email ?? '');
                    }}
                  >
                    تراجع عن التغييرات
                  </Button>
                </Stack>
                {dirty ? (
                  <Typography variant="caption" sx={{ display: 'block', color: 'warning.main', mt: 1 }}>
                    توجد تغييرات غير محفوظة بعد.
                  </Typography>
                ) : null}
                {!colorValid ? (
                  <Typography variant="caption" sx={{ display: 'block', color: 'error.main', mt: 1 }}>
                    اللون يجب أن يكون بصيغة HEX من ست خانات، مثل #0F6CBD.
                  </Typography>
                ) : null}
                {!canEdit ? (
                  <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 1 }}>
                    تعديل الهوية يتطلب صلاحية settings.branding.
                  </Typography>
                ) : null}
              </Box>
            </Stack>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={5}>
        <Card sx={{ height: '100%' }}>
          <CardContent>
            <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
              معاينة حيّة للهوية
            </Typography>
            <Box
              sx={{
                borderRadius: 2,
                border: '1px solid rgba(255,255,255,.1)',
                overflow: 'hidden',
                bgcolor: '#F2F4F7',
                color: '#344054',
                p: 2.5,
              }}
            >
              <Stack direction="row" spacing={1.25} alignItems="center" sx={{ mb: 2 }}>
                {data?.logo_url ? (
                  <Box
                    component="img"
                    src={data.logo_url}
                    alt={companyName || data.company_name}
                    sx={{ width: 54, height: 54, objectFit: 'contain', borderRadius: 1.5, bgcolor: '#fff' }}
                  />
                ) : (
                  <Box
                    sx={{
                      width: 54,
                      height: 54,
                      borderRadius: 1.5,
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: primaryColor,
                      color: '#fff',
                      fontWeight: 900,
                    }}
                  >
                    {(companyName || data?.company_name || 'H').slice(0, 2)}
                  </Box>
                )}
                <Box>
                  <Typography sx={{ fontWeight: 800, color: '#101828' }}>
                    {companyName || data?.company_name || 'Your company'}
                  </Typography>
                  <Typography variant="caption" sx={{ color: '#667085' }}>
                    {supportEmail || 'support@company.com'}
                  </Typography>
                </Box>
              </Stack>
              <Box sx={{ bgcolor: '#fff', borderRadius: 1.5, p: 2, border: '1px solid #E4E7EC' }}>
                <Typography sx={{ fontSize: '0.82rem', color: '#344054', mb: 1.5 }}>
                  مرحباً سارة، لديك مستند جديد يحتاج مراجعتك.
                </Typography>
                <Button
                  size="small"
                  variant="contained"
                  sx={{ bgcolor: primaryColor, '&:hover': { bgcolor: primaryColor } }}
                >
                  فتح المستند
                </Button>
              </Box>
              <Typography variant="caption" sx={{ display: 'block', color: '#98A2B3', mt: 2 }}>
                © {new Date().getFullYear()} {companyName || data?.company_name || 'Your company'}.
              </Typography>
            </Box>
            <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 1.5 }}>
              تستخدم هذه المعاينة القيم الحيّة نفسها التي يحقنها محرّك البريد.
            </Typography>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  );
}

type SettingsTab = 'runtime' | 'branding' | 'users';
const SETTINGS_TABS: SettingsTab[] = ['runtime', 'branding', 'users'];

export function SettingsPage() {
  const { user, can } = useAuth();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab') as SettingsTab | null;
  const tab: SettingsTab =
    requestedTab && SETTINGS_TABS.includes(requestedTab) ? requestedTab : 'runtime';
  const setTab = (next: SettingsTab) => {
    setSearchParams(next === 'runtime' ? {} : { tab: next });
  };
  const [testEmail, setTestEmail] = useState(user?.email ?? '');
  const [cooldownDays, setCooldownDays] = useState(14);
  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(testEmail.trim());
  const canDiagnostics = can('settings.diagnostics');
  const canGuardrails = can('settings.guardrails');

  const configQuery = useQuery({
    queryKey: ['runtime-config'],
    queryFn: () => diagnosticsApi.config(),
  });

  const healthQuery = useQuery({
    queryKey: ['diagnostics-health'],
    queryFn: () => diagnosticsApi.health(),
  });

  const guardrailsQuery = useQuery({
    queryKey: ['campaign-guardrails', user?.organization_id],
    queryFn: () => campaignsApi.guardrails(user?.organization_id as string),
    enabled: Boolean(user?.organization_id),
  });

  useEffect(() => {
    if (guardrailsQuery.data) {
      setCooldownDays(guardrailsQuery.data.campaign_cooldown_days);
    }
  }, [guardrailsQuery.data]);

  const guardrailsMutation = useMutation({
    mutationFn: () =>
      campaignsApi.updateGuardrails(user?.organization_id as string, {
        campaign_cooldown_days: cooldownDays,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['campaign-guardrails', user?.organization_id], data);
      toast.success('تم حفظ فترة التهدئة بين الحملات.');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const testMutation = useMutation({
    mutationFn: (toEmail: string) => diagnosticsApi.sendTestEmail(toEmail),
    onSuccess: (result) => {
      if (result.success) {
        toast.success(`Test email dispatched${result.message_id ? ` (${result.message_id})` : ''}`);
      } else {
        toast.error(result.error ?? 'The email could not be dispatched.');
      }
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const verifyMutation = useMutation({
    mutationFn: () => diagnosticsApi.verifyBrevo(),
    onError: (error) => toast.error(errorMessage(error)),
  });

  const verifyIllyVoipMutation = useMutation({
    mutationFn: () => diagnosticsApi.verifyIllyVoIP(),
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <>
      <PageHeader
        title="الإعدادات"
        subtitle="الهوية البصرية، إعدادات التشغيل والتشخيص، وإدارة المستخدمين والصلاحيات الدقيقة."
      />

      <Tabs
        value={SETTINGS_TABS.indexOf(tab)}
        onChange={(_event, value: number) => setTab(SETTINGS_TABS[value] ?? 'runtime')}
        variant="scrollable"
        allowScrollButtonsMobile
        sx={{ mb: 2 }}
      >
        <Tab label="التشغيل والتشخيص" />
        <Tab label="الهوية البصرية" />
        <Tab label="المستخدمون والصلاحيات" />
      </Tabs>

      {tab === 'runtime' ? (
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                الحساب الحالي
              </Typography>
              <Stack spacing={1}>
                <Typography variant="body2">
                  <strong>اسم المستخدم:</strong> {user?.username ?? '—'}
                </Typography>
                <Typography variant="body2">
                  <strong>البريد:</strong> {user?.email ?? '—'}
                </Typography>
                <Typography variant="body2">
                  <strong>الدور:</strong> {user?.role ?? '—'}
                </Typography>
                <Typography variant="body2">
                  <strong>الصلاحيات الفعّالة:</strong>{' '}
                  {user?.effective_permissions?.length ?? 0}
                </Typography>
                <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                  <strong>المؤسسة:</strong> {user?.organization_id ?? '—'}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                ضوابط الحملات
              </Typography>
              <Stack spacing={2}>
                <Typography variant="body2" color="text.secondary">
                  الحد الأدنى للأيام بين محاكاتين للموظف نفسه. القيمة 0 تُعطّل التهدئة، وحملات
                  التدريب الإلزامي تتجاوزها دائماً.
                </Typography>
                {guardrailsQuery.isLoading ? (
                  <LoadingState label="Loading guardrails…" />
                ) : guardrailsQuery.error ? (
                  <Alert severity="error">{errorMessage(guardrailsQuery.error)}</Alert>
                ) : (
                  <TextField
                    label="فترة التهدئة (أيام)"
                    type="number"
                    fullWidth
                    inputProps={{ min: 0, max: 365 }}
                    value={cooldownDays}
                    onChange={(event) =>
                      setCooldownDays(Math.max(0, Math.min(365, Number(event.target.value) || 0)))
                    }
                  />
                )}
                <Box>
                  <Button
                    variant="contained"
                    disabled={guardrailsMutation.isPending || !canGuardrails}
                    onClick={() => guardrailsMutation.mutate()}
                  >
                    حفظ التهدئة
                  </Button>
                  {!canGuardrails ? (
                    <Typography
                      variant="caption"
                      sx={{ display: 'block', color: 'text.secondary', mt: 1 }}
                    >
                      التعديل يتطلب صلاحية settings.guardrails.
                    </Typography>
                  ) : null}
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                إعدادات التشغيل
              </Typography>
              {configQuery.isLoading ? (
                <LoadingState label="Loading configuration…" />
              ) : configQuery.error ? (
                <Alert severity="error">{errorMessage(configQuery.error)}</Alert>
              ) : configQuery.data ? (
                <Stack spacing={1}>
                  <Typography variant="body2">
                    <strong>البيئة:</strong> {configQuery.data.environment}
                  </Typography>
                  <Typography variant="body2">
                    <strong>الرابط الأساسي:</strong> {configQuery.data.base_url}
                  </Typography>
                  <Typography variant="body2">
                    <strong>رابط الواجهة:</strong> {configQuery.data.frontend_url}
                  </Typography>
                  <Typography variant="body2">
                    <strong>المُرسل:</strong> {configQuery.data.from_name} &lt;
                    {configQuery.data.from_email}&gt;
                  </Typography>
                  <Stack direction="row" spacing={1} sx={{ pt: 1, flexWrap: 'wrap', gap: 1 }}>
                    <Chip
                      size="small"
                      label={`Transport: ${configQuery.data.email_transport.toUpperCase()}`}
                      color="info"
                      variant="outlined"
                    />
                    <Chip
                      size="small"
                      label={
                        configQuery.data.email_transport === 'smtp'
                          ? configQuery.data.smtp_configured
                            ? 'SMTP configured'
                            : 'SMTP missing'
                          : configQuery.data.brevo_configured
                            ? 'Brevo configured'
                            : 'Brevo missing'
                      }
                      color={
                        configQuery.data.email_transport === 'smtp'
                          ? configQuery.data.smtp_configured
                            ? 'success'
                            : 'error'
                          : configQuery.data.brevo_configured
                            ? 'success'
                            : 'error'
                      }
                    />
                    <Chip
                      size="small"
                      label={configQuery.data.email_dry_run ? 'Dry run' : 'Live sending'}
                      color={configQuery.data.email_dry_run ? 'warning' : 'success'}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={
                        configQuery.data.rate_limit_enabled ? 'Rate limiting on' : 'Rate limiting off'
                      }
                    />
                  </Stack>
                </Stack>
              ) : null}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                سلامة التبعيات
              </Typography>
              {healthQuery.isLoading ? (
                <LoadingState label="Probing dependencies…" />
              ) : healthQuery.error ? (
                <Alert severity="error">{errorMessage(healthQuery.error)}</Alert>
              ) : healthQuery.data ? (
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <StateChip ok={healthQuery.data.db.ok} label={`Database: ${healthQuery.data.db.ok ? 'ok' : 'down'}`} />
                    <StateChip
                      ok={healthQuery.data.redis.ok}
                      label={`Redis: ${healthQuery.data.redis.ok ? 'ok' : 'unavailable'}`}
                    />
                  </Stack>
                  {healthQuery.data.db.error ? (
                    <Alert severity="warning">DB: {healthQuery.data.db.error}</Alert>
                  ) : null}
                  {healthQuery.data.redis.error ? (
                    <Alert severity="info">Redis: {healthQuery.data.redis.error}</Alert>
                  ) : null}
                </Stack>
              ) : null}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                اختبار تسليم البريد
              </Typography>
              <Stack spacing={2}>
                <Typography variant="body2" color="text.secondary">
                  أرسل رسالة اختبار واحدة عبر قناة الإرسال الفعّالة (Brevo أو SMTP) للتأكد من صحة
                  هوية المُرسل ومسار الخروج.
                </Typography>
                <TextField
                  label="عنوان المستلم"
                  type="email"
                  fullWidth
                  value={testEmail}
                  onChange={(event) => setTestEmail(event.target.value)}
                  error={testEmail.length > 0 && !emailValid}
                  helperText={
                    testEmail.length > 0 && !emailValid ? 'صيغة البريد الإلكتروني غير صحيحة.' : undefined
                  }
                />
                <Box>
                  <Button
                    variant="contained"
                    disabled={testMutation.isPending || !emailValid || !canDiagnostics}
                    startIcon={testMutation.isPending ? <CircularProgress size={18} color="inherit" /> : null}
                    onClick={() => testMutation.mutate(testEmail.trim())}
                  >
                    إرسال بريد اختبار
                  </Button>
                  {!canDiagnostics ? (
                    <Typography
                      variant="caption"
                      sx={{ display: 'block', color: 'text.secondary', mt: 1 }}
                    >
                      التشخيص يتطلب صلاحية settings.diagnostics.
                    </Typography>
                  ) : null}
                </Box>

                <Divider flexItem />

                <Stack spacing={1.5}>
                  <Typography variant="subtitle2">إعدادات التسليم</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Brevo blocks requests from addresses that are not on the account allowlist.
                    Check the transport and, when Brevo is selected, find the exact address to
                    authorise.
                  </Typography>
                  <Box>
                    <Button
                      variant="outlined"
                      disabled={verifyMutation.isPending || !canDiagnostics}
                      startIcon={
                        verifyMutation.isPending ? <CircularProgress size={18} color="inherit" /> : null
                      }
                      onClick={() => verifyMutation.mutate()}
                    >
                      فحص التسليم الآن
                    </Button>
                  </Box>
                  {verifyMutation.data ? (
                    verifyMutation.data.valid ? (
                      <Alert severity="success">
                        {verifyMutation.data.detail?.transport === 'smtp'
                          ? 'SMTP login succeeded.'
                          : 'Brevo accepted the key.'}
                        {verifyMutation.data.detail?.email
                          ? ` Account: ${String(verifyMutation.data.detail.email)}.`
                          : ''}
                        {verifyMutation.data.detail?.host
                          ? ` Host: ${String(verifyMutation.data.detail.host)}.`
                          : ''}
                      </Alert>
                    ) : (
                      <Alert severity="error">
                        <Typography variant="body2" sx={{ mb: 1 }}>
                          {verifyMutation.data.hint ?? verifyMutation.data.error ?? 'Brevo check failed.'}
                        </Typography>
                        {verifyMutation.data.blocked_ip ? (
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', mb: 1 }}>
                            Blocked IP: {verifyMutation.data.blocked_ip}
                          </Typography>
                        ) : null}
                        {verifyMutation.data.action_url ? (
                          <Link
                            href={verifyMutation.data.action_url}
                            target="_blank"
                            rel="noreferrer"
                            underline="hover"
                          >
                            Open the Brevo setting
                          </Link>
                        ) : null}
                      </Alert>
                    )
                  ) : null}
                </Stack>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                بوابة الرسائل النصية TextBee
              </Typography>
              {configQuery.isLoading ? (
                <LoadingState label="Loading delivery configuration..." />
              ) : configQuery.error ? (
                <Alert severity="error">{errorMessage(configQuery.error)}</Alert>
              ) : configQuery.data ? (
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
                    <Chip
                      size="small"
                      color={
                        configQuery.data.sms_provider && configQuery.data.sms_provider !== 'none'
                          ? 'success'
                          : 'error'
                      }
                      label={`SMS provider: ${
                        configQuery.data.sms_provider === 'textbee'
                          ? `TextBee${
                              configQuery.data.textbee_device_id
                                ? ` · ${configQuery.data.textbee_device_id.slice(0, 8)}…`
                                : ''
                            }`
                          : 'none configured'
                      }`}
                    />
                    <StateChip
                      ok={Boolean(configQuery.data.textbee_configured)}
                      label={`TextBee API key: ${configQuery.data.textbee_configured ? 'ready' : 'not configured'}`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={configQuery.data.textbee_device_id || 'default TextBee device'}
                    />
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    SMS is delivered only through the TextBee Android gateway. Credentials stay in{' '}
                    <code>backend/.env</code> and are never sent to the browser. WhatsApp is not
                    available in this build.
                  </Typography>
                  {configQuery.data.textbee_missing_settings?.length ? (
                    <Alert severity="warning">
                      Missing TextBee settings: {configQuery.data.textbee_missing_settings.join(', ')}
                    </Alert>
                  ) : null}
                </Stack>
              ) : null}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                المكالمات الصوتية الحقيقية IllyVoIP (الويشينغ)
              </Typography>
              {configQuery.isLoading ? (
                <LoadingState label="Loading voice configuration..." />
              ) : configQuery.data ? (
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
                    <StateChip
                      ok={Boolean(configQuery.data.illyvoip_configured)}
                      label={`Voice API: ${configQuery.data.illyvoip_configured ? 'ready' : 'not configured'}`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`TTS: ${configQuery.data.illyvoip_tts_language ?? 'en-US'} / ${configQuery.data.illyvoip_tts_voice ?? 'illyvoip-emma'}`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`Caller ID: ${
                        configQuery.data.illyvoip_caller_id ??
                        configQuery.data.illyvoip_sip_user_id ??
                        'account default'
                      }${
                        configQuery.data.illyvoip_caller_id
                          ? ''
                          : ' (SIP identity — no verified number on the account)'
                      }`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      color={configQuery.data.illyvoip_record_calls ? 'warning' : 'default'}
                      label={
                        configQuery.data.illyvoip_record_calls
                          ? 'Call recording enabled'
                          : 'Call recording disabled'
                      }
                    />
                  </Stack>
                  {configQuery.data.illyvoip_missing_settings &&
                  configQuery.data.illyvoip_missing_settings.length > 0 ? (
                    <Alert severity="warning">
                      Missing settings: {configQuery.data.illyvoip_missing_settings.join(', ')}.
                      Add them to <code>backend/.env</code> and restart the API.
                    </Alert>
                  ) : null}
                  {configQuery.data.illyvoip_identity_warnings &&
                  configQuery.data.illyvoip_identity_warnings.length > 0 ? (
                    <Alert severity="info">
                      {configQuery.data.illyvoip_identity_warnings.join(', ')} not set — IllyVoIP
                      will use the account's main SIP identity and default caller ID. Set them
                      to pin the exact line that places the call.
                    </Alert>
                  ) : null}
                  <Typography variant="body2" color="text.secondary">
                    Real outbound calls use the IllyVoIP Voice API with native TTS. The
                    documented TTS catalog currently supports <code>en-US</code> only, so
                    voice scripts must be English. Credentials never reach the browser.
                  </Typography>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Button
                      variant="outlined"
                      size="small"
                      disabled={verifyIllyVoipMutation.isPending || !canDiagnostics}
                      startIcon={
                        verifyIllyVoipMutation.isPending ? (
                          <CircularProgress size={16} color="inherit" />
                        ) : null
                      }
                      onClick={() => verifyIllyVoipMutation.mutate()}
                    >
                      التحقق من Voice API
                    </Button>
                    <Typography variant="caption" color="text.secondary">
                      Checks configuration and the live Voice backend without placing a call.
                    </Typography>
                  </Stack>
                  {verifyIllyVoipMutation.data ? (
                    verifyIllyVoipMutation.data.valid ? (
                      <Alert severity="success">
                        IllyVoIP accepted the configuration and the Voice backend is reachable.
                      </Alert>
                    ) : (
                      <Alert severity="error">
                        {verifyIllyVoipMutation.data.hint ??
                          verifyIllyVoipMutation.data.error ??
                          'IllyVoIP verification failed.'}
                        {verifyIllyVoipMutation.data.missing &&
                        verifyIllyVoipMutation.data.missing.length > 0 ? (
                          <Typography variant="body2" sx={{ fontFamily: 'monospace', mt: 0.5 }}>
                            Missing: {verifyIllyVoipMutation.data.missing.join(', ')}
                          </Typography>
                        ) : null}
                      </Alert>
                    )
                  ) : null}
                </Stack>
              ) : null}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                الأساس التنظيمي للامتثال
              </Typography>
              <Stack spacing={1} divider={<Divider flexItem />}>
                {COMPLIANCE.map((line) => (
                  <Typography key={line} variant="body2">
                    {line}
                  </Typography>
                ))}
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      ) : tab === 'branding' ? (
        <BrandingSettings organizationId={user?.organization_id ?? null} />
      ) : (
        <UsersPermissionsTab />
      )}
    </>
  );
}
