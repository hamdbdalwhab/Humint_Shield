/**
 * Live campaign monitoring board.
 *
 * This is the screen an operator lands on the moment a campaign is launched:
 * one card per targeted employee, the current funnel status, every transition
 * timestamp to the second, the seconds between transitions, IP and device, and
 * a campaign-wide activity ticker.  The board polls the dedicated
 * ``/live`` endpoint every two seconds, so opens and clicks appear while the
 * recipient is still on the training page.
 */
import Alert from '@mui/material/Alert';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import DownloadIcon from '@mui/icons-material/Download';
import MarkEmailReadIcon from '@mui/icons-material/MarkEmailRead';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import PersonSearchIcon from '@mui/icons-material/PersonSearch';
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked';
import SyncIcon from '@mui/icons-material/Sync';
import VisibilityIcon from '@mui/icons-material/Visibility';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { keyframes } from '@emotion/react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';

import { campaignsApi } from '@/api/endpoints';
import { LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { RecipientDossierDialog } from '@/components/RecipientDossierDialog';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDuration, formatTime } from '@/lib/format';
import type { LiveBoard, LiveRecipient, LiveStatus } from '@/types';

type ChipColor = 'default' | 'info' | 'warning' | 'success' | 'error';

const pulse = keyframes`
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.82); }
`;

const spin = keyframes`
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
`;

const STATUS_META: Record<
  LiveStatus,
  { label: string; color: ChipColor; accent: string; hint: string }
> = {
  pending: { label: 'Pending', color: 'default', accent: '#9e9e9e', hint: 'Not sent yet' },
  sent: { label: 'Sent', color: 'info', accent: '#0288d1', hint: 'Email accepted by the mail server' },
  opened: { label: 'Opened', color: 'info', accent: '#1976d2', hint: 'Tracking pixel loaded' },
  clicked: { label: 'Clicked', color: 'warning', accent: '#ed6c02', hint: 'Training link opened' },
  form_viewed: { label: 'Form shown', color: 'warning', accent: '#f57c00', hint: 'Credential form displayed' },
  submitted: { label: 'Submitted', color: 'error', accent: '#d32f2f', hint: 'Credentials were entered' },
  completed: { label: 'Completed', color: 'success', accent: '#2e7d32', hint: 'Micro-training finished' },
  reported_safe: { label: 'Reported Safe', color: 'success', accent: '#FFD54F', hint: 'Employee reported the simulation safe' },
  failed: { label: 'Failed', color: 'error', accent: '#b71c1c', hint: 'The email could not be sent' },
  no_answer: {
    label: 'No answer',
    color: 'warning',
    accent: '#ef6c00',
    hint: 'The phone rang but nobody picked up before the carrier ended the call',
  },
};

const STATUS_ORDER: Record<LiveStatus, number> = {
  failed: 0,
  no_answer: 0,
  pending: 1,
  sent: 2,
  opened: 3,
  clicked: 4,
  form_viewed: 5,
  submitted: 6,
  completed: 7,
  reported_safe: 8,
};

const EVENT_TONES: Record<string, ChipColor> = {
  email_open: 'info',
  email_opened: 'info',
  link_click: 'warning',
  link_clicked: 'warning',
  form_viewed: 'warning',
  training_form_viewed: 'warning',
  form_submitted: 'error',
  credentials_submitted: 'error',
  phishing_reported: 'success',
  training_completed: 'success',
};

const STAGES: Array<{
  label: string;
  at: keyof LiveRecipient;
  delta: keyof LiveRecipient | null;
}> = [
  { label: 'Sent', at: 'sent_at', delta: null },
  { label: 'Delivered', at: 'delivered_at', delta: null },
  { label: 'Opened', at: 'opened_at', delta: 'seconds_to_open' },
  { label: 'Clicked', at: 'clicked_at', delta: 'seconds_to_click' },
  { label: 'Form shown', at: 'form_viewed_at', delta: 'seconds_to_form' },
  { label: 'Submitted', at: 'submitted_at', delta: 'seconds_to_submit' },
];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part.charAt(0).toUpperCase()).join('') || '?';
}

