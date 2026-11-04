/**
 * Campaign detail: KPI cards, live recipient report, campaign-wide activity feed
 * and the full per-recipient dossier.
 *
 * The recipients table is intentionally dense: it shows the exact time of every
 * funnel step, the number of opens/clicks/submissions and the employee's current
 * risk score. Clicking any row opens the dossier with the complete ledger and the
 * values the employee typed.
 */
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Divider from '@mui/material/Divider';
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
import CodeIcon from '@mui/icons-material/Code';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import PersonAddAlt1Icon from '@mui/icons-material/PersonAddAlt1';
import QrCode2Icon from '@mui/icons-material/QrCode2';
import UsbIcon from '@mui/icons-material/Usb';
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
import type {
  BehavioralCategory,
  CampaignEmployeeResult,
  DeliveryStatus,
  QRScan,
} from '@/types';

const REFRESH_INTERVAL_MS = 5000;
const ACTIVITY_REFRESH_INTERVAL_MS = 10000;

function deviceSummary(scan: QRScan): string {
  const fp = scan.fingerprint ?? {};
  const parts: string[] = [];
  const screen = fp.screen ?? fp.viewport;
  if (screen) parts.push(String(screen));
  if (fp.cpu_cores) parts.push(`${fp.cpu_cores} cores`);
  if (fp.device_memory_gb) parts.push(`${fp.device_memory_gb}GB RAM`);
  if (fp.timezone) parts.push(String(fp.timezone));
  if (fp.webgl_renderer) parts.push(String(fp.webgl_renderer).slice(0, 48));
  if (!parts.length && scan.user_agent) parts.push(scan.user_agent.slice(0, 48));
  return parts.join(' · ') || '—';
}

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
  available: 'Available',
  failed: 'Failed',
  rejected: 'Rejected',
};

