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
import Typography from '@mui/material/Typography';
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { brandingApi, diagnosticsApi } from '@/api/endpoints';
import { LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';

const COMPLIANCE = [
  'ISO/IEC 27001 A.7.2.2 — information security awareness, education and training.',
  'NIST SP 800-50 and SP 800-53 AT-2 — literacy training and awareness.',
  'PCI-DSS v4.0 requirement 12.6 — security awareness program.',
  'HIPAA Security Rule 164.308(a)(5) — workforce security awareness training.',
  'GDPR Article 32 — security of processing, including staff awareness.',
];

/** Small helper that renders a boolean dependency state as a chip. */
function StateChip({ ok, label }: { ok: boolean; label: string }) {
  return <Chip size="small" label={label} color={ok ? 'success' : 'error'} variant="outlined" />;
}

function BrandingSettings({ organizationId }: { organizationId: string | null }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [companyName, setCompanyName] = useState('');
  const [primaryColor, setPrimaryColor] = useState('#0F6CBD');
  const [supportEmail, setSupportEmail] = useState('');
  const canEdit = user?.role === 'admin' || user?.role === 'manager';

  const brandingQuery = useQuery({
    queryKey: ['branding', organizationId],
    queryFn: () => brandingApi.get(organizationId as string),
    enabled: Boolean(organizationId),
  });

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
    return <Alert severity="warning">No organization is attached to this account.</Alert>;
  }
  if (brandingQuery.isLoading) return <LoadingState label="Loading branding…" />;
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
              Organization branding
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              New templates inherit this identity automatically. Existing templates can override
              the button colour inside the visual editor.
            </Typography>
            <Stack spacing={2}>
              <TextField
                label="Company name"
                fullWidth
                value={companyName}
                onChange={(event) => setCompanyName(event.target.value)}
                disabled={!canEdit || busy}
                helperText="Used in the footer and in {{company_name}} merge tags."
              />
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                <TextField
                  label="Primary brand colour"
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
                  label="Support email"
                  type="email"
                  fullWidth
                  value={supportEmail}
                  onChange={(event) => setSupportEmail(event.target.value)}
                  disabled={!canEdit || busy}
                  helperText="Shown in the email footer."
                />
              </Stack>
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 1 }}>
                  Logo (PNG, JPEG, GIF or WebP — max 2 MB)
                </Typography>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap', gap: 1 }}>
                  <Button
                    component="label"
                    variant="outlined"
                    disabled={!canEdit || busy}
                    sx={{ position: 'relative', overflow: 'hidden' }}
                  >
                    {logoMutation.isPending ? 'Uploading…' : 'Upload logo'}
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
                      Remove logo
                    </Button>
                  ) : null}
                </Stack>
              </Box>
              <Box>
                <Button
                  variant="contained"
                  disabled={!canEdit || busy || !companyName.trim()}
                  startIcon={updateMutation.isPending ? <CircularProgress size={16} color="inherit" /> : null}
                  onClick={() => updateMutation.mutate()}
                >
                  Save branding
                </Button>
                {!canEdit ? (
                  <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', mt: 1 }}>
                    Only administrators and managers can change organization branding.
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
              Live brand preview
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
              This preview uses the same live values injected by the email renderer.
            </Typography>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('tab') === 'branding' ? 1 : 0;
  const [testEmail, setTestEmail] = useState(user?.email ?? '');

  const configQuery = useQuery({
    queryKey: ['runtime-config'],
    queryFn: () => diagnosticsApi.config(),
  });

  const healthQuery = useQuery({
    queryKey: ['diagnostics-health'],
    queryFn: () => diagnosticsApi.health(),
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

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Organization branding, runtime configuration, dependency health and deliverability checks."
      />

      <Tabs
        value={tab}
        onChange={(_event, value: number) => {
          if (value === 1) setSearchParams({ tab: 'branding' });
          else setSearchParams({});
        }}
        sx={{ mb: 2 }}
      >
        <Tab label="Runtime & diagnostics" />
        <Tab label="Branding" />
      </Tabs>

      {tab === 0 ? (
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                Account
              </Typography>
              <Stack spacing={1}>
                <Typography variant="body2">
                  <strong>Username:</strong> {user?.username ?? '—'}
                </Typography>
                <Typography variant="body2">
                  <strong>Email:</strong> {user?.email ?? '—'}
                </Typography>
                <Typography variant="body2">
                  <strong>Role:</strong> {user?.role ?? '—'}
                </Typography>
                <Typography variant="body2">
                  <strong>Organization:</strong> {user?.organization_id ?? '—'}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                Runtime configuration
              </Typography>
              {configQuery.isLoading ? (
                <LoadingState label="Loading configuration…" />
              ) : configQuery.error ? (
                <Alert severity="error">{errorMessage(configQuery.error)}</Alert>
              ) : configQuery.data ? (
                <Stack spacing={1}>
                  <Typography variant="body2">
                    <strong>Environment:</strong> {configQuery.data.environment}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Base URL:</strong> {configQuery.data.base_url}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Frontend URL:</strong> {configQuery.data.frontend_url}
                  </Typography>
                  <Typography variant="body2">
                    <strong>Sender:</strong> {configQuery.data.from_name} &lt;
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
                Dependency health
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
                Email deliverability test
              </Typography>
              <Stack spacing={2}>
                <Typography variant="body2" color="text.secondary">
                  Dispatch a single authentication message through the active transport (Brevo or
                  SMTP) to confirm the sender identity and outbound path are correct.
                </Typography>
                <TextField
                  label="Destination address"
                  type="email"
                  fullWidth
                  value={testEmail}
                  onChange={(event) => setTestEmail(event.target.value)}
                />
                <Box>
                  <Button
                    variant="contained"
                    disabled={testMutation.isPending || testEmail.length < 3}
                    startIcon={testMutation.isPending ? <CircularProgress size={18} color="inherit" /> : null}
                    onClick={() => testMutation.mutate(testEmail)}
                  >
                    Send test email
                  </Button>
                </Box>

                <Divider flexItem />

                <Stack spacing={1.5}>
                  <Typography variant="subtitle2">Delivery configuration</Typography>
                  <Typography variant="body2" color="text.secondary">
                    Brevo blocks requests from addresses that are not on the account allowlist.
                    Check the transport and, when Brevo is selected, find the exact address to
                    authorise.
                  </Typography>
                  <Box>
                    <Button
                      variant="outlined"
                      disabled={verifyMutation.isPending}
                      startIcon={
                        verifyMutation.isPending ? <CircularProgress size={18} color="inherit" /> : null
                      }
                      onClick={() => verifyMutation.mutate()}
                    >
                      Check delivery now
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
                Vonage SMS &amp; WhatsApp
              </Typography>
              {configQuery.isLoading ? (
                <LoadingState label="Loading delivery configuration..." />
              ) : configQuery.error ? (
                <Alert severity="error">{errorMessage(configQuery.error)}</Alert>
              ) : configQuery.data ? (
                <Stack spacing={1.5}>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
                    <StateChip
                      ok={Boolean(configQuery.data.vonage_sms_configured)}
                      label={`SMS: ${configQuery.data.vonage_sms_configured ? 'ready' : 'not configured'}`}
                    />
                    <StateChip
                      ok={Boolean(configQuery.data.vonage_whatsapp_configured)}
                      label={`WhatsApp: ${configQuery.data.vonage_whatsapp_configured ? 'ready' : 'not configured'}`}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      color={configQuery.data.vonage_application_configured ? 'success' : 'default'}
                      label={
                        configQuery.data.vonage_application_configured
                          ? 'WhatsApp JWT application'
                          : 'API key/secret auth'
                      }
                    />
                  </Stack>
                  <Typography variant="body2">
                    <strong>SMS sender:</strong> {configQuery.data.vonage_sms_from || 'not set'}
                  </Typography>
                  <Typography variant="body2">
                    <strong>WhatsApp sender:</strong>{' '}
                    {configQuery.data.vonage_whatsapp_from || 'not set'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Credentials stay in <code>backend/.env</code> and are never sent to the browser.
                    Configure these callback URLs in the Vonage dashboard so delivery and read
                    receipts can update campaign results:
                  </Typography>
                  <Stack spacing={0.5}>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                      SMS DLR: {configQuery.data.base_url.replace(/\/+$/, '')}
                      {configQuery.data.vonage_webhook_paths?.sms_dlr ?? ''}
                    </Typography>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                      WhatsApp status: {configQuery.data.base_url.replace(/\/+$/, '')}
                      {configQuery.data.vonage_webhook_paths?.whatsapp_status ?? ''}
                    </Typography>
                  </Stack>
                  <Typography variant="caption" color="text.secondary">
                    SMS callbacks include the per-message callback URL automatically. WhatsApp
                    status callbacks belong to the Vonage application linked to the sender.
                  </Typography>
                </Stack>
              ) : null}
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                Compliance basis
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
      ) : (
        <BrandingSettings organizationId={user?.organization_id ?? null} />
      )}
    </>
  );
}
