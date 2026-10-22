/**
 * Command Centre dashboard.
 *
 * Every number, sparkline and feed row comes from the live API. There is no
 * sample data: the seven-day series is computed from the interaction ledger,
 * and the activity feed is the newest ledger rows across all campaigns.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Eye,
  Flame,
  KeyRound,
  Mail,
  Megaphone,
  MousePointerClick,
  Radar,
  ScanEye,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
  Zap,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Link from '@mui/material/Link';
import type { ReactNode } from 'react';

import { lmsApi } from '@/api/endpoints';
import { LoadingState } from '@/components/Feedback';
import { KpiCard } from '@/components/KpiCard';
import { CampaignStatusBadge } from '@/components/StatusBadge';
import { useAuth } from '@/hooks/useAuth';
import { errorMessage } from '@/lib/errors';
import { arabicGreeting, formatDate, formatPercent, relativeArabic } from '@/lib/format';

const FUNNEL_COLORS = ['#5B6B84', '#00F0FF', '#FFB020', '#FF1744', '#00E676'];

function eventIcon(type: string) {
  if (type.includes('submitted')) return <KeyRound size={16} />;
  if (type.includes('click')) return <MousePointerClick size={16} />;
  if (type.includes('form_viewed')) return <ScanEye size={16} />;
  if (type.includes('reported') || type.includes('completed')) return <ShieldCheck size={16} />;
  return <Mail size={16} />;
}

function eventColor(type: string) {
  if (type.includes('submitted')) return '#FF1744';
  if (type.includes('click') || type.includes('form_viewed')) return '#FFB020';
  if (type.includes('reported') || type.includes('completed')) return '#00E676';
  return '#00F0FF';
}

function MiniStat({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: ReactNode;
  color: string;
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.25,
        px: 1.5,
        py: 1.25,
        borderRadius: 3,
        border: '1px solid rgba(255,255,255,.07)',
        bgcolor: 'rgba(255,255,255,.025)',
        transition: 'border-color .2s ease, background .2s ease',
        '&:hover': {
          borderColor: alpha(color, 0.35),
          bgcolor: alpha(color, 0.045),
        },
      }}
    >
      <Box
        sx={{
          width: 34,
          height: 34,
          borderRadius: 2,
          display: 'grid',
          placeItems: 'center',
          color,
          bgcolor: alpha(color, 0.09),
          border: `1px solid ${alpha(color, 0.20)}`,
          '& svg': { width: 16, height: 16 },
        }}
      >
        {icon}
      </Box>
      <Box>
        <Typography sx={{ fontSize: '1.1rem', fontWeight: 800, lineHeight: 1.1 }}>{value}</Typography>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.68rem' }}>
          {label}
        </Typography>
      </Box>
    </Box>
  );
}

export function DashboardPage() {
  const { organizationId, user } = useAuth();
  const navigate = useNavigate();
  const { data, isLoading, error } = useQuery({
    queryKey: ['dashboard', organizationId],
    queryFn: () => lmsApi.dashboard(organizationId as string),
    enabled: Boolean(organizationId),
    refetchInterval: 20_000,
  });

  if (!organizationId) {
    return <Alert severity="warning">حسابك غير مرتبط بأي مؤسسة.</Alert>;
  }
  if (isLoading) return <LoadingState label="جارٍ تحميل مركز القيادة…" />;
  if (error) return <Alert severity="error">{errorMessage(error)}</Alert>;
  if (!data) return null;

  const trend = data.engagement_trend ?? [];
  const activityVolume = trend.map((item) => item.opens + item.clicks + item.submissions);
  const events = data.recent_events ?? [];
  const activeCampaign = data.recent_campaigns.find((campaign) => campaign.status === 'active');
  const liveHref = activeCampaign ? `/campaigns/${activeCampaign.id}/live` : '/campaigns';

  const funnel = [
    { name: 'أُرسل', value: data.total_emails_sent },
    { name: 'فُتح', value: data.total_opened },
    { name: 'نُقر', value: data.total_clicked },
    { name: 'أُدخل', value: data.total_submitted },
    { name: 'اكتمل', value: data.total_completed },
  ];

  return (
    <>
      {/* ---------------- hero ---------------- */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
      >
        <Box
          sx={{
            position: 'relative',
            overflow: 'hidden',
            borderRadius: 4,
            p: { xs: 2.25, md: 3.25 },
            mb: 2.5,
            border: '1px solid rgba(0,240,255,.16)',
            background:
              'radial-gradient(circle at 90% 0%, rgba(0,240,255,.13), transparent 38%), radial-gradient(circle at 8% 100%, rgba(112,0,255,.18), transparent 42%), linear-gradient(145deg, rgba(22,33,55,.88), rgba(9,14,24,.82))',
            boxShadow: '0 30px 80px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.05)',
          }}
        >
          <Box className="mc-scan" sx={{ position: 'absolute', inset: 0, pointerEvents: 'none' }} />
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', md: 'center' }}
            spacing={2.5}
            sx={{ position: 'relative', zIndex: 1 }}
          >
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Box className="mc-live-dot" />
                <Typography
                  variant="overline"
                  sx={{ color: 'primary.main', fontSize: '0.66rem', letterSpacing: '.14em' }}
                >
                  LIVE HUMAN-RISK TELEMETRY
                </Typography>
              </Stack>
              <Typography
                component="h1"
                variant="h1"
                sx={{
                  fontSize: { xs: '1.7rem', md: '2.35rem' },
                  mb: 0.75,
                  '& span': { color: 'primary.main', textShadow: '0 0 28px rgba(0,240,255,.35)' },
                }}
              >
                {arabicGreeting()}، <span>{user?.username ?? 'قائد الفريق'}</span>
              </Typography>
              <Typography sx={{ color: 'text.secondary', maxWidth: 720, fontSize: { xs: '0.85rem', md: '0.94rem' } }}>
                هذه ليست لوحة إحصاءات. هذه غرفة عمليات حيّة تعرض كل فتح، كل نقرة، وكل قيمة
                يكتبها موظفك — بالثانية والدقيقة، وبأدلة غير قابلة للإنكار.
              </Typography>
            </Box>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} sx={{ flex: '0 0 auto' }}>
              <Button
                variant="contained"
                startIcon={<Zap size={17} />}
                onClick={() => navigate('/campaigns/new')}
              >
                حملة جديدة
              </Button>
              <Button
                variant="outlined"
                startIcon={<Radar size={17} />}
                onClick={() => navigate(liveHref)}
              >
                المراقبة الحية
              </Button>
            </Stack>
          </Stack>

          <Stack direction="row" spacing={1} sx={{ mt: 2.5, flexWrap: 'wrap', gap: 0.75, position: 'relative', zIndex: 1 }}>
            <Chip
              size="small"
              icon={<Activity size={13} />}
              label={`${events.length} حدث تتبع حديث`}
              color="primary"
              variant="outlined"
            />
            <Chip
              size="small"
              icon={<Megaphone size={13} />}
              label={`${data.active_campaigns} حملة نشطة`}
              color="info"
              variant="outlined"
            />
            <Chip
              size="small"
              icon={<AlertTriangle size={13} />}
              label={`${data.critical_risk_employees} موظف في خطر حرج`}
              color="error"
              variant="outlined"
            />
          </Stack>
        </Box>
      </motion.div>

      {/* ---------------- primary KPIs ---------------- */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} sm={6} lg={3}>
          <KpiCard
            label="إجمالي الموظفين"
            value={data.total_employees}
            helper={`${data.active_employees} حساب نشط`}
            data={activityVolume}
            icon={<Users size={20} />}
            tone="cyan"
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <KpiCard
            label="معدل الفتح"
            value={formatPercent(data.open_rate)}
            helper={`${data.total_opened} رسالة فُتحت`}
            data={trend.map((item) => item.opens)}
            icon={<Eye size={20} />}
            tone="blue"
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <KpiCard
            label="معدل النقر"
            value={formatPercent(data.click_rate)}
            helper={`${data.total_clicked} نقرة مسجّلة`}
            data={trend.map((item) => item.clicks)}
            icon={<MousePointerClick size={20} />}
            tone="amber"
          />
        </Grid>
        <Grid item xs={12} sm={6} lg={3}>
          <KpiCard
            label="المخاطر الحرجة"
            value={data.critical_risk_employees}
            helper="موظفون يحتاجون تدخلاً فورياً"
            data={trend.map((item) => item.submissions)}
            icon={<AlertTriangle size={20} />}
            tone="red"
            pulse={data.critical_risk_employees > 0}
          />
        </Grid>
      </Grid>

      {/* ---------------- secondary strip ---------------- */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(3, minmax(0, 1fr))', lg: 'repeat(6, minmax(0, 1fr))' },
          gap: 1.25,
          mb: 2.5,
        }}
      >
        <MiniStat label="الحملات" value={data.total_campaigns} icon={<Megaphone />} color="#00F0FF" />
        <MiniStat label="رسائل أُرسلت" value={data.total_emails_sent} icon={<Mail />} color="#38BDF8" />
        <MiniStat label="نماذج أُدخلت" value={data.total_submitted} icon={<KeyRound />} color="#FF1744" />
        <MiniStat label="تدريب مكتمل" value={data.total_completed} icon={<ShieldCheck />} color="#00E676" />
        <MiniStat label="القوالب" value={data.total_templates} icon={<Sparkles />} color="#B388FF" />
        <MiniStat label="بلاغات معلّقة" value={data.reports_pending} icon={<Target />} color="#FFB020" />
      </Box>

      {/* ---------------- charts + live feed ---------------- */}
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} xl={8}>
          <Grid container spacing={2}>
            <Grid item xs={12} lg={6}>
              <Card sx={{ height: '100%' }}>
                <CardContent sx={{ p: 2.25 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1.5 }}>
                    <Box>
                      <Typography variant="h3" sx={{ fontSize: '1rem' }}>
                        قمع التفاعل
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        من الإرسال إلى إكمال التدريب
                      </Typography>
                    </Box>
                    <Chip size="small" label="ALL CAMPAIGNS" color="primary" variant="outlined" />
                  </Stack>
                  <Box sx={{ height: 285 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={funnel} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
                        <CartesianGrid stroke="rgba(255,255,255,.055)" vertical={false} />
                        <XAxis
                          dataKey="name"
                          reversed
                          tick={{ fill: '#8B9BB4', fontSize: 11 }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <YAxis
                          orientation="right"
                          width={34}
                          tick={{ fill: '#64748B', fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <ChartTooltip
                          contentStyle={{
                            background: 'rgba(11,18,32,.96)',
                            border: '1px solid rgba(0,240,255,.22)',
                            borderRadius: 12,
                            fontFamily: 'Cairo, sans-serif',
                            fontSize: 12,
                          }}
                          cursor={{ fill: 'rgba(0,240,255,.04)' }}
                        />
                        <Bar dataKey="value" radius={[8, 8, 0, 0]} maxBarSize={54}>
                          {funnel.map((entry, index) => (
                            <Cell key={entry.name} fill={FUNNEL_COLORS[index]} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </Box>
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} lg={6}>
              <Card sx={{ height: '100%' }}>
                <CardContent sx={{ p: 2.25 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" sx={{ mb: 1.5 }}>
                    <Box>
                      <Typography variant="h3" sx={{ fontSize: '1rem' }}>
                        نبض آخر 7 أيام
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        فتح · نقر · إدخال بيانات
                      </Typography>
                    </Box>
                    <Box className="mc-live-dot" sx={{ mt: 0.75 }} />
                  </Stack>
                  <Box sx={{ height: 285 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={trend} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
                        <defs>
                          <linearGradient id="trendCyan" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#00F0FF" stopOpacity={0.35} />
                            <stop offset="100%" stopColor="#00F0FF" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="trendViolet" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#B388FF" stopOpacity={0.28} />
                            <stop offset="100%" stopColor="#B388FF" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid stroke="rgba(255,255,255,.055)" vertical={false} />
                        <XAxis
                          dataKey="date"
                          reversed
                          tickFormatter={(value: string) => value.slice(5)}
                          tick={{ fill: '#8B9BB4', fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <YAxis
                          orientation="right"
                          width={34}
                          tick={{ fill: '#64748B', fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                        />
                        <ChartTooltip
                          contentStyle={{
                            background: 'rgba(11,18,32,.96)',
                            border: '1px solid rgba(0,240,255,.22)',
                            borderRadius: 12,
                            fontFamily: 'Cairo, sans-serif',
                            fontSize: 12,
                          }}
                        />
                        <Area type="monotone" dataKey="opens" stroke="#00F0FF" strokeWidth={2} fill="url(#trendCyan)" />
                        <Area type="monotone" dataKey="clicks" stroke="#B388FF" strokeWidth={2} fill="url(#trendViolet)" />
                        <Area type="monotone" dataKey="submissions" stroke="#FF1744" strokeWidth={2} fill="transparent" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </Grid>

        <Grid item xs={12} xl={4}>
          <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <CardContent sx={{ p: 2.25, pb: 1, flex: 1 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Box
                    sx={{
                      width: 32,
                      height: 32,
                      borderRadius: 2,
                      display: 'grid',
                      placeItems: 'center',
                      color: 'primary.main',
                      bgcolor: 'rgba(0,240,255,.08)',
                      border: '1px solid rgba(0,240,255,.18)',
                    }}
                  >
                    <Activity size={17} />
                  </Box>
                  <Box>
                    <Typography variant="h3" sx={{ fontSize: '1rem' }}>
                      البث الحيّ
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      آخر الأحداث من سجل التتبع
                    </Typography>
                  </Box>
                </Stack>
                <Box className="mc-live-dot" />
              </Stack>

              {events.length === 0 ? (
                <Box sx={{ py: 5, textAlign: 'center' }}>
                  <Flame size={26} color="#8B9BB4" />
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    لا توجد أحداث بعد. أطلق حملة لتبدأ المراقبة.
                  </Typography>
                </Box>
              ) : (
                <Stack spacing={0} sx={{ maxHeight: 340, overflowY: 'auto', pr: 0.5 }}>
                  {events.slice(0, 7).map((event, index) => {
                    const color = eventColor(event.event_type);
                    return (
                      <motion.div
                        key={event.id}
                        initial={{ opacity: 0, x: 14 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: index * 0.04, duration: 0.3 }}
                        style={{ display: 'flex', gap: 10, paddingBottom: 12 }}
                      >
                        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', pt: 0.3 }}>
                          <Box
                            sx={{
                              width: 28,
                              height: 28,
                              borderRadius: '50%',
                              display: 'grid',
                              placeItems: 'center',
                              color,
                              bgcolor: alpha(color, 0.10),
                              border: `1px solid ${alpha(color, 0.28)}`,
                              flex: '0 0 auto',
                            }}
                          >
                            {eventIcon(event.event_type)}
                          </Box>
                          {index < Math.min(events.length, 7) - 1 ? (
                            <Box sx={{ width: 1, flex: 1, bgcolor: 'rgba(255,255,255,.08)', my: 0.5 }} />
                          ) : null}
                        </Box>
                        <Box sx={{ minWidth: 0, flex: 1 }}>
                          <Typography sx={{ fontSize: '0.78rem', fontWeight: 700, lineHeight: 1.55 }}>
                            {event.employee_name}
                            <Box component="span" sx={{ color, fontWeight: 700 }}>
                              {' '}· {event.label}
                            </Box>
                          </Typography>
                          <Typography variant="caption" color="text.secondary" noWrap display="block">
                            {event.campaign_name}
                          </Typography>
                          <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.64rem' }}>
                            {relativeArabic(event.occurred_at)}
                          </Typography>
                        </Box>
                      </motion.div>
                    );
                  })}
                </Stack>
              )}
            </CardContent>
            <Divider />
            <Button
              fullWidth
              size="small"
              endIcon={<ArrowUpRight size={15} />}
              onClick={() => navigate(liveHref)}
              sx={{ borderRadius: 0, py: 1.1 }}
            >
              فتح لوحة المراقبة
            </Button>
          </Card>
        </Grid>
      </Grid>

      {/* ---------------- recent campaigns ---------------- */}
      <Card>
        <CardContent sx={{ p: 2.25 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
            <Box>
              <Typography variant="h3" sx={{ fontSize: '1rem' }}>
                أحدث الحملات
              </Typography>
              <Typography variant="caption" color="text.secondary">
                آخر خمس حملات أُطلقت في مساحة عملك
              </Typography>
            </Box>
            <Button component={RouterLink} to="/campaigns" size="small" endIcon={<ArrowUpRight size={14} />}>
              عرض الكل
            </Button>
          </Stack>

          <Box className="mc-scroll-x">
            <Table size="small" className="mc-table-stagger">
              <TableHead>
                <TableRow>
                  <TableCell>الحملة</TableCell>
                  <TableCell>الحالة</TableCell>
                  <TableCell align="center">أُرسل</TableCell>
                  <TableCell align="center">فُتح</TableCell>
                  <TableCell align="center">نُقر</TableCell>
                  <TableCell align="center">اكتمل</TableCell>
                  <TableCell>التاريخ</TableCell>
                  <TableCell align="center">إجراء</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.recent_campaigns.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} align="center" sx={{ py: 5, color: 'text.secondary' }}>
                      لا توجد حملات بعد. ابدأ من زر «حملة جديدة».
                    </TableCell>
                  </TableRow>
                ) : (
                  data.recent_campaigns.map((campaign) => (
                    <TableRow key={campaign.id} hover className="mc-hover-row">
                      <TableCell>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Box
                            sx={{
                              width: 30,
                              height: 30,
                              borderRadius: 1.5,
                              display: 'grid',
                              placeItems: 'center',
                              color: 'primary.main',
                              bgcolor: 'rgba(0,240,255,.07)',
                              border: '1px solid rgba(0,240,255,.14)',
                            }}
                          >
                            <Megaphone size={15} />
                          </Box>
                          <Link
                            component={RouterLink}
                            to={`/campaigns/${campaign.id}`}
                            underline="none"
                            sx={{ fontWeight: 700, color: 'text.primary', '&:hover': { color: 'primary.main' } }}
                          >
                            {campaign.name}
                          </Link>
                        </Stack>
                      </TableCell>
                      <TableCell>
                        <CampaignStatusBadge status={campaign.status} />
                      </TableCell>
                      <TableCell align="center" className="mc-mono">{campaign.sent}</TableCell>
                      <TableCell align="center" className="mc-mono" sx={{ color: 'info.main' }}>{campaign.opened}</TableCell>
                      <TableCell align="center" className="mc-mono" sx={{ color: 'warning.main' }}>{campaign.clicked}</TableCell>
                      <TableCell align="center" className="mc-mono" sx={{ color: 'success.main' }}>{campaign.completed}</TableCell>
                      <TableCell sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}>{formatDate(campaign.created_at)}</TableCell>
                      <TableCell align="center">
                        <Tooltip title="تفاصيل الحملة">
                          <IconButton size="small" aria-label={`عرض ${campaign.name}`} onClick={() => navigate(`/campaigns/${campaign.id}`)}>
                            <Eye size={16} />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </Box>
        </CardContent>
      </Card>
    </>
  );
}
