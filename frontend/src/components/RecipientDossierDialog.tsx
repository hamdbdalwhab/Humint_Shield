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

/** Human label for the network telemetry block (battery/connection). */
function describeNetwork(network: unknown): string {
  if (!network || typeof network !== 'object') return '—';
  const net = network as {
    effective_type?: string;
    downlink_mbps?: number;
    online?: boolean;
  };
  return (
    [
      net.effective_type,
      net.downlink_mbps ? `${net.downlink_mbps} Mbps` : null,
      net.online === false ? 'offline' : null,
    ]
      .filter(Boolean)
      .join(' · ') || '—'
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

                
                {/* Anti-Evasion / Repeat Alert Banner */}
                {record.client_context && (record.client_context.repeat_status || record.client_context.status === 'evasion_attempt') ? (
                  <Alert
                    severity={record.client_context.status === 'evasion_attempt' ? 'error' : 'warning'}
                    sx={{ fontWeight: 700, fontSize: '0.85rem' }}
                  >
                    {String(record.client_context.repeat_status || '⚠️ محاولة تهرب / انتحال: الجهاز مسجل باسم موظف آخر!')}
                    {record.client_context.entered_email ? ` — البريد المدخل: ${String(record.client_context.entered_email)}` : ''}
                  </Alert>
                ) : null}

                {/* Elo & Security Rating Card */}
                <Box
                  sx={{
                    p: 1.8,
                    borderRadius: 2,
                    bgcolor: 'action.hover',
                    border: '1px solid rgba(0,240,255,0.25)',
                  }}
                >
                  <Grid container spacing={2} alignItems="center">
                    <Grid item xs={12} sm={4}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                        نقاط الوعي الأمني (Elo Rating)
                      </Typography>
                      <Typography variant="h5" sx={{ fontWeight: 900, color: (query.data.employee.elo_score ?? 1000) < 900 ? 'error.main' : 'primary.main' }}>
                        {query.data.employee.elo_score ?? 1000}
                      </Typography>
                    </Grid>
                    <Grid item xs={12} sm={4}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                        مستوى التهديد (Threat Level)
                      </Typography>
                      <Typography variant="body2" sx={{ fontWeight: 700 }}>
                        {query.data.employee.threat_level || ((query.data.employee.elo_score ?? 1000) < 900 ? 'مرتفع' : 'متوسط')}
                      </Typography>
                    </Grid>
                    <Grid item xs={12} sm={4}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                        خصم النقاط في هذه العملية
                      </Typography>
                      <Typography variant="body2" sx={{ fontWeight: 800, color: 'error.main' }}>
                        {record.client_context?.status === 'evasion_attempt' ? '-15 نقطة (محاولة تهرب)' : '-25 نقطة (تسجيل بيانات)'}
                      </Typography>
                    </Grid>
                  </Grid>
                </Box>

                {/* Deep Forensic Telemetry (Step 3: Cards/Table) */}
                {record.client_context ? (
                  <Box sx={{ mt: 1 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 800, color: 'primary.main', mb: 1.5 }}>
                      🔬 تفاصيل البصمة الجنائية والعتاد الحقيقي (Forensic Telemetry):
                    </Typography>

                    <Grid container spacing={1.5}>
                      {/* Hardware Card */}
                      <Grid item xs={12} md={6}>
                        <Box sx={{ p: 1.5, borderRadius: 2, border: '1px solid', borderColor: 'divider', height: '100%', bgcolor: 'background.paper' }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: 'info.main', display: 'block', mb: 1 }}>
                            🖥️ تفاصيل العتاد والمواصفات (Hardware)
                          </Typography>
                          <Stack spacing={0.6} sx={{ fontSize: '0.78rem' }}>
                            <div>
                              <strong>اسم الجهاز الحقيقي:</strong>{' '}
                              {String(
                                record.client_context.device_real_name ||
                                  record.client_context.hostname ||
                                  (record.client_context.mDNS_name
                                    ? 'مخفي بواسطة المتصفح — يظهر كاسم mDNS عشوائي أدناه'
                                    : 'غير متاح — المتصفح لا يكشف اسم الجهاز'),
                              )}
                            </div>
                            <div>
                              <strong>حساب Windows المسجّل:</strong>{' '}
                              {record.client_context.username ? (
                                String(record.client_context.username)
                              ) : (
                                <Typography component="span" variant="caption" color="text.secondary">
                                  غير متاح — صفحة HTML لا تستطيع قراءة اسم حساب النظام؛ شغّل أداة الهوية
                                  المحلية (HUMINT_Identity_Check.cmd) لتعبئته
                                </Typography>
                              )}
                            </div>
                            {String(record.client_context.identity_source || '') === 'local_tool' ? (
                              <Chip
                                size="small"
                                color="success"
                                variant="outlined"
                                label="الهوية من الأداة المحلية — قرأها السكربت على الجهاز نفسه"
                                sx={{ alignSelf: 'flex-start', fontWeight: 700, fontSize: '0.7rem' }}
                              />
                            ) : null}
                            <div><strong>المستخدم المسجّل على الجهاز:</strong> {String(record.client_context.windows_logged_on_user || '—')}</div>
                            <div><strong>النطاق / مجموعة العمل:</strong> {String(record.client_context.device_domain || '—')}</div>
                            <div><strong>نظام التشغيل:</strong> {String(record.client_context.os || '—')}</div>
                            <div><strong>إصدار النظام (Build):</strong> {String(record.client_context.os_build || '—')}</div>
                            <div>
                              <strong>الشركة المصنّعة / الطراز:</strong>{' '}
                              {[record.client_context.device_manufacturer, record.client_context.device_model]
                                .filter(Boolean)
                                .map(String)
                                .join(' — ') || '—'}
                            </div>
                            <div><strong>الرقم التسلسلي للجهاز:</strong> {String(record.client_context.device_serial || '—')}</div>
                            <div><strong>اسم المعالج:</strong> {String(record.client_context.cpu_model || '—')}</div>
                            <div>
                              <strong>صلاحيات الأداة:</strong>{' '}
                              {record.client_context.probe_elevated === true
                                ? 'مسؤول (Administrator)'
                                : record.client_context.probe_elevated === false
                                  ? 'مستخدم عادي'
                                  : '—'}
                            </div>
                            {String(record.client_context.identity_source || '') !== 'local_tool' ? (
                              <Typography variant="caption" color="text.secondary">
                                لم تُشغَّل الأداة المحلية على هذا الجهاز، لذلك اسم الحساب واسم الجهاز غير
                                متاحين من المتصفح. شغّل HUMINT_Identity_Check.cmd من الفلاشة لتعبئتهما.
                              </Typography>
                            ) : null}
                            <div><strong>معالج الرسوميات (GPU):</strong> {String(record.client_context.gpu_renderer || record.client_context.webgl_renderer || 'غير متاح')}</div>
                            <div><strong>أنوية المعالج (CPU Cores):</strong> {String(record.client_context.cpu_cores ?? 'غير متاح')}</div>
                            <div>
                              <strong>ذاكرة الجهاز (RAM):</strong>{' '}
                              {record.client_context.device_memory_gb
                                ? `${record.client_context.device_memory_gb} GB`
                                : 'غير متاح — هذا المتصفح لا يكشف الذاكرة'}
                            </div>
                            <div><strong>بصمة العتاد:</strong> <span style={{ fontFamily: 'monospace', wordBreak: 'break-all', fontSize: '0.72rem' }}>{String(record.client_context.hardware_fingerprint || record.client_context.fingerprint_hash || '—')}</span></div>
                          </Stack>
                        </Box>
                      </Grid>

                      {/* Network Card */}
                      <Grid item xs={12} md={6}>
                        <Box sx={{ p: 1.5, borderRadius: 2, border: '1px solid', borderColor: 'divider', height: '100%', bgcolor: 'background.paper' }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: 'success.main', display: 'block', mb: 1 }}>
                            🌐 بيانات الشبكة والاتصال (Network)
                          </Typography>
                          <Stack spacing={0.6} sx={{ fontSize: '0.78rem' }}>
                            <div>
                              <strong>الآيبي المحلي (Local IP):</strong>{' '}
                              {String(
                                record.client_context.local_ip ||
                                  (record.client_context.mDNS_name
                                    ? 'مخفي بواسطة المتصفح (mDNS)'
                                    : record.client_context.public_ip || '—'),
                              )}
                            </div>
                            <div><strong>اسم الجهاز بالشبكة (mDNS):</strong> {String(record.client_context.mDNS_name || '—')}</div>
                            <div><strong>الآيبي العام (WAN):</strong> {String(record.client_context.public_ip || '—')}</div>
                            <div><strong>الموقع الجغرافي:</strong> {[record.client_context.city, record.client_context.country].filter(Boolean).join(', ') || '—'}</div>
                            <div><strong>مزود الخدمة (ISP):</strong> {String(record.client_context.isp || '—')}</div>
                            {record.client_context.network ? (
                              <div>
                                <strong>نوع الاتصال:</strong>{' '}
                                {describeNetwork(record.client_context.network)}
                              </div>
                            ) : null}
                          </Stack>
                        </Box>
                      </Grid>

                      {/* Screen & Display Card */}
                      <Grid item xs={12} md={6}>
                        <Box sx={{ p: 1.5, borderRadius: 2, border: '1px solid', borderColor: 'divider', height: '100%', bgcolor: 'background.paper' }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: 'warning.main', display: 'block', mb: 1 }}>
                            📱 الشاشة والمتصفح (Display & Browser)
                          </Typography>
                          <Stack spacing={0.6} sx={{ fontSize: '0.78rem' }}>
                            <div><strong>دقة الشاشة:</strong> {String(record.client_context.screen_resolution || '—')}</div>
                            <div><strong>نسبة البكسل:</strong> {String(record.client_context.pixel_ratio ?? '—')}</div>
                            <div><strong>لغة الجهاز:</strong> {String(record.client_context.language || '—')}</div>
                            <div><strong>المنطقة الزمنية:</strong> {String(record.client_context.timezone || '—')}</div>
                            <div><strong>المتصفح:</strong> {String(record.client_context.browser || '—')}</div>
                            <div><strong>User-Agent:</strong> <span style={{ fontSize: '0.72rem', wordBreak: 'break-all' }}>{String(record.client_context.user_agent || '—')}</span></div>
                          </Stack>
                        </Box>
                      </Grid>

                      {/* Anti-Evasion Binding Card */}
                      <Grid item xs={12} md={6}>
                        <Box sx={{ p: 1.5, borderRadius: 2, border: '1px solid', borderColor: 'divider', height: '100%', bgcolor: 'background.paper' }}>
                          <Typography variant="caption" sx={{ fontWeight: 800, color: 'secondary.main', display: 'block', mb: 1 }}>
                            🛡️ حالة ارتباط الجهاز (Device Binding)
                          </Typography>
                          <Stack spacing={0.6} sx={{ fontSize: '0.78rem' }}>
                            <div><strong>حالة المسح:</strong> {record.client_context.status === 'evasion_attempt' ? 'محاولة تهرب / انتحال' : record.client_context.status === 'repeat_scan' ? 'تكرار مسح' : 'مسح أول'}</div>
                            {record.client_context.device_owner_name ? (
                              <div><strong>صاحب الجهاز المعتمد:</strong> {String(record.client_context.device_owner_name)}</div>
                            ) : null}
                            {record.client_context.entered_email ? (
                              <div><strong>البريد المدخل من الماسح:</strong> {String(record.client_context.entered_email)}</div>
                            ) : null}
                            <div><strong>عدد مرات المسح:</strong> {String(record.client_context.scan_count || 1)}</div>
                          </Stack>
                        </Box>
                      </Grid>
                    </Grid>
                  </Box>
                ) : null}

                {record.client_context ? (
                  <Alert severity="info" variant="outlined">
                    Browser context recorded with the submission:{' '}
                    {Object.entries(record.client_context)
                      .filter(([, value]) => value !== null && value !== '')
                      .map(
                        ([key, value]) =>
                          `${key}=${typeof value === 'object' ? JSON.stringify(value) : String(value)}`,
                      )
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
