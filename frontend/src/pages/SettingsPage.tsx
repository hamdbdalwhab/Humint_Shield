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
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import toast from 'react-hot-toast';

import { diagnosticsApi } from '@/api/endpoints';
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

export function SettingsPage() {
  const { user } = useAuth();
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
        subtitle="Read-only runtime configuration, dependency health and deliverability checks."
      />

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
    </>
  );
}
