/**
 * Campaign detail: KPI cards, live recipient report, campaign-wide activity feed
 * and the full per-recipient dossier.
 *
 * The recipients table is intentionally dense: it shows the exact time of every
 * funnel step, the number of opens/clicks/submissions and the employee's current
 * risk score. Clicking any row opens the dossier with the complete ledger and the
 * values the employee typed.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Grid from '@mui/material/Grid';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Tabs from '@mui/material/Tabs';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import DownloadIcon from '@mui/icons-material/Download';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import DoneAllIcon from '@mui/icons-material/DoneAll';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ScheduleIcon from '@mui/icons-material/Schedule';
import SensorsIcon from '@mui/icons-material/Sensors';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { campaignsApi, reportsApi } from '@/api/endpoints';
import { InteractionTimeline } from '@/components/InteractionTimeline';
import { LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { RecipientDossierDialog } from '@/components/RecipientDossierDialog';
import { CampaignStatusBadge, EngagementStatusBadge } from '@/components/StatusBadge';
import { ThreatBadge } from '@/components/ThreatBadge';
import { StatCard } from '@/components/StatCard';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDateTime, formatPercent } from '@/lib/format';
import type { BehavioralCategory, CampaignEmployeeResult, DeliveryStatus } from '@/types';

const REFRESH_INTERVAL_MS = 5000;
const ACTIVITY_REFRESH_INTERVAL_MS = 10000;

const CATEGORY_META: Record<
  BehavioralCategory,
  { label: string; color: 'default' | 'info' | 'warning' | 'success' | 'error' }
> = {
  critical_risk: { label: 'Critical risk', color: 'error' },
  unaware: { label: 'Unaware', color: 'warning' },
  hesitant: { label: 'Hesitant', color: 'default' },
  competent: { label: 'Competent', color: 'success' },
};

function CategoryChip({ category }: { category: BehavioralCategory | null }) {
  if (!category) return null;
  const meta = CATEGORY_META[category];
  return <Chip size="small" variant="outlined" label={meta.label} color={meta.color} />;
}

const DELIVERY_LABELS: Record<DeliveryStatus, string> = {
  submitted: 'Submitted',
  accepted: 'Accepted',
  buffered: 'Buffered',
  delivered: 'Delivered',
  read: 'Read',
  failed: 'Failed',
  rejected: 'Rejected',
};

function DeliveryStatusBadge({
  status,
  error,
  failedAt,
}: {
  status: DeliveryStatus | null;
  error?: string | null;
  failedAt?: string | null;
}) {
  if (!status) return <Typography variant="caption" color="text.secondary">—</Typography>;
  if (status === 'read') {
    return (
      <Tooltip title={error || 'The recipient read the message on WhatsApp'}>
        <Chip
          size="small"
          color="info"
          variant="outlined"
          icon={<DoneAllIcon />}
          label={DELIVERY_LABELS[status]}
        />
      </Tooltip>
    );
  }
  if (status === 'delivered') {
    return (
      <Tooltip title={error || 'Delivery confirmed by the provider webhook'}>
        <Chip
          size="small"
          color="success"
          variant="outlined"
          icon={<CheckCircleOutlineIcon />}
          label={DELIVERY_LABELS[status]}
        />
      </Tooltip>
    );
  }
  if (status === 'failed' || status === 'rejected') {
    const failureTitle = error || (failedAt ? `Failed at ${formatDateTime(failedAt)}` : 'The provider rejected the message');
    return (
      <Tooltip title={failureTitle}>
        <Chip
          size="small"
          color="error"
          icon={<ErrorOutlineIcon />}
          label={DELIVERY_LABELS[status]}
        />
      </Tooltip>
    );
  }
  return (
    <Tooltip title="Waiting for the provider delivery receipt">
      <Chip
        size="small"
        color="default"
        variant="outlined"
        icon={<ScheduleIcon />}
        label={DELIVERY_LABELS[status]}
      />
    </Tooltip>
  );
}

const STATUS_OPTIONS = [
  { value: 'all', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'sent', label: 'Sent' },
  { value: 'opened', label: 'Opened' },
  { value: 'clicked', label: 'Clicked' },
  { value: 'submitted', label: 'Form submitted' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
];

export function CampaignDetailPage() {
  const { campaignId } = useParams<{ campaignId: string }>();
  const { organizationId } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [detailFor, setDetailFor] = useState<CampaignEmployeeResult | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [reportBusy, setReportBusy] = useState(false);

  const resultsQuery = useQuery({
    queryKey: ['campaign-results', organizationId, campaignId],
    queryFn: () => campaignsApi.results(organizationId as string, campaignId as string),
    enabled: Boolean(organizationId && campaignId),
    refetchInterval: REFRESH_INTERVAL_MS,
  });

  const activityQuery = useQuery({
    queryKey: ['campaign-activity', organizationId, campaignId],
    queryFn: () => campaignsApi.activity(organizationId as string, campaignId as string, 500),
    enabled: Boolean(organizationId && campaignId) && tab === 1,
    refetchInterval: ACTIVITY_REFRESH_INTERVAL_MS,
  });

  const employees = useMemo(() => {
    const rows = resultsQuery.data?.employees ?? [];
    const term = search.trim().toLowerCase();
    return rows.filter((row) => {
      if (statusFilter !== 'all' && row.status !== statusFilter) return false;
      if (!term) return true;
      return (
        row.name.toLowerCase().includes(term) ||
        row.email.toLowerCase().includes(term) ||
        (row.phone ?? '').toLowerCase().includes(term) ||
        (row.department ?? '').toLowerCase().includes(term)
      );
    });
  }, [resultsQuery.data, search, statusFilter]);

  async function handleExport() {
    if (!organizationId || !campaignId) return;
    try {
      const blob = await campaignsApi.exportCsv(organizationId, campaignId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `campaign_${campaignId}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function handleExecutiveReport() {
    if (!campaignId) return;
    setReportBusy(true);
    try {
      const blob = await reportsApi.executivePdf(campaignId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `executive_report_${campaignId}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success('Executive report downloaded');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setReportBusy(false);
    }
  }

  if (resultsQuery.isLoading) return <LoadingState label="Loading campaign…" />;
  if (resultsQuery.error) return <Alert severity="error">{errorMessage(resultsQuery.error)}</Alert>;
  if (!resultsQuery.data) return null;

  const { campaign, stats } = resultsQuery.data;
  const allEmployees = resultsQuery.data.employees;
  const isPhoneChannel = campaign.channel !== 'email';
  const deliveredCount = allEmployees.filter(
    (row) => row.delivery_status === 'delivered' || row.delivery_status === 'read',
  ).length;
  const readCount = allEmployees.filter((row) => row.delivery_status === 'read').length;
  const deliveredRate = stats.sent > 0 ? (deliveredCount / stats.sent) * 100 : 0;
  const readRate = stats.sent > 0 ? (readCount / stats.sent) * 100 : 0;

  return (
    <>
      <PageHeader
        title={campaign.name}
        subtitle={`Created ${formatDateTime(campaign.created_at)}${
          campaign.launched_at ? ` · launched ${formatDateTime(campaign.launched_at)}` : ''
        }`}
        actions={
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <CampaignStatusBadge status={campaign.status} />
            <Chip
              size="small"
              variant="outlined"
              label={
                campaign.channel === 'email'
                  ? 'Email'
                  : campaign.channel === 'sms'
                    ? 'SMS · Vonage'
                    : 'WhatsApp · Vonage'
              }
            />
            {campaign.status !== 'draft' ? (
              <Button
                variant="contained"
                color="success"
                startIcon={<SensorsIcon />}
                onClick={() => navigate(`/campaigns/${campaign.id}/live`)}
              >
                Live board
              </Button>
            ) : null}
            <Button
              variant="contained"
              color="secondary"
              startIcon={
                reportBusy ? (
                  <CircularProgress size={16} color="inherit" />
                ) : (
                  <PictureAsPdfIcon />
                )
              }
              onClick={handleExecutiveReport}
              disabled={reportBusy}
              aria-busy={reportBusy}
            >
              {reportBusy ? 'Generating PDF…' : 'Download Executive Report'}
            </Button>
            <Button variant="outlined" startIcon={<DownloadIcon />} onClick={handleExport}>
              Export CSV
            </Button>
          </Stack>
        }
      />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={2}>
          <StatCard label="Total" value={stats.total} />
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <StatCard label="Sent" value={stats.sent} helper={`${stats.failed} failed`} tone="primary" />
        </Grid>
        {isPhoneChannel ? (
          <>
            <Grid item xs={12} sm={6} md={2}>
              <StatCard
                label="Delivered"
                value={deliveredCount}
                helper={formatPercent(deliveredRate)}
                tone="success"
              />
            </Grid>
            <Grid item xs={12} sm={6} md={2}>
              <StatCard
                label="Read"
                value={readCount}
                helper={formatPercent(readRate)}
                tone="primary"
              />
            </Grid>
          </>
        ) : (
          <Grid item xs={12} sm={6} md={2}>
            <StatCard label="Opened" value={stats.opened} helper={formatPercent(stats.open_rate)} tone="primary" />
          </Grid>
        )}
        <Grid item xs={12} sm={6} md={2}>
          <StatCard label="Clicked" value={stats.clicked} helper={formatPercent(stats.click_rate)} tone="warning" />
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <StatCard
            label="Form submitted"
            value={stats.submitted}
            helper={formatPercent(stats.submission_rate)}
            tone="warning"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={2}>
          <StatCard
            label="Completed"
            value={stats.completed}
            helper={formatPercent(stats.completion_rate)}
            tone="success"
          />
        </Grid>
      </Grid>

      <Card>
        <Tabs
          value={tab}
          onChange={(_, value: number) => setTab(value)}
          sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}
        >
          <Tab label={`Recipients (${allEmployees.length})`} />
          <Tab label="Live activity" />
        </Tabs>

        {tab === 0 ? (
          <CardContent>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={2}
              alignItems={{ xs: 'stretch', sm: 'center' }}
              sx={{ mb: 2 }}
            >
              <TextField
                size="small"
                label="Search by name, email, phone or department"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ minWidth: 280 }}
              />
              <TextField
                size="small"
                select
                label="Status"
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                sx={{ minWidth: 180 }}
              >
                {STATUS_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
              <Box sx={{ flex: 1 }} />
              <Typography variant="caption" color="text.secondary">
                Auto-refreshing every {REFRESH_INTERVAL_MS / 1000}s · click a row for the full report
              </Typography>
            </Stack>

            {employees.length === 0 ? (
              <Typography color="text.secondary" variant="body2">
                {allEmployees.length === 0
                  ? 'No tracking records yet. Launch the campaign to send messages.'
                  : 'No recipient matches the current filters.'}
              </Typography>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Name</TableCell>
                      <TableCell>Email</TableCell>
                      {isPhoneChannel ? <TableCell>Phone</TableCell> : null}
                      <TableCell>Department</TableCell>
                      <TableCell align="center">Status</TableCell>
                      {isPhoneChannel ? <TableCell align="center">Delivery</TableCell> : null}
                      <TableCell>Opened</TableCell>
                      <TableCell>Clicked</TableCell>
                      <TableCell>Form shown</TableCell>
                      <TableCell>Submitted</TableCell>
                      <TableCell align="center">Score</TableCell>
                      <TableCell align="center">Threat</TableCell>
                      <TableCell align="center">Category</TableCell>
                      <TableCell align="center">Dossier</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {employees.map((row) => (
                      <TableRow
                        key={row.employee_id}
                        hover
                        sx={{ cursor: 'pointer' }}
                        onClick={() => setDetailFor(row)}
                      >
                        <TableCell>{row.name}</TableCell>
                        <TableCell>{row.email}</TableCell>
                        {isPhoneChannel ? (
                          <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                            {row.phone ?? '—'}
                          </TableCell>
                        ) : null}
                        <TableCell>{row.department ?? '—'}</TableCell>
                        <TableCell align="center">
                          <EngagementStatusBadge status={row.status} />
                        </TableCell>
                        {isPhoneChannel ? (
                          <TableCell align="center">
                            <DeliveryStatusBadge
                              status={row.delivery_status}
                              error={row.delivery_error}
                              failedAt={row.failed_at}
                            />
                          </TableCell>
                        ) : null}
                        <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                          {formatDateTime(row.opened_at)}
                          {row.open_count > 1 ? ` (${row.open_count}×)` : ''}
                        </TableCell>
                        <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                          {formatDateTime(row.clicked_at)}
                          {row.click_count > 1 ? ` (${row.click_count}×)` : ''}
                        </TableCell>
                        <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                          {formatDateTime(row.form_viewed_at)}
                        </TableCell>
                        <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                          {formatDateTime(row.submitted_at)}
                          {row.submission_count > 1 ? ` (${row.submission_count}×)` : ''}
                        </TableCell>
                        <TableCell align="center">
                          {row.immunity_score !== null ? row.immunity_score.toFixed(1) : '—'}
                        </TableCell>
                        <TableCell align="center">
                          <Stack alignItems="center" spacing={0.3}>
                            <ThreatBadge level={row.threat_level} />
                            <Typography variant="caption" color="text.secondary">
                              Elo {row.elo_score ?? '—'}
                            </Typography>
                          </Stack>
                        </TableCell>
                        <TableCell align="center">
                          <CategoryChip category={row.behavioral_category} />
                        </TableCell>
                        <TableCell align="center">
                          <Tooltip title="Open full dossier">
                            <IconButton
                              size="small"
                              aria-label={`Open dossier for ${row.name}`}
                              onClick={(event) => {
                                event.stopPropagation();
                                setDetailFor(row);
                              }}
                            >
                              <VisibilityIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </CardContent>
        ) : null}

        {tab === 1 ? (
          <CardContent>
            {activityQuery.isLoading ? <LoadingState label="Loading activity…" /> : null}
            {activityQuery.error ? (
              <Alert severity="error">{errorMessage(activityQuery.error)}</Alert>
            ) : null}
            {activityQuery.data ? (
              <>
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  sx={{ mb: 2 }}
                >
                  <Typography variant="h3" sx={{ fontSize: '1.05rem' }}>
                    Every recorded interaction
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {activityQuery.data.events.length} event(s) · refresh every{' '}
                    {ACTIVITY_REFRESH_INTERVAL_MS / 1000}s
                  </Typography>
                </Stack>
                <InteractionTimeline events={activityQuery.data.events} showEmployee />
              </>
            ) : null}
          </CardContent>
        ) : null}
      </Card>

      <RecipientDossierDialog
        open={Boolean(detailFor)}
        onClose={() => setDetailFor(null)}
        organizationId={organizationId as string}
        campaignId={campaignId as string}
        employeeId={detailFor?.employee_id ?? null}
        employeeName={detailFor?.name}
      />
    </>
  );
}