/** One KPI tile at the top of the board. */
function StatTile({
  label,
  value,
  detail,
  icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: ReactNode;
}) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center">
          <Typography variant="overline" color="text.secondary" sx={{ lineHeight: 1.2 }}>
            {label}
          </Typography>
          {icon}
        </Stack>
        <Typography variant="h4" sx={{ fontWeight: 700, lineHeight: 1.3 }}>
          {value}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block">
          {detail}
        </Typography>
      </CardContent>
    </Card>
  );
}

/** One employee card: identity, funnel rail, evidence and counters. */
function RecipientCard({
  recipient,
  flash,
  onOpen,
}: {
  recipient: LiveRecipient;
  flash: boolean;
  onOpen: () => void;
}) {
  const meta = STATUS_META[recipient.status];
  return (
    <Card
      role="button"
      tabIndex={0}
      aria-label={`Open the full record for ${recipient.name}`}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onOpen();
        }
      }}
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        borderTop: 4,
        borderColor: meta.accent,
        cursor: 'pointer',
        transition: 'box-shadow 200ms ease, transform 200ms ease',
        '&:hover': { boxShadow: 6, transform: 'translateY(-1px)' },
        ...(flash ? { boxShadow: `0 0 0 3px ${meta.accent}55` } : {}),
      }}
    >
      <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
        <Stack direction="row" spacing={1.25} alignItems="flex-start">
          <Avatar sx={{ bgcolor: meta.accent, width: 38, height: 38, fontSize: 15 }}>
            {initials(recipient.name)}
          </Avatar>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="subtitle2" noWrap title={recipient.name}>
              {recipient.name}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap display="block">
              {recipient.email}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap display="block">
              {[recipient.department, recipient.job_title].filter(Boolean).join(' · ') || '—'}
            </Typography>
          </Box>
          <Tooltip title={meta.hint}>
            <Chip size="small" label={meta.label} color={meta.color} />
          </Tooltip>
        </Stack>

        <Divider />

        <Stack spacing={0.35}>
          {STAGES.map((stage) => {
            const value = recipient[stage.at];
            const reached = typeof value === 'string' && value.length > 0;
            const delta = stage.delta ? recipient[stage.delta] : null;
            return (
              <Stack key={stage.label} direction="row" spacing={0.75} alignItems="center">
                {reached ? (
                  <CheckCircleIcon sx={{ fontSize: 15, color: 'success.main' }} />
                ) : (
                  <RadioButtonUncheckedIcon sx={{ fontSize: 15, color: 'divider' }} />
                )}
                <Typography
                  variant="caption"
                  sx={{ width: 76, color: reached ? 'text.primary' : 'text.disabled' }}
                >
                  {stage.label}
                </Typography>
                <Typography
                  variant="caption"
                  sx={{
                    fontFamily: 'monospace',
                    color: reached ? 'text.secondary' : 'text.disabled',
                  }}
                >
                  {reached ? formatTime(value as string) : '—'}
                </Typography>
                {typeof delta === 'number' ? (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`+${formatDuration(delta)}`}
                    sx={{ height: 17, '& .MuiChip-label': { px: 0.6, fontSize: 10 } }}
                  />
                ) : null}
              </Stack>
            );
          })}
        </Stack>

        <Box sx={{ flex: 1 }} />

        <Divider />

        <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
          <Chip size="small" variant="outlined" label={`opens ${recipient.open_count}`} />
          <Chip size="small" variant="outlined" label={`clicks ${recipient.click_count}`} />
          {recipient.submission_count > 0 ? (
            <Chip size="small" color="error" label={`submissions ${recipient.submission_count}`} />
          ) : null}
          {recipient.reported ? (
            <Chip size="small" color="success" label="reported" icon={<WarningAmberIcon />} />
          ) : null}
          {recipient.password_length !== null ? (
            <Chip size="small" color="warning" label={`password ${recipient.password_length} chars`} />
          ) : null}
        </Stack>

        {recipient.device_summary || recipient.geo_label || recipient.source_path ? (
          <Box
            sx={{
              bgcolor: 'action.hover',
              borderRadius: 1,
              px: 0.9,
              py: 0.6,
              display: 'grid',
              gap: 0.15,
            }}
          >
            {recipient.device_summary ? (
              <Typography variant="caption" noWrap title={recipient.device_summary} display="block">
                🖥 {recipient.device_summary}
              </Typography>
            ) : null}
            {[recipient.device_hostname, recipient.device_username].filter(Boolean).length > 0 ? (
              <Typography variant="caption" color="text.secondary" noWrap display="block">
                👤 {[recipient.device_hostname, recipient.device_username].filter(Boolean).join(' · ')}
              </Typography>
            ) : null}
            {recipient.geo_label ? (
              <Typography variant="caption" color="text.secondary" noWrap display="block">
                📍 {recipient.geo_label}
              </Typography>
            ) : null}
            {recipient.source_path ? (
              <Typography
                variant="caption"
                color="text.secondary"
                noWrap
                title={recipient.source_path}
                display="block"
                sx={{ fontFamily: 'monospace', fontSize: 10.5, direction: 'ltr', textAlign: 'right' }}
              >
                📄 {recipient.source_path}
              </Typography>
            ) : null}
            {!recipient.telemetry_received ? (
              <Typography variant="caption" color="warning.main" noWrap display="block">
                device profile pending — the document could not reach the server yet
              </Typography>
            ) : null}
          </Box>
        ) : null}

        <Stack direction="row" spacing={0.75} alignItems="center" justifyContent="space-between">
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" noWrap display="block">
              {recipient.last_event_label ?? 'No activity yet'}
              {recipient.seconds_since_last_event !== null
                ? ` · ${formatDuration(recipient.seconds_since_last_event)} ago`
                : ''}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap display="block">
              {recipient.last_ip_address ?? 'IP unknown'}
              {recipient.last_user_agent ? ` · ${recipient.last_user_agent.slice(0, 42)}` : ''}
            </Typography>
          </Box>
          <Tooltip title="Full record">
            <Button
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                onOpen();
              }}
              endIcon={<OpenInNewIcon fontSize="small" />}
            >
              Details
            </Button>
          </Tooltip>
        </Stack>
      </CardContent>
    </Card>
  );
}

