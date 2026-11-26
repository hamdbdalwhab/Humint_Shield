/**
 * Full employee dossier: every campaign, every event and every value typed.
 *
 * This is the page an administrator opens when they need the complete, provable
 * history of one person — not a summary. Timestamps keep second precision and
 * the captured form values are shown verbatim (secrets masked until revealed).
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Tabs from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import SendIcon from '@mui/icons-material/Send';
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { Link as RouterLink, useParams } from 'react-router-dom';

import { employeesApi, trackingApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { InteractionTimeline } from '@/components/InteractionTimeline';
import { PageHeader } from '@/components/PageHeader';
import { StatCard } from '@/components/StatCard';
import { EngagementStatusBadge } from '@/components/StatusBadge';
import { SubmissionCard } from '@/components/SubmissionCard';
import { ThreatBadge } from '@/components/ThreatBadge';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatDate, formatDateTime } from '@/lib/format';
import type { EmployeeCampaignRecord } from '@/types';

function CampaignRow({
  record,
  onReportSafe,
  reporting,
}: {
  record: EmployeeCampaignRecord;
  onReportSafe: (trackingUuid: string) => void;
  reporting: boolean;
}) {
  return (
    <TableRow hover>
      <TableCell sx={{ minWidth: 220 }}>
        <Button
          component={RouterLink}
          to={`/campaigns/${record.campaign_id}`}
          size="small"
          sx={{ textTransform: 'none', p: 0, minWidth: 0 }}
        >
          {record.campaign_name}
        </Button>
        <Typography variant="caption" color="text.secondary" display="block">
          {record.template_name ?? '—'}
        </Typography>
      </TableCell>
      <TableCell align="center">
        <EngagementStatusBadge status={record.status} />
      </TableCell>
      <TableCell align="center">
        {record.quiz_score !== null
          ? `${record.quiz_score}/${record.quiz_total ?? 5}`
          : '—'}
      </TableCell>
      <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{formatDateTime(record.sent_at)}</TableCell>
      <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{formatDateTime(record.opened_at)}</TableCell>
      <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{formatDateTime(record.clicked_at)}</TableCell>
      <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{formatDateTime(record.form_viewed_at)}</TableCell>
      <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{formatDateTime(record.submitted_at)}</TableCell>
      <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{formatDateTime(record.reported_at)}</TableCell>
      <TableCell sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{formatDateTime(record.completed_at)}</TableCell>
      <TableCell align="center">{record.open_count}</TableCell>
      <TableCell align="center">{record.click_count}</TableCell>
      <TableCell align="center">{record.submission_count}</TableCell>
      <TableCell align="center">
        <Button
          size="small"
          variant="outlined"
          startIcon={<VerifiedUserIcon />}
          disabled={record.is_reported_safe || reporting}
          onClick={() => onReportSafe(record.tracking_uuid)}
          sx={{
            color: record.is_reported_safe ? 'success.main' : '#FFD54F',
            borderColor: record.is_reported_safe
              ? 'rgba(0,230,118,.35)'
              : 'rgba(255,213,79,.5)',
            bgcolor: record.is_reported_safe
              ? 'rgba(0,230,118,.05)'
              : 'rgba(255,213,79,.06)',
            whiteSpace: 'nowrap',
            '&:hover': {
              borderColor: record.is_reported_safe
                ? 'rgba(0,230,118,.55)'
                : 'rgba(255,213,79,.85)',
              bgcolor: record.is_reported_safe
                ? 'rgba(0,230,118,.08)'
                : 'rgba(255,213,79,.12)',
            },
          }}
        >
          {record.is_reported_safe ? 'Reported Safe' : reporting ? '…' : 'Report Safe'}
        </Button>
      </TableCell>
    </TableRow>
  );
}

export function EmployeeDossierPage() {
  const { employeeId } = useParams<{ employeeId: string }>();
  const { organizationId } = useAuth();
  const [tab, setTab] = useState(0);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ['employee-dossier', organizationId, employeeId],
    queryFn: () => employeesApi.dossier(organizationId as string, employeeId as string),
    enabled: Boolean(organizationId && employeeId),
  });

  const reportSafeMutation = useMutation({
    mutationFn: (trackingUuid: string) => trackingApi.reportSafe(trackingUuid),
    onSuccess: (result) => {
      toast.success(result.message || 'Reported safe — immunity set to 100%.');
      void queryClient.invalidateQueries({
        queryKey: ['employee-dossier', organizationId, employeeId],
      });
      void queryClient.invalidateQueries({ queryKey: ['employees', organizationId] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (query.isLoading) return <LoadingState label="Loading employee dossier…" />;
  if (query.error) return <Alert severity="error">{errorMessage(query.error)}</Alert>;
  if (!query.data) return null;

  const { employee, summary, campaigns, events, submissions } = query.data;
  const fullName = `${employee.first_name} ${employee.last_name}`.trim();

  return (
    <>
      <PageHeader
        title={fullName || employee.email}
        subtitle={`${employee.email}${employee.department ? ` · ${employee.department}` : ''}${
          employee.job_title ? ` · ${employee.job_title}` : ''
        }`}
        actions={
          <Stack direction="row" spacing={1}>
            <Button
              component={RouterLink}
              to={`/campaigns/new?employeeId=${employee.id}`}
              startIcon={<SendIcon />}
              variant="contained"
            >
              Send simulation
            </Button>
            <Button
              component={RouterLink}
              to="/employees"
              startIcon={<ArrowBackIcon />}
              variant="outlined"
            >
              All employees
            </Button>
          </Stack>
        }
      />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={6} md={2}>
          <StatCard label="Campaigns" value={summary.campaigns} />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatCard label="Emails sent" value={summary.emails_sent} tone="primary" />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatCard label="Opened" value={summary.opened} tone="primary" />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatCard label="Clicked" value={summary.clicked} tone="warning" />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatCard label="Form submitted" value={summary.submitted} tone="warning" />
        </Grid>
        <Grid item xs={6} md={2}>
          <StatCard label="Reported" value={summary.reported} tone="success" />
        </Grid>
      </Grid>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
            <Chip label={`Immunity score ${employee.immunity_score.toFixed(1)}`} color="primary" />
            <Chip
              variant="outlined"
              label={`Elo ${employee.elo_score ?? 1000}`}
              sx={{ fontWeight: 800 }}
            />
            <ThreatBadge level={employee.threat_level} />
            {employee.is_blacklisted ? (
              <Chip
                color="error"
                label="BLACKLISTED: Repeated Failure"
                sx={{ fontWeight: 800 }}
              />
            ) : null}
            <Chip
              variant="outlined"
              label={
                employee.behavioral_category
                  ? employee.behavioral_category.replace('_', ' ')
                  : 'not classified'
              }
            />
            <Chip variant="outlined" label={`${summary.total_interactions} recorded events`} />
            <Typography variant="body2" color="text.secondary">
              First interaction: {formatDateTime(summary.first_interaction_at)} · Last:{' '}
              {formatDateTime(summary.last_interaction_at)}
            </Typography>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <Tabs
          value={tab}
          onChange={(_, value: number) => setTab(value)}
          variant="scrollable"
          sx={{ px: 2, borderBottom: 1, borderColor: 'divider' }}
        >
          <Tab label={`Campaigns (${campaigns.length})`} />
          <Tab label={`Full activity (${events.length})`} />
          <Tab label={`Entered data (${submissions.length})`} />
          <Tab label="Profile" />
        </Tabs>

        {tab === 0 ? (
          campaigns.length === 0 ? (
            <EmptyState
              title="No campaigns yet"
              description="This employee has not been included in a simulation."
            />
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Campaign</TableCell>
                    <TableCell align="center">Status</TableCell>
                    <TableCell align="center">Quiz</TableCell>
                    <TableCell>Sent</TableCell>
                    <TableCell>Opened</TableCell>
                    <TableCell>Clicked</TableCell>
                    <TableCell>Form shown</TableCell>
                    <TableCell>Submitted</TableCell>
                    <TableCell>Reported</TableCell>
                    <TableCell>Completed</TableCell>
                    <TableCell align="center">Opens</TableCell>
                    <TableCell align="center">Clicks</TableCell>
                    <TableCell align="center">Submits</TableCell>
                    <TableCell align="center">Safe report</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {campaigns.map((record) => (
                    <CampaignRow
                      key={record.campaign_id}
                      record={record}
                      onReportSafe={(trackingUuid) => reportSafeMutation.mutate(trackingUuid)}
                      reporting={
                        reportSafeMutation.isPending &&
                        reportSafeMutation.variables === record.tracking_uuid
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )
        ) : null}

        {tab === 1 ? (
          <Box sx={{ p: 2 }}>
            <Alert severity="info" variant="outlined" sx={{ mb: 2 }}>
              Every event is listed in the order the server recorded it, to the second. Hover a
              timestamp for the raw ISO-8601 value.
            </Alert>
            <InteractionTimeline events={events} showCampaign />
          </Box>
        ) : null}

        {tab === 2 ? (
          <Box sx={{ p: 2 }}>
            {submissions.length === 0 ? (
              <EmptyState
                title="Nothing entered"
                description="This employee has never submitted a simulated form."
              />
            ) : (
              <Stack spacing={2}>
                <Alert severity="warning" variant="outlined">
                  Every value below was typed by the employee and stored encrypted. Values are
                  visible by default for review; use the eye icon to hide one. Use the comparison
                  box to check whether the submitted password matches the employee&apos;s real
                  password — that comparison happens only in this browser.
                </Alert>
                {submissions.map((submission, index) => (
                  <Box key={`${submission.occurred_at}-${index}`}>
                    {submission.campaign_name ? (
                      <Typography variant="subtitle2" gutterBottom>
                        {submission.campaign_name}
                      </Typography>
                    ) : null}
                    <SubmissionCard submission={submission} index={index} />
                  </Box>
                ))}
              </Stack>
            )}
          </Box>
        ) : null}

        {tab === 3 ? (
          <Box sx={{ p: 2 }}>
            <Grid container spacing={2}>
              {[
                ['Email', employee.email],
                ['Department', employee.department ?? '—'],
                ['Job title', employee.job_title ?? '—'],
                ['Phone', employee.phone ?? '—'],
                ['Access level', String(employee.access_level)],
                ['Active', employee.is_active ? 'Yes' : 'No'],
                ['On leave', employee.is_on_leave ? 'Yes' : 'No'],
                ['Mandatory training', employee.requires_mandatory_training ? 'Yes' : 'No'],
                ['Enhanced monitoring', employee.under_enhanced_monitoring ? 'Yes' : 'No'],
                ['Tests received', String(employee.total_tests_received)],
                ['Total clicks', String(employee.total_clicks)],
                ['Credential submissions', String(employee.total_credential_submissions)],
                ['Reports filed', String(employee.total_reports)],
                ['Last test', formatDate(employee.last_test_date)],
                ['Next test', formatDate(employee.next_test_date)],
                ['Created', formatDateTime(employee.created_at)],
              ].map(([label, value]) => (
                <Grid item xs={12} sm={6} md={4} key={label}>
                  <Typography variant="caption" color="text.secondary">
                    {label}
                  </Typography>
                  <Typography variant="body2">{value}</Typography>
                </Grid>
              ))}
            </Grid>
            <Divider sx={{ my: 2 }} />
            <Typography variant="caption" color="text.secondary">
              Dossier generated from the tracking ledger. Secrets are encrypted at rest with
              AES-256-GCM.
            </Typography>
          </Box>
        ) : null}
      </Card>
    </>
  );
}