const CHANNEL_CHIPS: Record<string, string> = {
  email: 'Email',
  sms: 'SMS · Vonage',
  whatsapp: 'WhatsApp · Vonage',
  qr: 'QR · Quishing',
  vishing: 'Vishing · Call',
  pretexting: 'Pretexting · Chat',
  usb: 'USB · Drop',
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
  if (status === 'available') {
    return (
      <Tooltip title={error || 'The simulation is ready for manual delivery'}>
        <Chip
          size="small"
          color="info"
          variant="outlined"
          icon={<CheckCircleOutlineIcon />}
          label={DELIVERY_LABELS[status]}
        />
      </Tooltip>
    );
  }
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
  const [qrBusy, setQrBusy] = useState(false);
  const [usbBusy, setUsbBusy] = useState(false);
  const [usbHtmlBusy, setUsbHtmlBusy] = useState(false);
  const [copiedEmployeeId, setCopiedEmployeeId] = useState<string | null>(null);
  const [assignScan, setAssignScan] = useState<QRScan | null>(null);
  const [assignEmployeeId, setAssignEmployeeId] = useState('');
  const [assignBusy, setAssignBusy] = useState(false);

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

  const scansQuery = useQuery({
    queryKey: ['campaign-scans', campaignId],
    queryFn: () => campaignsApi.getCampaignScans(campaignId as string),
    enabled: Boolean(campaignId),
    refetchInterval: REFRESH_INTERVAL_MS,
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

  async function handleQrPosters() {
    if (!campaignId) return;
    setQrBusy(true);
    try {
      const blob = await campaignsApi.generateQrPosters(campaignId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `campaign-${campaignId}-poster.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success('Campaign poster downloaded');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setQrBusy(false);
    }
  }

  async function handleAssignScan() {
    if (!organizationId || !campaignId || !assignScan || !assignEmployeeId) return;
    setAssignBusy(true);
    try {
      const result = await campaignsApi.assignScan(
        organizationId,
        campaignId,
        assignScan.id,
        assignEmployeeId,
      );
      toast.success(result.message || 'تم ربط المسح بالموظف.');
      setAssignScan(null);
      setAssignEmployeeId('');
      await resultsQuery.refetch();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setAssignBusy(false);
    }
  }

  async function handleUsbPdf() {
    if (!campaignId) return;
    setUsbBusy(true);
    try {
      const blob = await campaignsApi.generateUsbPdf(campaignId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'راتب_الشهر_القادم.pdf';
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success('USB awareness document downloaded');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setUsbBusy(false);
    }
  }

  async function handleUsbHtml() {
    if (!campaignId) return;
    setUsbHtmlBusy(true);
    try {
      const blob = await campaignsApi.generateUsbHtml(campaignId);
      const recipientCount = resultsQuery.data?.employees.length ?? 0;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download =
        recipientCount <= 1 ? 'الرواتب_السرية.html' : 'usb_html_pack.zip';
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast.success(
        recipientCount <= 1
          ? 'USB HTML awareness file downloaded'
          : 'USB HTML pack downloaded (one file per recipient)',
      );
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setUsbHtmlBusy(false);
    }
  }

  if (resultsQuery.isLoading) return <LoadingState label="Loading campaign…" />;
  if (resultsQuery.error) return <Alert severity="error">{errorMessage(resultsQuery.error)}</Alert>;
  if (!resultsQuery.data) return null;

  const { campaign, stats } = resultsQuery.data;
  const allEmployees = resultsQuery.data.employees;
  const scans = scansQuery.data ?? resultsQuery.data.scans ?? [];
  const isPhoneChannel = campaign.channel === 'sms' || campaign.channel === 'whatsapp';
  const isQrChannel = campaign.channel === 'qr';
  const isUsbChannel = campaign.channel === 'usb';
  const isVishingChannel = campaign.channel === 'vishing';
  const isPretextingChannel = campaign.channel === 'pretexting';
  const isLinkChannel = isVishingChannel || isPretextingChannel;
  const isManualChannel =
    isQrChannel || isUsbChannel || isVishingChannel || isPretextingChannel;

  async function handleCopySimulationLink(row: CampaignEmployeeResult) {
    if (!row.tracking_uuid) {
      toast.error('This recipient has no tracking link yet. Launch the campaign first.');
      return;
    }
    const path = isVishingChannel
      ? `/simulation/vishing/${row.tracking_uuid}`
      : `/simulation/ceo/${row.tracking_uuid}`;
    const url = new URL(path, window.location.origin).toString();
    try {
      await navigator.clipboard.writeText(url);
      setCopiedEmployeeId(row.employee_id);
      toast.success(`Simulation link copied for ${row.name}`);
      window.setTimeout(() => setCopiedEmployeeId(null), 1600);
    } catch {
      toast(url, { icon: '🔗' });
    }
  }
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
              label={CHANNEL_CHIPS[campaign.channel] ?? campaign.channel}
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
            {isQrChannel ? (
              <Button
                variant="contained"
                color="primary"
                startIcon={
                  qrBusy ? <CircularProgress size={16} color="inherit" /> : <QrCode2Icon />
                }
                onClick={handleQrPosters}
                disabled={qrBusy}
                aria-busy={qrBusy}
              >
                {qrBusy ? 'Generating poster...' : 'Download Campaign Poster'}
              </Button>
            ) : null}
            {isUsbChannel ? (
              <>
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={
                    usbHtmlBusy ? (
                      <CircularProgress size={16} color="inherit" />
                    ) : (
                      <CodeIcon />
                    )
                  }
                  onClick={handleUsbHtml}
                  disabled={usbHtmlBusy}
                  aria-busy={usbHtmlBusy}
                >
                  {usbHtmlBusy ? 'Generating HTML…' : 'Download USB HTML'}
                </Button>
                <Button
                  variant="outlined"
                  color="primary"
                  startIcon={
                    usbBusy ? <CircularProgress size={16} color="inherit" /> : <UsbIcon />
                  }
                  onClick={handleUsbPdf}
                  disabled={usbBusy}
                  aria-busy={usbBusy}
                >
                  {usbBusy ? 'Generating document…' : 'Download USB PDF'}
                </Button>
              </>
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
          <StatCard
            label={isManualChannel ? 'Prepared' : 'Sent'}
            value={stats.sent}
            helper={
              isQrChannel
                ? `${stats.total} posters`
                : isUsbChannel
                  ? `${stats.total} documents`
                  : `${stats.failed} failed`
            }
            tone="primary"
          />
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
            <StatCard
              label={isQrChannel ? 'Scanned' : 'Opened'}
              value={isQrChannel || isUsbChannel ? stats.clicked : stats.opened}
              helper={formatPercent(
                isQrChannel || isUsbChannel ? stats.click_rate : stats.open_rate,
              )}
              tone="primary"
            />
          </Grid>
        )}
        {!isManualChannel ? (
          <Grid item xs={12} sm={6} md={2}>
            <StatCard label="Clicked" value={stats.clicked} helper={formatPercent(stats.click_rate)} tone="warning" />
          </Grid>
        ) : null}
        {!isUsbChannel ? (
          <Grid item xs={12} sm={6} md={2}>
            <StatCard
              label="Form submitted"
              value={stats.submitted}
              helper={formatPercent(stats.submission_rate)}
              tone="warning"
            />
          </Grid>
        ) : null}
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
          {isQrChannel ? <Tab label={`Live scans — الرادار (${scans.length})`} /> : null}
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
                      <TableCell>{isUsbChannel ? 'USB opened' : 'Opened'}</TableCell>
                      {!isUsbChannel ? <TableCell>Clicked</TableCell> : null}
                      {!isUsbChannel ? <TableCell>Form shown</TableCell> : null}
                      {!isUsbChannel ? <TableCell>Submitted</TableCell> : null}
                      <TableCell align="center">Score</TableCell>
                      <TableCell align="center">Threat</TableCell>
                      <TableCell align="center">Category</TableCell>
                      {isLinkChannel ? (
                        <TableCell align="center">Simulation link</TableCell>
                      ) : null}
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
                        {!isUsbChannel ? (
                          <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                            {formatDateTime(row.clicked_at)}
                            {row.click_count > 1 ? ` (${row.click_count}×)` : ''}
                          </TableCell>
                        ) : null}
                        {!isUsbChannel ? (
                          <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                            {formatDateTime(row.form_viewed_at)}
                          </TableCell>
                        ) : null}
                        {!isUsbChannel ? (
                          <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                            {formatDateTime(row.submitted_at)}
                            {row.submission_count > 1 ? ` (${row.submission_count}×)` : ''}
                          </TableCell>
                        ) : null}
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
                        {isLinkChannel ? (
                          <TableCell align="center">
                            <Tooltip
                              title={
                                copiedEmployeeId === row.employee_id
                                  ? 'Copied'
                                  : 'Copy the unique simulation link'
                              }
                            >
                              <span>
                                <IconButton
                                  size="small"
                                  color={copiedEmployeeId === row.employee_id ? 'success' : 'primary'}
                                  aria-label={`Copy simulation link for ${row.name}`}
                                  disabled={!row.tracking_uuid}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void handleCopySimulationLink(row);
                                  }}
                                >
                                  {copiedEmployeeId === row.employee_id ? (
                                    <CheckIcon fontSize="small" />
                                  ) : (
                                    <ContentCopyIcon fontSize="small" />
                                  )}
                                </IconButton>
                              </span>
                            </Tooltip>
                          </TableCell>
                        ) : null}
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
        {tab === 2 && isQrChannel ? (
          <CardContent>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              justifyContent="space-between"
              alignItems={{ xs: 'stretch', sm: 'center' }}
              sx={{ mb: 2 }}
            >
              <Box>
                <Typography variant="h3" sx={{ fontSize: '1.05rem' }}>
                  الرادار — Live scans
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  كل إرسال لنموذج الدخول، بما في ذلك الهويات غير المعروفة · تحديث كل{' '}
                  {REFRESH_INTERVAL_MS / 1000} ثانية
                </Typography>
              </Box>
              <Chip
                color={scans.some((scan) => !scan.employee_id) ? 'warning' : 'success'}
                label={`${scans.filter((scan) => !scan.employee_id).length} غير معروف`}
              />
            </Stack>
            {scans.length === 0 ? (
              <Box sx={{ p: 4, textAlign: 'center', bgcolor: 'action.hover', borderRadius: 2 }}>
                <Typography variant="body1" sx={{ fontWeight: 700, mb: 1 }}>
                  بانتظار المسحات الأولى (Live Radar Active)
                </Typography>
                <Typography color="text.secondary" variant="body2">
                  لا توجد مسحات مسجلة بعد. اطبع الملصق وقم بتعليقه، وعند قيام أي موظف بمسح الرمز ستظهر بطاقته هنا فوراً مع تحديث تلقائي كل 5 ثوانٍ.
                </Typography>
              </Box>
            ) : (
              <Grid container spacing={2}>
                {scans.map((scan) => (
                  <Grid item xs={12} md={6} lg={4} key={scan.id}>
                    <Card
                      variant="outlined"
                      sx={{
                        p: 2,
                        borderRadius: 3,
                        border: '1px solid',
                        borderColor: scan.employee_id ? 'primary.main' : 'warning.main',
                        bgcolor: scan.employee_id ? 'rgba(0, 240, 255, 0.03)' : 'rgba(255, 170, 0, 0.03)',
                        transition: 'all 0.2s ease-in-out',
                        '&:hover': {
                          transform: 'translateY(-2px)',
                          boxShadow: scan.employee_id
                            ? '0 8px 24px rgba(0, 240, 255, 0.18)'
                            : '0 8px 24px rgba(255, 170, 0, 0.18)',
                        },
                      }}
                    >
                      <Stack spacing={1.5}>
                        <Stack direction="row" justifyContent="space-between" alignItems="center">
                          <Chip
                            size="small"
                            color={scan.employee_id ? 'success' : 'warning'}
                            icon={scan.employee_id ? <CheckIcon fontSize="small" /> : <PersonAddAlt1Icon fontSize="small" />}
                            label={scan.employee_name || 'Unknown'}
                            sx={{ fontWeight: 800 }}
                          />
                          <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
                            {formatDateTime(scan.occurred_at)}
                          </Typography>
                        </Stack>

                        <Divider />

                        <Box sx={{ p: 1.2, borderRadius: 1.5, bgcolor: 'background.default' }}>
                          <Stack spacing={0.5}>
                            <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.82rem' }}>
                              <strong>User:</strong> {scan.username_entered || scan.username || '—'}
                            </Typography>
                            <Typography variant="body2" sx={{ fontFamily: 'monospace', fontSize: '0.82rem' }}>
                              <strong>Email:</strong> {scan.email_entered || scan.email || '—'}
                            </Typography>
                          </Stack>
                        </Box>

                        <Stack spacing={0.8}>
                          <Stack direction="row" justifyContent="space-between" alignItems="center">
                            <Typography variant="caption" color="text.secondary">
                              IP:
                            </Typography>
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                              {scan.ip_address || '—'}
                            </Typography>
                          </Stack>

                          <Stack direction="row" justifyContent="space-between" alignItems="center">
                            <Typography variant="caption" color="text.secondary">
                              Device:
                            </Typography>
                            <Typography variant="caption" sx={{ fontWeight: 600 }}>
                              {deviceSummary(scan)}
                            </Typography>
                          </Stack>

                          <Stack direction="row" justifyContent="space-between" alignItems="center">
                            <Typography variant="caption" color="text.secondary">
                              Fingerprint:
                            </Typography>
                            <Typography
                              variant="caption"
                              sx={{
                                fontFamily: 'monospace',
                                color: 'primary.main',
                                bgcolor: 'action.hover',
                                px: 0.8,
                                py: 0.2,
                                borderRadius: 1,
                              }}
                            >
                              #{scan.fingerprint_hash ? scan.fingerprint_hash.slice(0, 14) : '—'}
                            </Typography>
                          </Stack>

                          {scan.penalty_applied ? (
                            <Chip
                              size="small"
                              color="error"
                              label="عقوبة مطبقة: −25 Elo"
                              sx={{ mt: 0.5, fontWeight: 700 }}
                            />
                          ) : null}
                        </Stack>

                        {!scan.employee_id ? (
                          <Button
                            fullWidth
                            size="small"
                            variant="outlined"
                            color="warning"
                            startIcon={<PersonAddAlt1Icon />}
                            onClick={() => {
                              setAssignScan(scan);
                              setAssignEmployeeId('');
                            }}
                          >
                            Assign to Employee
                          </Button>
                        ) : null}
                      </Stack>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            )}
          </CardContent>
        ) : null}
      </Card>

      <Dialog
        open={Boolean(assignScan)}
        onClose={() => (assignBusy ? undefined : setAssignScan(null))}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>ربط المسح بموظف — Assign to employee</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <Alert severity="info">
              سيُربط هذا المسح بالموظف المحدد، ويُخصم 25 نقطة Elo مرة واحدة إن لم يكن قد
              خُصمت سابقاً في هذه الحملة.
            </Alert>
            <Box sx={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
              <div>username: {assignScan?.username || '—'}</div>
              <div>email: {assignScan?.email || '—'}</div>
              <div>device: {assignScan ? deviceSummary(assignScan) : '—'}</div>
              <div>ip: {assignScan?.ip_address || '—'}</div>
            </Box>
            <TextField
              select
              fullWidth
              label="اختر الموظف"
              value={assignEmployeeId}
              onChange={(event) => setAssignEmployeeId(event.target.value)}
            >
              {allEmployees.map((employee) => (
                <MenuItem key={employee.employee_id} value={employee.employee_id}>
                  {employee.name} — {employee.email}
                </MenuItem>
              ))}
            </TextField>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAssignScan(null)} disabled={assignBusy}>
            إلغاء
          </Button>
          <Button
            variant="contained"
            onClick={() => void handleAssignScan()}
            disabled={assignBusy || !assignEmployeeId}
            startIcon={assignBusy ? <CircularProgress size={16} /> : <PersonAddAlt1Icon />}
          >
            ربط وتطبيق الخصم
          </Button>
        </DialogActions>
      </Dialog>

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