export function LiveBoardPage() {
  const { campaignId } = useParams<{ campaignId: string }>();
  const { organizationId } = useAuth();
  const navigate = useNavigate();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | LiveStatus>('all');
  const [detailFor, setDetailFor] = useState<LiveRecipient | null>(null);
  const [flash, setFlash] = useState<Record<string, boolean>>({});
  const previousStatuses = useRef<Map<string, LiveStatus>>(new Map());

  const boardQuery = useQuery({
    queryKey: ['campaign-live', organizationId, campaignId],
    queryFn: () => campaignsApi.live(organizationId as string, campaignId as string),
    enabled: Boolean(organizationId && campaignId),
    refetchInterval: 2000,
    refetchIntervalInBackground: true,
  });

  const board: LiveBoard | undefined = boardQuery.data;

  useEffect(() => {
    if (!board) return undefined;
    const changed: Record<string, boolean> = {};
    for (const recipient of board.recipients) {
      const before = previousStatuses.current.get(recipient.employee_id);
      if (before && before !== recipient.status) changed[recipient.employee_id] = true;
      previousStatuses.current.set(recipient.employee_id, recipient.status);
    }
    if (Object.keys(changed).length === 0) return undefined;
    setFlash(changed);
    const timer = setTimeout(() => setFlash({}), 4000);
    return () => clearTimeout(timer);
  }, [board]);

  const recipients = useMemo(() => {
    const rows = board?.recipients ?? [];
    const query = search.trim().toLowerCase();
    return rows
      .filter((row) => statusFilter === 'all' || row.status === statusFilter)
      .filter((row) => {
        if (!query) return true;
        return [row.name, row.email, row.department ?? '', row.job_title ?? ''].some((value) =>
          value.toLowerCase().includes(query),
        );
      })
      .sort((a, b) => {
        const byStatus = STATUS_ORDER[b.status] - STATUS_ORDER[a.status];
        if (byStatus !== 0) return byStatus;
        return (b.last_event_at ?? '').localeCompare(a.last_event_at ?? '');
      });
  }, [board, search, statusFilter]);

  async function handleExport() {
    if (!organizationId || !campaignId) return;
    const blob = await campaignsApi.exportCsv(organizationId, campaignId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `campaign_${campaignId}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  if (!campaignId) {
    return <Alert severity="error">No campaign selected.</Alert>;
  }

  if (boardQuery.isLoading) {
    return <LoadingState label="Connecting to the live board…" />;
  }

  if (boardQuery.error || !board) {
    return (
      <Alert severity="error">
        {boardQuery.error ? errorMessage(boardQuery.error) : 'The live board is unavailable.'}
      </Alert>
    );
  }

  const { campaign, summary } = board;
  const lastUpdated = boardQuery.dataUpdatedAt
    ? formatTime(new Date(boardQuery.dataUpdatedAt).toISOString())
    : '—';

  return (
    <>
      <Button
        size="small"
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/campaigns')}
        sx={{ mb: 1 }}
      >
        Campaigns
      </Button>

      <PageHeader
        title={campaign.name}
        subtitle={`Launched ${formatTime(campaign.launched_at)} · running for ${formatDuration(
          campaign.elapsed_seconds,
        )} · template ${campaign.template_name ?? '—'}`}
        actions={
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button
              variant="outlined"
              startIcon={<DownloadIcon />}
              onClick={() => void handleExport()}
            >
              Export CSV
            </Button>
            <Button
              variant="outlined"
              startIcon={<PersonSearchIcon />}
              onClick={() => navigate(`/campaigns/${campaign.id}`)}
            >
              Classic report
            </Button>
          </Stack>
        }
      />

      
      {campaign.channel === 'qr' ? (
        <Alert
          severity="info"
          sx={{ mb: 2, alignItems: 'center', fontWeight: 600 }}
          action={
            <Button
              color="primary"
              variant="contained"
              size="small"
              onClick={() => navigate(`/campaigns/${campaign.id}`)}
              sx={{ fontWeight: 800 }}
            >
              فتح الرادار المباشر والملصق
            </Button>
          }
        >
          هذه حملة QR (Generic Lure). مراقبة عمليات المسح وبصمات الأجهزة والبيانات المدخلة في الوقت الفعلي متوفرة في صفحة الحملة والرادار المباشر.
        </Alert>
      ) : null}

      <Card
        sx={{
          mb: 2,
          borderLeft: 5,
          borderColor: 'success.main',
          bgcolor: 'background.paper',
        }}
      >
        <CardContent sx={{ py: 1.25, '&:last-child': { pb: 1.25 } }}>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1.5}
            alignItems={{ sm: 'center' }}
            justifyContent="space-between"
          >
            <Stack direction="row" spacing={1.25} alignItems="center" flexWrap="wrap" useFlexGap>
              <Box
                sx={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  bgcolor: 'success.main',
                  animation: `${pulse} 1.4s ease-in-out infinite`,
                }}
              />
              <Typography variant="subtitle2" sx={{ letterSpacing: 1 }}>
                LIVE MONITORING
              </Typography>
              <Chip
                size="small"
                variant="outlined"
                color="success"
                label={`${summary.active_last_5m} active in the last 5 min`}
              />
              <Chip
                size="small"
                variant="outlined"
                label={`${summary.sent}/${summary.total} emails sent`}
              />
              {summary.failed > 0 ? (
                <Chip size="small" color="error" label={`${summary.failed} failed`} />
              ) : null}
            </Stack>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography variant="caption" color="text.secondary">
                Updated {lastUpdated} · auto-refresh every 2s
              </Typography>
              <SyncIcon
                fontSize="small"
                sx={{
                  color: 'text.secondary',
                  animation: boardQuery.isFetching ? `${spin} 1s linear infinite` : 'none',
                }}
              />
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        <Grid item xs={6} md={2}>
          <StatTile
            label="Sent"
            value={`${summary.sent}/${summary.total}`}
            detail={summary.failed > 0 ? `${summary.failed} failed` : 'all accepted'}
            icon={<MarkEmailReadIcon color="primary" fontSize="small" />}
          />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatTile
            label="Opened"
            value={String(summary.opened)}
            detail={`${summary.open_rate}% · avg ${formatDuration(summary.avg_seconds_to_open)}`}
            icon={<VisibilityIcon color="info" fontSize="small" />}
          />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatTile
            label="Clicked"
            value={String(summary.clicked)}
            detail={`${summary.click_rate}% · avg ${formatDuration(summary.avg_seconds_to_click)}`}
            icon={<OpenInNewIcon color="warning" fontSize="small" />}
          />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatTile
            label="Form shown"
            value={String(summary.form_viewed)}
            detail={`${summary.form_view_rate}% saw the page`}
            icon={<VisibilityIcon color="warning" fontSize="small" />}
          />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatTile
            label="Submitted"
            value={String(summary.submitted)}
            detail={`${summary.submission_rate}% · avg ${formatDuration(summary.avg_seconds_to_submit)}`}
            icon={<WarningAmberIcon color="error" fontSize="small" />}
          />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatTile
            label="Reported"
            value={String(summary.reported)}
            detail="flagged as phishing"
            icon={<CheckCircleIcon color="success" fontSize="small" />}
          />
        </Grid>
      </Grid>

      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
            <TextField
              size="small"
              fullWidth
              placeholder="Search by name, email, department or job title…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <TextField
              select
              size="small"
              label="Status"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as 'all' | LiveStatus)}
              sx={{ minWidth: 190 }}
            >
              <MenuItem value="all">All statuses ({board.recipients.length})</MenuItem>
              {(Object.keys(STATUS_META) as LiveStatus[]).map((status) => {
                const count = board.recipients.filter((row) => row.status === status).length;
                return (
                  <MenuItem key={status} value={status}>
                    {STATUS_META[status].label} ({count})
                  </MenuItem>
                );
              })}
            </TextField>
          </Stack>
        </CardContent>
      </Card>

      {campaign.status === 'draft' ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          This campaign is still a draft. Launch it to start tracking recipients.
        </Alert>
      ) : null}

      {recipients.length === 0 ? (
        <Card>
          <CardContent>
            <Typography variant="body2" color="text.secondary">
              No recipients match the current filter.
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <Grid container spacing={2}>
          {recipients.map((recipient) => (
            <Grid item xs={12} sm={6} lg={4} xl={3} key={recipient.employee_id}>
              <RecipientCard
                recipient={recipient}
                flash={Boolean(flash[recipient.employee_id])}
                onOpen={() => setDetailFor(recipient)}
              />
            </Grid>
          ))}
        </Grid>
      )}

      <Card sx={{ mt: 3 }}>
        <CardContent>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
            <Typography variant="h3" sx={{ fontSize: '1.05rem' }}>
              Live activity
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {board.recent_events.length} most recent event
              {board.recent_events.length === 1 ? '' : 's'}
            </Typography>
          </Stack>
          {board.recent_events.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No interactions yet. Opens and clicks appear here the moment they happen.
            </Typography>
          ) : (
            <Stack divider={<Divider flexItem />} spacing={0.75}>
              {board.recent_events.slice(0, 12).map((event) => (
                <Stack
                  key={event.id}
                  direction="row"
                  spacing={1}
                  alignItems="center"
                  sx={{ py: 0.25 }}
                >
                  <Chip
                    size="small"
                    color={EVENT_TONES[event.event_type] ?? 'default'}
                    label={event.label}
                    sx={{ minWidth: 150 }}
                  />
                  <Typography variant="body2" sx={{ flex: 1 }} noWrap>
                    {event.employee_name}
                    {event.ip_address ? ` · ${event.ip_address}` : ''}
                  </Typography>
                  <Typography
                    variant="caption"
                    sx={{ fontFamily: 'monospace' }}
                    color="text.secondary"
                  >
                    {formatTime(event.occurred_at)}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ minWidth: 86, textAlign: 'right' }}
                  >
                    {event.seconds_ago < 60
                      ? `${Math.max(1, Math.round(event.seconds_ago))}s ago`
                      : `${formatDuration(event.seconds_ago)} ago`}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <RecipientDossierDialog
        open={detailFor !== null}
        onClose={() => setDetailFor(null)}
        organizationId={organizationId as string}
        campaignId={campaign.id}
        employeeId={detailFor?.employee_id ?? null}
        employeeName={detailFor?.name}
      />
    </>
  );
}
