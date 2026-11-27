/**
 * Employee Intelligence Hub — `/employees/:employeeId/intelligence`.
 *
 * One screen answers every question an analyst has about a single employee:
 * who they are and how they score (header card), what happened and when
 * (timeline), what they actually typed (submitted data, passwords masked) and
 * which certificates they earned. All four come from one aggregated API call so
 * the numbers can never disagree with each other.
 *
 * Layout uses Flexbox/Grid + MUI `gap`. Nothing is absolutely positioned, so
 * long Arabic names and large timestamps wrap instead of overflowing.
 */
import Alert from '@mui/material/Alert';
import Avatar from '@mui/material/Avatar';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
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
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import BadgeIcon from '@mui/icons-material/Badge';
import DownloadIcon from '@mui/icons-material/Download';
import PrintIcon from '@mui/icons-material/Print';
import ReplayIcon from '@mui/icons-material/Replay';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { employeesApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { InteractionTimeline } from '@/components/InteractionTimeline';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { formatTime } from '@/lib/format';

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function scoreColor(score: number): 'success' | 'info' | 'warning' | 'error' {
  if (score >= 1101) return 'success';
  if (score >= 900) return 'info';
  if (score >= 700) return 'warning';
  return 'error';
}

export function EmployeeIntelligenceProfile() {
  const { employeeId } = useParams<{ employeeId: string }>();
  const { organizationId, can } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState(0);
  const [downloading, setDownloading] = useState(false);

  const intelligenceQuery = useQuery({
    queryKey: ['employee-intelligence', organizationId, employeeId],
    queryFn: () => employeesApi.intelligence(organizationId as string, employeeId as string),
    enabled: Boolean(organizationId && employeeId),
  });

  const canExport = can('reports.view');
  const data = intelligenceQuery.data;

  if (!employeeId) {
    return <Alert severity="error">لم يتم تحديد موظف.</Alert>;
  }
  if (intelligenceQuery.isLoading) {
    return <LoadingState label="جارٍ تحميل الملف الاستخباراتي…" />;
  }
  if (intelligenceQuery.error || !data) {
    return (
      <Alert severity="error">
        {intelligenceQuery.error ? errorMessage(intelligenceQuery.error) : 'الملف غير متاح.'}
      </Alert>
    );
  }

  async function downloadReport(): Promise<void> {
    if (!organizationId || !employeeId) return;
    setDownloading(true);
    try {
      const blob = await employeesApi.reportPdf(organizationId, employeeId);
      saveBlob(blob, `employee-report-${employeeId}.pdf`);
      toast.success('تم تنزيل تقرير الموظف.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setDownloading(false);
    }
  }

  async function printCertificate(monthYear?: string): Promise<void> {
    if (!organizationId || !employeeId) return;
    try {
      const blob = await employeesApi.certificatePdf(
        organizationId,
        employeeId,
        monthYear ?? new Date().toISOString().slice(0, 7),
      );
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener,noreferrer');
      // Give the new tab time to load before revoking the object URL.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  const { employee, elo, summary, events, submissions, certificates, journeys } = data;

  return (
    <>
      <Button
        size="small"
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/employees')}
        sx={{ mb: 1 }}
      >
        الموظفون
      </Button>

      <PageHeader
        title="الملف الاستخباراتي للموظف"
        subtitle="الصورة الكاملة: الملف الشخصي، درجة Elo، الخط الزمني، البيانات المدخلة والشهادات."
        actions={
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button
              variant="contained"
              startIcon={
                downloading ? <CircularProgress size={16} color="inherit" /> : <DownloadIcon />
              }
              disabled={!canExport || downloading}
              onClick={() => void downloadReport()}
            >
              تقرير الموظف PDF
            </Button>
            <Button
              variant="outlined"
              startIcon={<PrintIcon />}
              disabled={!canExport}
              onClick={() => void printCertificate(certificates[0]?.month_year)}
            >
              طباعة الشهادة
            </Button>
            <Button
              variant="outlined"
              color="warning"
              startIcon={<ReplayIcon />}
              onClick={() => navigate(`/campaigns/new?employeeId=${employee.id}`)}
            >
              إعادة اختبار
            </Button>
          </Stack>
        }
      />

      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            spacing={2}
            alignItems={{ xs: 'flex-start', md: 'center' }}
            justifyContent="space-between"
            flexWrap="wrap"
            useFlexGap
          >
            <Stack direction="row" spacing={2} alignItems="center" sx={{ minWidth: 0 }}>
              <Avatar sx={{ width: 56, height: 56, bgcolor: 'primary.main', fontWeight: 800 }}>
                {(employee.first_name || employee.email).charAt(0).toUpperCase()}
              </Avatar>
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="h5" sx={{ fontWeight: 800, wordBreak: 'break-word' }}>
                  {employee.full_name}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-word' }}>
                  {employee.email}
                </Typography>
                <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mt: 0.75 }}>
                  <Chip size="small" variant="outlined" label={employee.department || 'بلا قسم'} />
                  <Chip size="small" variant="outlined" label={employee.job_title || 'بلا مسمى'} />
                  <Chip
                    size="small"
                    variant="outlined"
                    label={elo.category || 'غير مصنّف'}
                  />
                  {employee.is_blacklisted ? (
                    <Chip size="small" color="error" label="فشل متكرر" />
                  ) : null}
                  {employee.under_enhanced_monitoring ? (
                    <Chip size="small" color="warning" label="مراقبة معزّزة" />
                  ) : null}
                  {!employee.is_active ? (
                    <Chip size="small" label="غير نشط" />
                  ) : null}
                </Stack>
              </Box>
            </Stack>

            <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap alignItems="center">
              <Box sx={{ textAlign: 'center' }}>
                <Typography variant="overline" color="text.secondary">
                  Elo
                </Typography>
                <Typography variant="h3" sx={{ fontWeight: 800, lineHeight: 1 }}>
                  {elo.score}
                </Typography>
                <Chip size="small" color={scoreColor(elo.score)} label={elo.level_ar} />
              </Box>
              <Divider orientation="vertical" flexItem sx={{ display: { xs: 'none', sm: 'block' } }} />
              <Stack spacing={0.5}>
                <Stack direction="row" spacing={1} alignItems="baseline">
                  <Typography variant="caption" color="text.secondary">
                    بلاغات
                  </Typography>
                  <Typography sx={{ fontWeight: 700 }}>{elo.total_reports}</Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="baseline">
                  <Typography variant="caption" color="text.secondary">
                    نقرات
                  </Typography>
                  <Typography sx={{ fontWeight: 700 }}>{elo.total_clicks}</Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="baseline">
                  <Typography variant="caption" color="text.secondary">
                    إدخالات
                  </Typography>
                  <Typography sx={{ fontWeight: 700 }}>{elo.total_submissions}</Typography>
                </Stack>
              </Stack>
            </Stack>
          </Stack>

          <Divider sx={{ my: 2 }} />

          <Grid container spacing={1.5}>
            {[
              { label: 'الحملات', value: summary.campaigns },
              { label: 'أُرسلت', value: summary.emails_sent },
              { label: 'فُتحت', value: summary.opened },
              { label: 'نُقرت', value: summary.clicked },
              { label: 'إدخالات', value: summary.submitted },
              { label: 'بلاغات', value: summary.reported },
              { label: 'أكمل التدريب', value: summary.completed },
              { label: 'تفاعلات', value: summary.total_interactions },
            ].map((item) => (
              <Grid item xs={6} sm={3} md={1.5} key={item.label}>
                <Box sx={{ p: 1, borderRadius: 1.5, bgcolor: 'action.hover', textAlign: 'center' }}>
                  <Typography variant="h6" sx={{ fontWeight: 800, lineHeight: 1.1 }}>
                    {item.value}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {item.label}
                  </Typography>
                </Box>
              </Grid>
            ))}
          </Grid>
        </CardContent>
      </Card>

      <Card>
        <Tabs
          value={tab}
          onChange={(_event, value: number) => setTab(value)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ borderBottom: 1, borderColor: 'divider' }}
        >
          <Tab label={`الخط الزمني (${events.length})`} />
          <Tab label={`البيانات المدخلة (${submissions.length})`} />
          <Tab label={`الشهادات (${certificates.length})`} />
        </Tabs>

        {tab === 0 ? (
          <CardContent>
            {journeys.length > 0 ? (
              <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
                {journeys.map((journey) => (
                  <Chip
                    key={journey.campaign_id}
                    size="small"
                    variant="outlined"
                    icon={<BadgeIcon />}
                    label={`${journey.campaign_name} · ${journey.channel}${
                      journey.journey_id ? ` · ${journey.journey_id.slice(0, 8)}` : ''
                    }`}
                  />
                ))}
              </Stack>
            ) : null}
            {events.length === 0 ? (
              <EmptyState
                title="لا توجد أحداث"
                description="لم يُسجَّل أي تفاعل لهذا الموظف بعد."
              />
            ) : (
              <InteractionTimeline events={[...events].reverse()} showCampaign />
            )}
          </CardContent>
        ) : null}

        {tab === 1 ? (
          <CardContent>
            {submissions.length === 0 ? (
              <EmptyState
                title="لا توجد بيانات مدخلة"
                description="لم يُدخل الموظف أي بيانات في أي صفحة تصيّد."
              />
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>الوقت</TableCell>
                      <TableCell>الحملة</TableCell>
                      <TableCell>IP</TableCell>
                      <TableCell align="center">طول كلمة المرور</TableCell>
                      <TableCell>القيم (مقنّعة)</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {[...submissions].reverse().map((submission, index) => (
                      <TableRow key={`${submission.occurred_at}-${index}`}>
                        <TableCell sx={{ whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
                          {submission.occurred_at
                            ? `${formatTime(submission.occurred_at)} · ${submission.occurred_at.slice(0, 10)}`
                            : '—'}
                        </TableCell>
                        <TableCell>{submission.campaign_name || '—'}</TableCell>
                        <TableCell sx={{ fontFamily: 'monospace' }}>{submission.ip_address || '—'}</TableCell>
                        <TableCell align="center">{submission.password_length ?? '—'}</TableCell>
                        <TableCell sx={{ wordBreak: 'break-word' }}>
                          <Stack spacing={0.25}>
                            {Object.entries(submission.values || {}).map(([key, value]) => (
                              <Typography key={key} variant="caption" sx={{ wordBreak: 'break-all' }}>
                                <strong>{key}</strong>: {String(value)}
                              </Typography>
                            ))}
                          </Stack>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </CardContent>
        ) : null}

        {tab === 2 ? (
          <CardContent>
            {certificates.length === 0 ? (
              <EmptyState
                title="لا توجد شهادات"
                description="تُصدر الشهادة تلقائياً عند أرشفة الشهر أو يمكن طباعتها من الشهر الحالي."
              />
            ) : (
              <Grid container spacing={2}>
                {certificates.map((certificate) => (
                  <Grid item xs={12} sm={6} md={4} key={certificate.month_year}>
                    <Card variant="outlined" sx={{ height: '100%' }}>
                      <CardContent>
                        <Stack spacing={1}>
                          <Typography variant="overline" color="text.secondary">
                            {certificate.month_year}
                          </Typography>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <Typography variant="h4" sx={{ fontWeight: 800 }}>
                              {certificate.final_elo_score}
                            </Typography>
                            <Chip
                              size="small"
                              color={scoreColor(certificate.final_elo_score)}
                              label={certificate.level_ar}
                            />
                          </Stack>
                          <Typography variant="caption" color="text.secondary">
                            بلاغات {certificate.total_reports} · نقرات {certificate.total_clicks} · إدخالات{' '}
                            {certificate.total_submissions}
                          </Typography>
                          <Tooltip title="تنزيل الشهادة">
                            <span>
                              <Button
                                size="small"
                                startIcon={<DownloadIcon />}
                                disabled={!canExport}
                                onClick={() => void printCertificate(certificate.month_year)}
                              >
                                تنزيل
                              </Button>
                            </span>
                          </Tooltip>
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
    </>
  );
}

export default EmployeeIntelligenceProfile;
