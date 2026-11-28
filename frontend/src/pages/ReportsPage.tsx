/**
 * Monthly awareness reports (module 5).
 *
 * Reads the immutable ``monthly_archives`` snapshots: average-Elo line chart,
 * a per-employee table, the monthly PDF report and a ZIP of all certificates.
 * The manual archive button is an admin-only convenience for deployments
 * without a Celery worker.
 *
 * The table is the relational heart of the page: every row links to the
 * employee dossier, can be filtered by department or free text, and the whole
 * filtered view exports to CSV so the data leaves the product in a usable form
 * instead of staying trapped in a chart.
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
import InputAdornment from '@mui/material/InputAdornment';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ArchiveIcon from '@mui/icons-material/Archive';
import DownloadIcon from '@mui/icons-material/Download';
import FolderZipIcon from '@mui/icons-material/FolderZip';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import SearchIcon from '@mui/icons-material/Search';
import { useEffect, useMemo, useState } from 'react';
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import toast from 'react-hot-toast';

import { employeesApi } from '@/api/endpoints';
import { EmptyState, LoadingState } from '@/components/Feedback';
import { PageHeader } from '@/components/PageHeader';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';

const SORT_OPTIONS = [
  { value: 'elo-asc', label: 'الأضعف أولاً (Elo تصاعدي)' },
  { value: 'elo-desc', label: 'الأقوى أولاً (Elo تنازلي)' },
  { value: 'clicks-desc', label: 'الأكثر نقراً أولاً' },
  { value: 'name-asc', label: 'الاسم أبجدياً' },
] as const;

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

function csvCell(value: unknown): string {
  const text = value == null ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

interface ArchiveRow {
  employee_id: string;
  employee_name: string;
  email: string;
  department: string | null;
  month_year: string;
  final_elo_score: number;
  total_reports: number;
  total_clicks: number;
  total_submissions: number;
  awareness_level_ar: string;
  is_blacklisted: boolean;
}

export function ReportsPage() {
  const { organizationId, user, can } = useAuth();
  const queryClient = useQueryClient();
  const [selectedMonth, setSelectedMonth] = useState('');
  const [downloading, setDownloading] = useState<'pdf' | 'zip' | null>(null);
  const [search, setSearch] = useState('');
  const [department, setDepartment] = useState('all');
  const [sort, setSort] = useState<(typeof SORT_OPTIONS)[number]['value']>('elo-asc');

  const trendQuery = useQuery({
    queryKey: ['monthly-elo-trend', organizationId],
    queryFn: () => employeesApi.monthlyEloTrend(organizationId as string),
    enabled: Boolean(organizationId),
  });

  const archivesQuery = useQuery({
    queryKey: ['monthly-archives', organizationId, selectedMonth],
    queryFn: () =>
      employeesApi.monthlyArchives(organizationId as string, selectedMonth || undefined),
    enabled: Boolean(organizationId),
    // Keep the month list and rows visible while a newly selected month loads.
    placeholderData: keepPreviousData,
  });

  useEffect(() => {
    if (!selectedMonth && archivesQuery.data?.month) {
      setSelectedMonth(archivesQuery.data.month);
    }
  }, [archivesQuery.data?.month, selectedMonth]);

  const archiveMutation = useMutation({
    mutationFn: () => employeesApi.runMonthlyArchive(organizationId as string, { force: true }),
    onSuccess: (result) => {
      toast.success(
        `تم أرشفة ${result.archived} موظفاً؛ أُضيف ${result.blacklisted} إلى قائمة الفشل المتكرر.`,
      );
      void queryClient.invalidateQueries({ queryKey: ['monthly-archives'] });
      void queryClient.invalidateQueries({ queryKey: ['monthly-elo-trend'] });
      void queryClient.invalidateQueries({ queryKey: ['employees'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const rows = useMemo<ArchiveRow[]>(
    () => (archivesQuery.data?.rows ?? []) as ArchiveRow[],
    [archivesQuery.data?.rows],
  );

  const departments = useMemo(() => {
    const seen = new Set<string>();
    for (const row of rows) {
      if (row.department) seen.add(row.department);
    }
    return Array.from(seen).sort((a, b) => a.localeCompare(b));
  }, [rows]);

  const visibleRows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = rows.filter((row) => {
      if (department !== 'all' && row.department !== department) return false;
      if (!needle) return true;
      return [row.employee_name, row.email, row.department]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle));
    });
    const sorted = [...filtered];
    switch (sort) {
      case 'elo-desc':
        sorted.sort((a, b) => b.final_elo_score - a.final_elo_score);
        break;
      case 'clicks-desc':
        sorted.sort((a, b) => b.total_clicks - a.total_clicks);
        break;
      case 'name-asc':
        sorted.sort((a, b) => a.employee_name.localeCompare(b.employee_name, 'ar'));
        break;
      default:
        sorted.sort((a, b) => a.final_elo_score - b.final_elo_score);
    }
    return sorted;
  }, [department, rows, search, sort]);

  const distribution = useMemo(() => {
    return {
      critical: visibleRows.filter((row) => row.final_elo_score < 700).length,
      atRisk: visibleRows.filter(
        (row) => row.final_elo_score >= 700 && row.final_elo_score < 900,
      ).length,
      solid: visibleRows.filter(
        (row) => row.final_elo_score >= 900 && row.final_elo_score < 1101,
      ).length,
      strong: visibleRows.filter((row) => row.final_elo_score >= 1101).length,
      blacklisted: visibleRows.filter((row) => row.is_blacklisted).length,
    };
  }, [visibleRows]);

  async function downloadMonthlyPdf(): Promise<void> {
    if (!organizationId || !selectedMonth) return;
    setDownloading('pdf');
    try {
      const blob = await employeesApi.monthlyReportPdf(organizationId, selectedMonth);
      saveBlob(blob, `monthly-report-${selectedMonth}.pdf`);
      toast.success('تم تنزيل تقرير الشهر.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setDownloading(null);
    }
  }

  async function downloadCertificates(): Promise<void> {
    if (!organizationId || !selectedMonth) return;
    setDownloading('zip');
    try {
      const blob = await employeesApi.certificatesZip(organizationId, selectedMonth);
      saveBlob(blob, `certificates-${selectedMonth}.zip`);
      toast.success('تم تنزيل حزمة الشهادات.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setDownloading(null);
    }
  }

  async function downloadCertificate(employeeId: string, employeeName: string): Promise<void> {
    if (!organizationId || !selectedMonth) return;
    try {
      const blob = await employeesApi.certificatePdf(organizationId, employeeId, selectedMonth);
      saveBlob(blob, `certificate-${employeeName}-${selectedMonth}.pdf`);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  function exportCsv(): void {
    if (!visibleRows.length || !selectedMonth) return;
    const header = [
      'month',
      'employee_id',
      'employee_name',
      'email',
      'department',
      'final_elo',
      'awareness_level',
      'reports',
      'clicks',
      'submissions',
      'blacklisted',
    ];
    const lines = [header.join(',')];
    for (const row of visibleRows) {
      lines.push(
        [
          row.month_year,
          row.employee_id,
          row.employee_name,
          row.email,
          row.department ?? '',
          row.final_elo_score,
          row.awareness_level_ar,
          row.total_reports,
          row.total_clicks,
          row.total_submissions,
          row.is_blacklisted ? 'yes' : 'no',
        ]
          .map(csvCell)
          .join(','),
      );
    }
    // The BOM keeps Arabic readable when the CSV opens in Excel.
    const blob = new Blob(['\uFEFF', lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    saveBlob(blob, `awareness-${selectedMonth}.csv`);
    toast.success(`تم تصدير ${visibleRows.length} صفاً إلى CSV.`);
  }

  const trend = trendQuery.data ?? [];
  const months = archivesQuery.data?.months ?? [];
  const canArchive = user?.role === 'admin' && can('employees.manage');
  const canExport = can('reports.view');

  return (
    <>
      <PageHeader
        title="تقارير الوعي الشهري"
        subtitle="متوسط Elo الشهري، أرشيف الدرجات، شهادات الموظفين وتقرير PDF قابل للمشاركة."
        actions={
          canArchive ? (
            <Button
              variant="outlined"
              startIcon={<ArchiveIcon />}
              disabled={archiveMutation.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    'سيتم أرشفة درجات الشهر الحالي وتصفير Elo لكل الموظفين إلى 1000. هل تريد المتابعة؟',
                  )
                ) {
                  archiveMutation.mutate();
                }
              }}
            >
              {archiveMutation.isPending ? 'جارٍ الأرشفة…' : 'أرشفة الشهر الحالي'}
            </Button>
          ) : null
        }
      />

      {trendQuery.isLoading ? (
        <LoadingState label="جارٍ تحميل اتجاه Elo…" />
      ) : trendQuery.error ? (
        <Alert severity="error">{errorMessage(trendQuery.error)}</Alert>
      ) : (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid item xs={12} md={3}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="overline" color="text.secondary">
                  متوسط Elo للشهر المحدد
                </Typography>
                <Typography variant="h3" sx={{ fontWeight: 800 }}>
                  {archivesQuery.data?.average_elo != null
                    ? archivesQuery.data.average_elo.toFixed(1)
                    : '—'}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {selectedMonth || 'لا يوجد شهر محدد'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={3}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="overline" color="text.secondary">
                  عرض الصفوف
                </Typography>
                <Typography variant="h3" sx={{ fontWeight: 800 }}>
                  {visibleRows.length}
                  <Typography component="span" variant="body2" color="text.secondary">
                    {' '}
                    / {rows.length}
                  </Typography>
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  بعد البحث والتصفية
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={3}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="overline" color="text.secondary">
                  معرّضون للخطر (Elo &lt; 900)
                </Typography>
                <Typography variant="h3" sx={{ fontWeight: 800, color: 'error.main' }}>
                  {distribution.critical + distribution.atRisk}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {distribution.critical} حرج · {distribution.atRisk} مرتفع
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={3}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Typography variant="overline" color="text.secondary">
                  قائمة الفشل المتكرر
                </Typography>
                <Typography variant="h3" sx={{ fontWeight: 800, color: 'warning.main' }}>
                  {distribution.blacklisted}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  بحاجة إلى تدريب إلزامي
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', sm: 'center' }}
            spacing={1}
            sx={{ mb: 2 }}
          >
            <Typography variant="h3" sx={{ fontSize: '1.05rem' }}>
              اتجاه متوسط Elo
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
              <Chip size="small" variant="outlined" label={`حرج: ${distribution.critical}`} />
              <Chip size="small" variant="outlined" label={`مرتفع: ${distribution.atRisk}`} />
              <Chip size="small" variant="outlined" label={`جيد: ${distribution.solid}`} />
              <Chip size="small" color="success" variant="outlined" label={`قوي: ${distribution.strong}`} />
            </Stack>
          </Stack>
          {trend.length === 0 ? (
            <EmptyState
              title="لا توجد أرشيفات شهرية بعد"
              description="شغّل مهمة الأرشفة في آخر يوم من الشهر أو استخدم زر الأرشفة اليدوية للمدير."
            />
          ) : (
            <Box sx={{ width: '100%', height: 300 }} dir="ltr">
              <ResponsiveContainer>
                <LineChart data={trend} margin={{ top: 8, right: 18, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.25} />
                  <XAxis dataKey="month_year" tick={{ fontSize: 12 }} />
                  <YAxis domain={[0, 2000]} tick={{ fontSize: 12 }} />
                  <ChartTooltip
                    formatter={(value) => [Number(value ?? 0).toFixed(1), 'Average Elo']}
                    labelFormatter={(label) => `Month ${label}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="average_elo"
                    stroke="#00B8D4"
                    strokeWidth={3}
                    dot={{ r: 4 }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Box>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            spacing={2}
            alignItems={{ xs: 'stretch', md: 'center' }}
            justifyContent="space-between"
            sx={{ mb: 2 }}
          >
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ flex: 1 }}>
              <TextField
                select
                size="small"
                label="الشهر"
                value={selectedMonth}
                onChange={(event) => setSelectedMonth(event.target.value)}
                sx={{ minWidth: 220 }}
                disabled={months.length === 0}
              >
                {months.map((month) => (
                  <MenuItem key={month.month_year} value={month.month_year}>
                    {month.month_year} · {month.employee_count} موظف · متوسط{' '}
                    {month.average_elo.toFixed(1)}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                size="small"
                label="بحث"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ minWidth: 220 }}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                }}
              />
              <TextField
                select
                size="small"
                label="القسم"
                value={department}
                onChange={(event) => setDepartment(event.target.value)}
                sx={{ minWidth: 170 }}
                disabled={departments.length === 0}
              >
                <MenuItem value="all">كل الأقسام</MenuItem>
                {departments.map((item) => (
                  <MenuItem key={item} value={item}>
                    {item}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                size="small"
                label="الترتيب"
                value={sort}
                onChange={(event) =>
                  setSort(event.target.value as (typeof SORT_OPTIONS)[number]['value'])
                }
                sx={{ minWidth: 190 }}
              >
                {SORT_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
              <Button
                variant="contained"
                startIcon={
                  downloading === 'pdf' ? (
                    <CircularProgress size={18} color="inherit" />
                  ) : (
                    <PictureAsPdfIcon />
                  )
                }
                disabled={!selectedMonth || downloading !== null || !canExport}
                onClick={() => void downloadMonthlyPdf()}
              >
                تقرير PDF الشهري
              </Button>
              <Button
                variant="outlined"
                startIcon={
                  downloading === 'zip' ? (
                    <CircularProgress size={18} color="inherit" />
                  ) : (
                    <FolderZipIcon />
                  )
                }
                disabled={!selectedMonth || downloading !== null || !canExport}
                onClick={() => void downloadCertificates()}
              >
                حزمة الشهادات ZIP
              </Button>
              <Button
                variant="outlined"
                startIcon={<DownloadIcon />}
                disabled={!visibleRows.length}
                onClick={exportCsv}
              >
                تصدير CSV
              </Button>
            </Stack>
          </Stack>

          {archivesQuery.isLoading ? (
            <LoadingState label="جارٍ تحميل الأرشيف…" />
          ) : archivesQuery.error ? (
            <Alert severity="error">{errorMessage(archivesQuery.error)}</Alert>
          ) : rows.length === 0 ? (
            <EmptyState
              title="لا توجد صفوف لهذا الشهر"
              description="اختر شهراً آخر أو شغّل الأرشفة أولاً."
            />
          ) : visibleRows.length === 0 ? (
            <EmptyState
              title="لا نتائج مطابقة"
              description="جرّب تعديل البحث أو اختيار قسم آخر."
            />
          ) : (
            <TableContainer sx={{ maxHeight: 560 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>الموظف</TableCell>
                    <TableCell>البريد</TableCell>
                    <TableCell>القسم</TableCell>
                    <TableCell align="center">Elo النهائي</TableCell>
                    <TableCell align="center">المستوى</TableCell>
                    <TableCell align="center">بلاغات</TableCell>
                    <TableCell align="center">نقرات</TableCell>
                    <TableCell align="center">إدخالات</TableCell>
                    <TableCell align="center">ملف</TableCell>
                    <TableCell align="center">شهادة</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {visibleRows.map((row) => (
                    <TableRow key={`${row.month_year}-${row.employee_id}`} hover>
                      <TableCell>
                        <Stack direction="row" spacing={0.75} alignItems="center">
                          <span>{row.employee_name}</span>
                          {row.is_blacklisted ? (
                            <Chip
                              size="small"
                              color="error"
                              label="فشل متكرر"
                              sx={{ fontWeight: 800 }}
                            />
                          ) : null}
                        </Stack>
                      </TableCell>
                      <TableCell>{row.email}</TableCell>
                      <TableCell>{row.department ?? '—'}</TableCell>
                      <TableCell align="center">
                        <Chip
                          size="small"
                          color={scoreColor(row.final_elo_score)}
                          label={row.final_elo_score}
                          sx={{ fontWeight: 800 }}
                        />
                      </TableCell>
                      <TableCell align="center">{row.awareness_level_ar}</TableCell>
                      <TableCell align="center">{row.total_reports}</TableCell>
                      <TableCell align="center">{row.total_clicks}</TableCell>
                      <TableCell align="center">{row.total_submissions}</TableCell>
                      <TableCell align="center">
                        <Tooltip title="ملف الموظف الكامل">
                          <IconButton
                            size="small"
                            component={RouterLink}
                            to={`/employees/${row.employee_id}`}
                          >
                            <OpenInNewIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                      <TableCell align="center">
                        <Tooltip title="تنزيل شهادة PDF">
                          <span>
                            <IconButton
                              size="small"
                              disabled={!canExport}
                              onClick={() =>
                                void downloadCertificate(row.employee_id, row.employee_name)
                              }
                            >
                              <DownloadIcon fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </CardContent>
      </Card>
    </>
  );
}
