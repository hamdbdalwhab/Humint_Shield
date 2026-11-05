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
import KeyboardIcon from '@mui/icons-material/Keyboard';
import ComputerIcon from '@mui/icons-material/Computer';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import DoneAllIcon from '@mui/icons-material/DoneAll';
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ScheduleIcon from '@mui/icons-material/Schedule';
import SensorsIcon from '@mui/icons-material/Sensors';
import VisibilityIcon from '@mui/icons-material/Visibility';
import RadioButtonCheckedIcon from '@mui/icons-material/RadioButtonChecked';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import PublicIcon from '@mui/icons-material/Public';
import DevicesIcon from '@mui/icons-material/Devices';
import FingerprintIcon from '@mui/icons-material/Fingerprint';
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { campaignsApi, reportsApi } from '@/api/endpoints';
import { InteractionTimeline } from '@/components/InteractionTimeline';
import { LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { RecipientDossierDialog } from '@/components/RecipientDossierDialog';
import { UsbDeploymentStation } from '@/components/UsbDeploymentStation';
import { EnterpriseContainmentStation } from '@/components/EnterpriseContainmentStation';
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

function parseDeviceInfo(scan: QRScan): { os: string; browser: string; screen: string } {
  const fp = ((scan.fingerprint || {}) as Record<string, unknown>);
  const ua = scan.user_agent || '';

  let os = (scan.device_model || (fp.os as string) || (fp.platform as string) || '');
  if (!os) {
    if (/Windows/i.test(ua)) os = 'Windows';
    else if (/Android/i.test(ua)) os = 'Android';
    else if (/iPhone|iPad|iPod/i.test(ua)) os = 'iOS';
    else if (/Macintosh|Mac OS X/i.test(ua)) os = 'macOS';
    else if (/Linux/i.test(ua)) os = 'Linux';
    else os = 'Unknown OS';
  }

  let browser = (fp.browser as string) || '';
  if (!browser) {
    if (/Edg/i.test(ua)) browser = 'Edge';
    else if (/Chrome/i.test(ua)) browser = 'Chrome';
    else if (/Safari/i.test(ua)) browser = 'Safari';
    else if (/Firefox/i.test(ua)) browser = 'Firefox';
    else browser = 'Unknown Browser';
  }

  const screen = (fp.screen || (fp.screen_width && fp.screen_height ? `${fp.screen_width}x${fp.screen_height}` : '') || fp.viewport || 'Unknown') as string;

  return { os: String(os), browser: String(browser), screen: String(screen) };
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
  const [radarScans, setRadarScans] = useState<QRScan[]>([]);

  useEffect(() => {
    if (!campaignId) return;
    const fetchRadarScans = async () => {
      try {
        const data = await campaignsApi.getCampaignScans(campaignId);
        setRadarScans(data || []);
      } catch {
        /* ignore polling error */
      }
    };
    fetchRadarScans();
    const interval = setInterval(fetchRadarScans, 5000);
    return () => clearInterval(interval);
  }, [campaignId]);

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

  const isUsb = resultsQuery.data?.campaign.channel === 'usb';

  const usbBreaches = useMemo(() => {
    if (!isUsb) return [];
    const rows = resultsQuery.data?.employees ?? [];
    const list: Array<{
      id: string;
      hostname: string;
      username: string;
      domain: string;
      arch: string;
      scenario: string;
      ip_address: string;
      timestamp: string;
      employee_name: string;
      department: string;
      employee_id?: string;
      tracking_uuid: string;
      status: string;
      attack_type: string;
    }> = [];

    rows.forEach((row) => {
      const ctx = (row as any).client_context || {};
      const events = (ctx.breach_events as any[]) || [];
      if (events.length > 0) {
        events.forEach((ev: any, idx: number) => {
          list.push({
            id: `${row.tracking_uuid}-${idx}`,
            hostname: ev.hostname || ctx.hostname || 'DESKTOP-ENDPOINT',
            username: ev.username || ctx.username || 'Unknown User',
            domain: ev.domain || ctx.domain || '',
            arch: ev.arch || ctx.arch || '',
            scenario: ev.scenario || ctx.scenario || '',
            ip_address: ev.ip_address || '',
            timestamp: ev.timestamp || row.clicked_at || row.opened_at || '',
            employee_name: row.name !== 'طعم فيزيائي عام (Physical Drop Target)' ? row.name : (ev.username || 'موظف مجهول'),
            department: row.department || 'Physical Assessment',
            employee_id: row.employee_id,
            tracking_uuid: String(row.tracking_uuid),
            status: row.status,
            attack_type: ev.attack_type || ctx.attack_type || 'baiting',
          });
        });
      } else if (ctx.hostname || row.status === 'clicked' || row.status === 'opened') {
        list.push({
          id: String(row.tracking_uuid),
          hostname: ctx.hostname || 'DESKTOP-ENDPOINT',
          username: ctx.username || row.name,
          domain: ctx.domain || '',
          arch: ctx.arch || '',
          scenario: ctx.scenario || '',
          ip_address: (row as any).last_ip_address || '',
          timestamp: row.clicked_at || row.opened_at || row.sent_at || '',
          employee_name: row.name !== 'طعم فيزيائي عام (Physical Drop Target)' ? row.name : (ctx.username || 'موظف مجهول'),
          department: row.department || 'Physical Assessment',
          employee_id: row.employee_id,
          tracking_uuid: String(row.tracking_uuid),
          status: row.status,
          attack_type: ctx.attack_type || 'baiting',
        });
      }
    });

    return list;
  }, [isUsb, resultsQuery.data]);

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
  if (!resultsQuery.data) return <LoadingState label="Loading campaign…" />;

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

      {campaignId ? (
        <EnterpriseContainmentStation campaignId={campaignId} />
      ) : null}

      {isUsbChannel && organizationId && campaignId ? (
        <UsbDeploymentStation campaignId={campaignId} organizationId={organizationId} />
      ) : null}

      <Card>
        <Tabs
          value={tab}
          onChange={(_, value: number) => setTab(value)}
          sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}
        >
          <Tab label={isUsbChannel ? `السجلات الفيزيائية (${allEmployees.length})` : `Recipients (${allEmployees.length})`} />
          <Tab label="Live activity" />
          {isQrChannel ? <Tab label={`الرادار المباشر — Live Scans (${radarScans.length || scans.length})`} /> : null}
          {isUsbChannel ? <Tab label={`رادار اختراقات الـ USB الميداني (${usbBreaches.length})`} /> : null}
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
                <Stack direction="row" spacing={1.5} alignItems="center">
                  <Typography variant="h3" sx={{ fontSize: '1.15rem', fontWeight: 800 }}>
                    الرادار المباشر — Live Telemetry Radar
                  </Typography>
                  <Chip size="small" color="primary" icon={<RadioButtonCheckedIcon fontSize="small" />} label="استطلاع حي كل 5 ثوانٍ (Live Polling 5s)" sx={{ fontWeight: 700 }} />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  استعراض فوري لعمليات المسح المدخلة من صفحة الهبوط
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} sx={{ mt: { xs: 1, sm: 0 } }}>
                <Chip
                  color={radarScans.some((scan) => !scan.employee_id) ? 'warning' : 'success'}
                  label={`${radarScans.filter((scan) => !scan.employee_id).length} غير معروف`}
                />
                <Chip
                  variant="outlined"
                  label={`إجمالي المسحات: ${radarScans.length}`}
                />
              </Stack>
            </Stack>

            {radarScans.length === 0 ? (
              <Box sx={{ p: 4, textAlign: 'center', bgcolor: 'action.hover', borderRadius: 2 }}>
                <Typography variant="body1" sx={{ fontWeight: 700, mb: 1 }}>لا توجد عمليات مسح حتى الآن (No scans yet)</Typography>
                <Typography color="text.secondary" variant="body2">بمجرد قيام أي شخص بمسح رمز الاستجابة السريعة (QR) أو إدخال البيانات، ستظهر بطاقة المسح هنا فوراً.</Typography>
              </Box>
            ) : (
              <Grid container spacing={2}>
                {radarScans.map((scan) => {
                  const deviceInfo = parseDeviceInfo(scan);
                  const matchedName = scan.employee_name;
                  const isMatched = Boolean(matchedName || scan.employee_id);
                  const fpHash = scan.hardware_fingerprint || scan.fingerprint_hash || (scan.fingerprint as any)?.hardware_fingerprint || (scan.fingerprint as any)?.fingerprint_hash || '';
                  const truncatedFp = fpHash ? fpHash.slice(0, 16) + '...' : '—';
                  const loc = [scan.city, scan.country].filter(Boolean).join(', ') || scan.location_display || '';
                  const usernameEntered = scan.username || scan.username_entered || '—';
                  const emailEntered = scan.email || scan.email_entered || '—';

                  const devRealName = scan.device_real_name || (scan.fingerprint as any)?.device_real_name || scan.device_model || `${deviceInfo.os} · ${deviceInfo.browser}`;
                  const localIp = scan.local_ip || (scan.fingerprint as any)?.local_ip;
                  const mdnsName = scan.mDNS_name || (scan.fingerprint as any)?.mDNS_name;
                  const publicIp = scan.ip_address || (scan.fingerprint as any)?.public_ip || '—';
                  const gpuRenderer = scan.gpu_renderer || (scan.fingerprint as any)?.gpu_renderer || (scan.fingerprint as any)?.webgl_renderer || 'Standard GPU';
                  const cpuCores = scan.cpu_cores || (scan.fingerprint as any)?.cpu_cores;
                  const memGb = scan.device_memory_gb || (scan.fingerprint as any)?.device_memory_gb;
                  const screenRes = (scan.fingerprint as any)?.screen || (scan.fingerprint as any)?.screen_resolution;
                  const dpr = scan.pixel_ratio || (scan.fingerprint as any)?.pixel_ratio;
                  const lang = scan.language || (scan.fingerprint as any)?.language;

                  return (
                    <Grid item xs={12} sm={6} md={4} key={scan.id}>
                      <Card
                        variant="outlined"
                        sx={{
                          height: '100%',
                          display: 'flex',
                          flexDirection: 'column',
                          borderRadius: 2.5,
                          borderColor: isMatched ? 'rgba(0, 230, 118, 0.45)' : 'rgba(255, 179, 0, 0.45)',
                          bgcolor: 'background.paper',
                          boxShadow: isMatched
                            ? '0 4px 18px rgba(0, 230, 118, 0.08)'
                            : '0 4px 18px rgba(255, 179, 0, 0.08)',
                          transition: 'all 0.2s ease-in-out',
                          '&:hover': {
                            transform: 'translateY(-2px)',
                            boxShadow: '0 8px 24px rgba(0,0,0,.25)',
                          },
                        }}
                      >
                        <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                          {/* Top: Time & Matched Badge */}
                          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                            <Stack direction="row" spacing={0.8} alignItems="center">
                              <AccessTimeIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                              <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                                {new Date(scan.occurred_at).toLocaleString('en-US', {
                                  month: 'short',
                                  day: '2-digit',
                                  hour: '2-digit',
                                  minute: '2-digit',
                                  second: '2-digit',
                                  hour12: false,
                                })}
                              </Typography>
                            </Stack>
                            <Stack direction="row" spacing={0.8} alignItems="center">
                              {scan.elo_delta ? (
                                <Chip
                                  size="small"
                                  label={`${scan.elo_delta} Elo`}
                                  color={scan.elo_delta < 0 ? 'error' : 'success'}
                                  sx={{ fontWeight: 800, fontSize: '0.72rem' }}
                                />
                              ) : null}
                              <Chip
                                size="small"
                                label={isMatched ? `Matched: ${matchedName || 'Employee'}` : 'Unknown'}
                                color={isMatched ? 'success' : 'warning'}
                                variant={isMatched ? 'filled' : 'outlined'}
                                sx={{ fontWeight: 800, fontSize: '0.72rem' }}
                              />
                            </Stack>
                          </Stack>

                          {/* Anti-Evasion / Repeat Alert Badge */}
                          {scan.status === 'evasion_attempt' || (scan.repeat_status && scan.repeat_status.includes('تهرب')) ? (
                            <Box sx={{ mb: 1.2, p: 0.8, borderRadius: 1.5, bgcolor: 'error.dark', color: '#fff', fontSize: '0.72rem', fontWeight: 800 }}>
                              ⚠️ محاولة تهرب / انتحال — الجهاز مسجل باسم {scan.device_owner_name || (scan.fingerprint as any)?.device_owner_name || scan.employee_name}
                            </Box>
                          ) : scan.repeat_status ? (
                            <Box sx={{ mb: 1.2, p: 0.8, borderRadius: 1.5, bgcolor: 'warning.dark', color: '#fff', fontSize: '0.72rem', fontWeight: 700 }}>
                              {scan.repeat_status}
                            </Box>
                          ) : null}

                          {/* 1. Real Device & Router Hostname */}
                          <Box sx={{ mb: 1.2, p: 1.2, borderRadius: 2, bgcolor: 'action.hover' }}>
                            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.4 }}>
                              <DevicesIcon sx={{ fontSize: 18, color: 'info.main' }} />
                              <Box sx={{ flex: 1 }}>
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: '0.68rem', fontWeight: 700 }}>
                                  اسم الجهاز الحقيقي (كما يظهر في الراوتر)
                                </Typography>
                                <Typography variant="body2" sx={{ fontSize: '0.86rem', fontWeight: 900, color: 'primary.main' }}>
                                  {devRealName}
                                </Typography>
                              </Box>
                            </Stack>
                            {mdnsName ? (
                              <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', pl: 3.2, fontSize: '0.72rem', fontFamily: 'monospace' }}>
                                اسم الشبكة المحلي (mDNS): <strong>{mdnsName}</strong>
                              </Typography>
                            ) : null}
                          </Box>

                          {/* 2. Network Telemetry (Local & Global IP) */}
                          <Box sx={{ mb: 1.2, p: 1.2, borderRadius: 2, bgcolor: 'action.hover' }}>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.4, fontSize: '0.68rem', fontWeight: 700 }}>
                              عناوين الشبكة والاتصال (Network IPs)
                            </Typography>
                            <Grid container spacing={1}>
                              <Grid item xs={6}>
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: '0.65rem' }}>
                                  الآيبي المحلي (LAN):
                                </Typography>
                                <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 800, color: localIp ? 'success.main' : 'text.disabled', fontSize: '0.78rem' }}>
                                  {localIp || '—'}
                                </Typography>
                              </Grid>
                              <Grid item xs={6}>
                                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', fontSize: '0.65rem' }}>
                                  الآيبي العالمي (Public WAN):
                                </Typography>
                                <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 800, color: 'info.main', fontSize: '0.78rem' }}>
                                  {publicIp}
                                </Typography>
                              </Grid>
                            </Grid>
                            {loc ? (
                              <Stack direction="row" spacing={0.6} alignItems="center" sx={{ mt: 0.6 }}>
                                <PublicIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
                                <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.72rem', fontWeight: 600 }}>
                                  {loc} {scan.isp ? `· ISP: ${scan.isp}` : ''}
                                </Typography>
                              </Stack>
                            ) : null}
                          </Box>

                          {/* 3. Deep Hardware & GPU Specs */}
                          <Box sx={{ mb: 1.2, p: 1, borderRadius: 1.5, border: '1px solid', borderColor: 'divider' }}>
                            <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.7rem' }}>
                              🎮 <strong>معالج الرسوميات (GPU):</strong> {gpuRenderer}
                            </Typography>
                            <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.7rem' }}>
                              ⚡ <strong>المواصفات:</strong> {[
                                cpuCores ? `${cpuCores} أنوية` : null,
                                memGb ? `${memGb} GB RAM` : null,
                                screenRes ? `الشاشة: ${screenRes}` : null,
                                dpr ? `@${dpr}x` : null,
                                lang ? `${lang}` : null,
                              ].filter(Boolean).join(' · ')}
                            </Typography>
                          </Box>

                          {/* 4. Fingerprint Hash (truncated) */}
                          <Box sx={{ mb: 1.2 }}>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.2, fontSize: '0.68rem' }}>
                              بصمة العتاد الرقمية (Hardware Fingerprint)
                            </Typography>
                            <Stack direction="row" spacing={1} alignItems="center">
                              <FingerprintIcon sx={{ fontSize: 16, color: 'secondary.main' }} />
                              <Typography
                                variant="caption"
                                sx={{
                                  fontFamily: 'monospace',
                                  fontSize: '0.73rem',
                                  bgcolor: 'action.hover',
                                  px: 1,
                                  py: 0.3,
                                  borderRadius: 1,
                                }}
                                title={fpHash}
                              >
                                {truncatedFp}
                              </Typography>
                            </Stack>
                          </Box>

                          {/* 5. Entered Credentials */}
                          <Box sx={{ pt: 1, borderTop: '1px solid', borderColor: 'divider' }}>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                              Username Entered: <strong>{usernameEntered}</strong>
                            </Typography>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                              Email Entered: <strong style={{ color: '#00f0ff' }}>{emailEntered}</strong>
                            </Typography>
                          </Box>

                          {!isMatched ? (
                            <Box sx={{ mt: 1.5, textAlign: 'right' }}>
                              <Button
                                size="small"
                                variant="outlined"
                                color="warning"
                                startIcon={<PersonAddAlt1Icon fontSize="small" />}
                                onClick={() => {
                                  setAssignScan(scan);
                                  setAssignEmployeeId('');
                                }}
                                sx={{ fontSize: '0.72rem', py: 0.2 }}
                              >
                                ربط بموظف (Assign)
                              </Button>
                            </Box>
                          ) : null}
                        </CardContent>
                      </Card>
                    </Grid>
                  );
                })}
              </Grid>
            )}
          </CardContent>
        ) : null}

        {tab === 2 && isUsbChannel ? (
          <CardContent>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              justifyContent="space-between"
              alignItems={{ xs: 'stretch', sm: 'center' }}
              sx={{ mb: 2 }}
            >
              <Box>
                <Stack direction="row" spacing={1.5} alignItems="center">
                  <Typography variant="h3" sx={{ fontSize: '1.15rem', fontWeight: 800 }}>
                    رادار اختراقات الـ USB الميداني — Live Physical Breach Radar
                  </Typography>
                  <Chip
                    size="small"
                    color="primary"
                    icon={<RadioButtonCheckedIcon fontSize="small" />}
                    label="استطلاع حي وتحديث فوري"
                    sx={{ fontWeight: 700 }}
                  />
                </Stack>
                <Typography variant="caption" color="text.secondary">
                  رصد أجهزة ومحطات العمل التي تم توصيل فلاشات التوعية بها وتشغيل ملفات المحاكاة
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} sx={{ mt: { xs: 1, sm: 0 } }}>
                <Chip
                  color={usbBreaches.length > 0 ? 'error' : 'success'}
                  label={`محطات العمل المخترقة: ${usbBreaches.length}`}
                  sx={{ fontWeight: 800 }}
                />
                <Chip
                  variant="outlined"
                  label="خصم النقاط: -30 Elo لكل اختراق فيزيائي"
                />
              </Stack>
            </Stack>

            {usbBreaches.length === 0 ? (
              <Box sx={{ p: 4, textAlign: 'center', bgcolor: 'action.hover', borderRadius: 2 }}>
                <Typography variant="body1" sx={{ fontWeight: 700, mb: 1 }}>
                  لم يتم رصد أي اختراق فيزيائي حتى الآن (No USB Breaches Yet)
                </Typography>
                <Typography color="text.secondary" variant="body2" sx={{ maxWidth: 600, mx: 'auto' }}>
                  بمجرد قيام أي موظف بالتقاط الفلاشة الميدانية وتوصيلها بجهاز الكمبيوتر وتشغيل أي ملف محاكاة، سيتم التقاط اسم الجهاز (Hostname) واسم المستخدم والنطاق وعرض بطاقة الاختراق هنا فوراً.
                </Typography>
              </Box>
            ) : (
              <Grid container spacing={2}>
                {usbBreaches.map((breach) => (
                  <Grid item xs={12} sm={6} md={4} key={breach.id}>
                    <Card
                      variant="outlined"
                      sx={{
                        height: '100%',
                        display: 'flex',
                        flexDirection: 'column',
                        borderRadius: 2.5,
                        borderColor: 'rgba(255, 23, 68, 0.45)',
                        bgcolor: 'background.paper',
                        boxShadow: '0 4px 18px rgba(255, 23, 68, 0.08)',
                        transition: 'all 0.2s ease-in-out',
                        '&:hover': {
                          transform: 'translateY(-2px)',
                          boxShadow: '0 8px 24px rgba(255, 23, 68, 0.2)',
                        },
                      }}
                    >
                      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
                        {/* Red Alert Banner */}
                        <Chip
                          size="small"
                          label="اختراق فيزيائي عاجل — Critical Physical Breach"
                          color="error"
                          variant="filled"
                          sx={{ fontWeight: 800, mb: 1.2, width: '100%' }}
                        />

                        {/* Header: Timestamp and Attack Vector */}
                        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                          <Stack direction="row" spacing={0.8} alignItems="center">
                            <AccessTimeIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                            <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 700 }}>
                              {breach.timestamp ? new Date(breach.timestamp).toLocaleString('ar-SA') : 'الآن'}
                            </Typography>
                          </Stack>
                          <Stack direction="row" spacing={0.8} alignItems="center">
                            {breach.attack_type === 'badusb_hid' ? (
                              <Chip
                                size="small"
                                icon={<KeyboardIcon />}
                                label="BadUSB (HID)"
                                color="warning"
                                sx={{ fontWeight: 700, fontSize: '0.72rem' }}
                              />
                            ) : (
                              <Chip
                                size="small"
                                icon={<UsbIcon />}
                                label="USB Baiting"
                                color="info"
                                sx={{ fontWeight: 700, fontSize: '0.72rem' }}
                              />
                            )}
                            <Chip
                              size="small"
                              label={breach.attack_type === 'badusb_hid' ? "-40 Elo" : "-30 Elo"}
                              color="error"
                              sx={{ fontWeight: 800, fontSize: '0.72rem' }}
                            />
                          </Stack>
                        </Stack>

                        {/* Endpoint Name */}
                        <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                          <ComputerIcon color="error" fontSize="medium" />
                          <Typography variant="h6" sx={{ fontWeight: 800, fontSize: '0.95rem' }}>
                            {breach.hostname}
                          </Typography>
                        </Stack>

                        {/* Forensics List */}
                        <Stack spacing={0.8} sx={{ mb: 2, bgcolor: 'action.hover', p: 1.2, borderRadius: 1.5 }}>
                          <Stack direction="row" justifyContent="space-between">
                            <Typography variant="caption" color="text.secondary">نوع ناقل الهجوم:</Typography>
                            <Typography variant="caption" sx={{ fontWeight: 800, color: breach.attack_type === 'badusb_hid' ? 'warning.main' : 'info.main' }}>
                              {breach.attack_type === 'badusb_hid' ? 'محاكاة كيبورد (BadUSB HID)' : 'طعم تخزين فيزيائي (Storage Bait)'}
                            </Typography>
                          </Stack>
                          <Stack direction="row" justifyContent="space-between">
                            <Typography variant="caption" color="text.secondary">عنوان الـ IP:</Typography>
                            <Typography variant="caption" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                              {breach.ip_address || '—'}
                            </Typography>
                          </Stack>
                          <Stack direction="row" justifyContent="space-between">
                            <Typography variant="caption" color="text.secondary">حساب المستخدم:</Typography>
                            <Typography variant="caption" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
                              {breach.domain ? `${breach.domain}\\${breach.username}` : breach.username}
                            </Typography>
                          </Stack>
                          <Stack direction="row" justifyContent="space-between">
                            <Typography variant="caption" color="text.secondary">الموظف المطابق:</Typography>
                            <Typography variant="caption" sx={{ fontWeight: 700, color: 'primary.main' }}>
                              {breach.employee_name}
                            </Typography>
                          </Stack>
                          <Stack direction="row" justifyContent="space-between">
                            <Typography variant="caption" color="text.secondary">القسم / الموقع:</Typography>
                            <Typography variant="caption" sx={{ fontWeight: 600 }}>
                              {breach.department}
                            </Typography>
                          </Stack>
                          {breach.scenario ? (
                            <Stack direction="row" justifyContent="space-between">
                              <Typography variant="caption" color="text.secondary">سيناريو الطُعم:</Typography>
                              <Typography variant="caption" sx={{ fontWeight: 600, color: 'warning.main' }}>
                                {breach.scenario}
                              </Typography>
                            </Stack>
                          ) : null}
                          {breach.arch ? (
                            <Stack direction="row" justifyContent="space-between">
                              <Typography variant="caption" color="text.secondary">المعمارية / النظام:</Typography>
                              <Typography variant="caption" sx={{ fontWeight: 600, fontFamily: 'monospace' }}>
                                {breach.arch}
                              </Typography>
                            </Stack>
                          ) : null}
                        </Stack>

                        {/* Action buttons */}
                        <Stack direction="row" spacing={1}>
                          <Button
                            fullWidth
                            size="small"
                            variant="contained"
                            color="error"
                            onClick={() => {
                              toast.success(`تم فرض جلسة توعية فيزيائية إلزامية لمحطة العمل ${breach.hostname}`);
                            }}
                            sx={{ fontWeight: 700, fontSize: '0.75rem' }}
                          >
                            فرض تدريب إلزامي
                          </Button>
                        </Stack>
                      </CardContent>
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
