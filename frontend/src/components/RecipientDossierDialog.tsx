/**
 * Full dossier for one recipient of one campaign.
 *
 * The dialog is the "prove exactly what happened" surface: every ledger event
 * with second-level timestamps, IP and device, every captured submission with
 * the values verbatim, and a delivery reference table. Data is fetched on open
 * from the recipient endpoint so the list endpoint stays lightweight.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
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
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';

import { campaignsApi } from '@/api/endpoints';
import { InteractionTimeline } from '@/components/InteractionTimeline';
import { SubmissionCard } from '@/components/SubmissionCard';
import { EngagementStatusBadge } from '@/components/StatusBadge';
import { LoadingState } from '@/components/Feedback';
import { errorMessage } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';
import { describeUserAgent, isSecretField, orderedSubmissionFields } from '@/lib/interactions';
import type { EmployeeCampaignRecord } from '@/types';

interface RecipientDossierDialogProps {
  open: boolean;
  onClose: () => void;
  organizationId: string;
  campaignId: string;
  employeeId: string | null;
  employeeName?: string;
}

const TIMELINE_FIELDS: Array<[string, keyof EmployeeCampaignRecord]> = [
  ['Email sent', 'sent_at'],
  ['Delivered', 'delivered_at'],
  ['Opened', 'opened_at'],
  ['Link clicked', 'clicked_at'],
  ['Form displayed', 'form_viewed_at'],
  ['Form submitted', 'submitted_at'],
  ['Reported as phishing', 'reported_at'],
  ['Training completed', 'completed_at'],
];

function ValuesPreview({ record }: { record: EmployeeCampaignRecord }) {
  const values = record.submitted_values ?? {};
  const fields = orderedSubmissionFields(values);
  if (fields.length === 0) {
    return (
      <Alert severity="info" variant="outlined">
        This employee has not submitted the simulated form in this campaign.
      </Alert>
    );
  }
  return (
    <TableContainer>
      <Table size="small">
        <TableBody>
          {fields.map(([key, value]) => (
            <TableRow key={key}>
              <TableCell sx={{ width: '34%', color: 'text.secondary' }}>{key}</TableCell>
              <TableCell>
                <Typography
                  variant="body2"
                  sx={{
                    fontFamily: 'monospace',
                    wordBreak: 'break-all',
                    userSelect: 'all',
                    color: isSecretField(key) ? 'error.main' : 'text.primary',
                  }}
                >
                  {value}
                </Typography>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
        Values are shown in plain text for evidentiary review. Open the “Entered data” tab for the
        local real-password comparison and every submission separately.
      </Typography>
    </TableContainer>
  );
}

export function RecipientDossierDialog({
  open,
  onClose,
  organizationId,
  campaignId,
  employeeId,
  employeeName,
}: RecipientDossierDialogProps) {
  const [tab, setTab] = useState(0);

  const query = useQuery({
    queryKey: ['campaign-recipient', organizationId, campaignId, employeeId],
    queryFn: () => campaignsApi.recipient(organizationId, campaignId, employeeId as string),
    enabled: open && Boolean(organizationId && campaignId && employeeId),
  });

  const record = query.data?.record;
  const employee = query.data?.employee;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
          spacing={1}
        >
          <Box>
            <Typography variant="h3" sx={{ fontSize: '1.15rem' }}>
              {employee ? `${employee.first_name} ${employee.last_name}`.trim() : employeeName ?? 'Recipient'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {employee?.email ?? ''}
              {employee?.department ? ` · ${employee.department}` : ''}
              {employee?.job_title ? ` · ${employee.job_title}` : ''}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            {record ? <EngagementStatusBadge status={record.status} /> : null}
            {employee?.behavioral_category ? (
              <Chip size="small" variant="outlined" label={employee.behavioral_category.replace('_', ' ')} />
            ) : null}
            {employee ? (
              <Chip size="small" label={`Score ${employee.immunity_score.toFixed(1)}`} />
            ) : null}
          </Stack>
        </Stack>
      </DialogTitle>

      <DialogContent dividers sx={{ minHeight: 420 }}>
        {query.isLoading ? <LoadingState label="Loading recipient record…" /> : null}
        {query.error ? <Alert severity="error">{errorMessage(query.error)}</Alert> : null}
        {query.data && record ? (
          <>
            <Tabs
              value={tab}
              onChange={(_, value: number) => setTab(value)}
              variant="scrollable"
              sx={{ mb: 2 }}
            >
              <Tab label="Overview" />
              <Tab label={`Timeline (${record.events.length})`} />
              <Tab label={`Entered data (${record.submissions.length})`} />
              <Tab label="Delivery" />
            </Tabs>

            {tab === 0 ? (
              <Stack spacing={2}>
                <Grid container spacing={2}>
                  <Grid item xs={6} sm={3}>
                    <Typography variant="caption" color="text.secondary">
                      Opens
                    </Typography>
                    <Typography variant="h3" sx={{ fontSize: '1.1rem' }}>
                      {record.open_count}
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3}>
                    <Typography variant="caption" color="text.secondary">
                      Clicks
                    </Typography>
                    <Typography variant="h3" sx={{ fontSize: '1.1rem' }}>
                      {record.click_count}
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3}>
                    <Typography variant="caption" color="text.secondary">
                      Submissions
                    </Typography>
                    <Typography variant="h3" sx={{ fontSize: '1.1rem' }}>
                      {record.submission_count}
                    </Typography>
                  </Grid>
                  <Grid item xs={6} sm={3}>
                    <Typography variant="caption" color="text.secondary">
                      Events recorded
                    </Typography>
                    <Typography variant="h3" sx={{ fontSize: '1.1rem' }}>
                      {record.events.length}
                    </Typography>
                  </Grid>
                </Grid>

                <Box>
                  <Typography variant="subtitle2" gutterBottom>
                    What the employee entered
                  </Typography>
                  <ValuesPreview record={record} />
                </Box>

                <Divider />

                <Box>
                  <Typography variant="subtitle2" gutterBottom>
                    Latest activity
                  </Typography>
                  <InteractionTimeline events={record.events.slice(-4)} />
                </Box>

                
                {record.client_context ? (
                  <Box
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      bgcolor: 'action.hover',
                      border: '1px solid rgba(0,240,255,0.2)',
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ fontWeight: 800, color: 'primary.main', mb: 1 }}>
                      🔬 تفاصيل العتاد والجهاز الحقيقي (Hardware Forensic Telemetry):
                    </Typography>
                    <Stack spacing={0.6} sx={{ fontSize: '0.78rem' }}>
                      <div><strong>اسم الجهاز / النموذج:</strong> {String(record.client_context.device_real_name || record.client_context.device_model || '—')}</div>
                      <div><strong>معالج الرسوميات (GPU):</strong> {String(record.client_context.gpu_renderer || record.client_context.webgl_renderer || '—')}</div>
                      <div><strong>الآيبي المحلي (WebRTC Local IP):</strong> {String(record.client_context.local_ip || '—')}</div>
                      <div><strong>بصمة العتاد (Hardware Fingerprint):</strong> <span style={{ fontFamily: 'monospace' }}>{String(record.client_context.hardware_fingerprint || record.client_context.fingerprint_hash || '—')}</span></div>
                    </Stack>
                  </Box>
                ) : null}

                {record.client_context ? (
                  <Alert severity="info" variant="outlined">
                    Browser context recorded with the submission:{' '}
                    {Object.entries(record.client_context)
                      .filter(([, value]) => value !== null && value !== '')
                      .map(([key, value]) => `${key}=${String(value)}`)
                      .join(' · ')}
                  </Alert>
                ) : null}
              </Stack>
            ) : null}

            {tab === 1 ? (
              <Stack spacing={2}>
                <Alert severity="info" variant="outlined">
                  Times are shown to the second in your local timezone. Hover a timestamp to see
                  the raw ISO-8601 value stored by the server.
                </Alert>
                <InteractionTimeline events={record.events} />
              </Stack>
            ) : null}

            {tab === 2 ? (
              <Stack spacing={2}>
                {record.submissions.length === 0 ? (
                  <Alert severity="warning" variant="outlined">
                    No form submissions were captured for this recipient.
                  </Alert>
                ) : (
                  <>
                    <Alert severity="warning" variant="outlined">
                      These values were typed by the employee and stored encrypted. They are shown
                      in plain text for evidentiary review; the eye icon hides a field. Use the
                      comparison box to check whether the submitted password matches the real
                      password — that check happens only in this browser.
                    </Alert>
                    {record.submissions.map((submission, index) => (
                      <SubmissionCard
                        key={`${submission.occurred_at}-${index}`}
                        submission={submission}
                        index={index}
                      />
                    ))}
                  </>
                )}
              </Stack>
            ) : null}

            {tab === 3 ? (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Event</TableCell>
                      <TableCell>Exact time</TableCell>
                      <TableCell>Source</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {TIMELINE_FIELDS.map(([label, key]) => {
                      const value = record[key] as string | null;
                      return (
                        <TableRow key={label}>
                          <TableCell>{label}</TableCell>
                          <TableCell sx={{ fontFamily: 'monospace' }}>
                            {formatDateTime(value)}
                          </TableCell>
                          <TableCell>
                            {label === 'Opened'
                              ? `${record.open_count}× · ${describeUserAgent(
                                  record.events.find((event) => event.event_type === 'email_open')
                                    ?.user_agent,
                                )}`
                              : label === 'Link clicked'
                                ? `${record.click_count}×`
                                : '—'}
                          </TableCell>
                        </TableRow>
                      );
                    })}
                    <TableRow>
                      <TableCell>Tracking UUID</TableCell>
                      <TableCell colSpan={2} sx={{ fontFamily: 'monospace' }}>
                        {record.tracking_uuid}
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell>Template</TableCell>
                      <TableCell colSpan={2}>{record.template_name ?? '—'}</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
              </TableContainer>
            ) : null}
          </>
        ) : null}
      </DialogContent>

      <DialogActions>
        {employeeId ? (
          <Button
            component={RouterLink}
            to={`/employees/${employeeId}`}
            startIcon={<OpenInNewIcon />}
          >
            Full employee profile
          </Button>
        ) : null}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
