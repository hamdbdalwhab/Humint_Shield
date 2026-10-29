/**
 * Security Recommendations tab.
 *
 * A short, actionable layer over `DEFENSIVE_PLAYBOOK.md`.  The detailed Sigma
 * rules, KQL queries, incident-response phases and hardening steps are
 * downloadable as Markdown so the dashboard stays readable while the full
 * engineering reference remains one click away.
 */
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import { BookOpen, Download, ShieldCheck, Usb } from 'lucide-react';
import { useMemo, useState } from 'react';
import toast from 'react-hot-toast';

import { securityApi } from '@/api/endpoints';
import { errorMessage } from '@/lib/errors';
import {
  CATEGORY_LABELS,
  RECOMMENDATION_CATEGORIES,
  SECURITY_RECOMMENDATIONS,
  SEVERITY_LABELS,
  type RecommendationCategory,
  type RecommendationSeverity,
} from '@/lib/securityRecommendations';

const SEVERITY_STYLE: Record<
  RecommendationSeverity,
  { color: string; bg: string; border: string }
> = {
  critical: { color: '#FF8A9A', bg: 'rgba(255,23,68,.10)', border: 'rgba(255,23,68,.32)' },
  high: { color: '#FFC857', bg: 'rgba(255,176,32,.10)', border: 'rgba(255,176,32,.28)' },
  medium: { color: '#8BE9FD', bg: 'rgba(0,240,255,.08)', border: 'rgba(0,240,255,.24)' },
};

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function SecurityRecommendationsPanel() {
  const [category, setCategory] = useState<RecommendationCategory | 'all'>('all');
  const [playbookBusy, setPlaybookBusy] = useState(false);
  const [guideBusy, setGuideBusy] = useState(false);

  const visible = useMemo(
    () =>
      category === 'all'
        ? SECURITY_RECOMMENDATIONS
        : SECURITY_RECOMMENDATIONS.filter((item) => item.category === category),
    [category],
  );

  const criticalCount = SECURITY_RECOMMENDATIONS.filter(
    (item) => item.severity === 'critical',
  ).length;

  async function downloadPlaybook() {
    setPlaybookBusy(true);
    try {
      const blob = await securityApi.playbook();
      download(blob, 'DEFENSIVE_PLAYBOOK.md');
      toast.success('تم تحميل الدليل الدفاعي الكامل.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setPlaybookBusy(false);
    }
  }

  async function downloadUsbGuide() {
    setGuideBusy(true);
    try {
      const blob = await securityApi.usbGuide();
      download(blob, 'README_USB.md');
      toast.success('تم تحميل دليل تمرين USB.');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setGuideBusy(false);
    }
  }

  return (
    <Stack spacing={2.5}>
      <Card
        sx={{
          position: 'relative',
          overflow: 'hidden',
          border: '1px solid rgba(0,240,255,.20)',
          background:
            'radial-gradient(circle at 8% 20%, rgba(0,240,255,.14), transparent 38%), radial-gradient(circle at 92% 0%, rgba(112,0,255,.16), transparent 34%), linear-gradient(150deg, rgba(21,32,52,.94), rgba(8,13,24,.97))',
        }}
      >
        <CardContent sx={{ p: { xs: 2.2, md: 3 } }}>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', md: 'center' }}
            spacing={2}
          >
            <Box>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <Chip
                  size="small"
                  icon={<ShieldCheck size={13} />}
                  label="DEFENSIVE ONLY"
                  sx={{
                    bgcolor: 'rgba(0,230,118,.10)',
                    color: '#7DFFB2',
                    border: '1px solid rgba(0,230,118,.28)',
                    fontFamily: 'monospace',
                    fontSize: '0.62rem',
                  }}
                />
                <Chip
                  size="small"
                  label={`${criticalCount} توصية حرجة`}
                  sx={{ bgcolor: 'rgba(255,23,68,.10)', color: '#FF8A9A', fontSize: '0.62rem' }}
                />
              </Stack>
              <Typography sx={{ fontSize: { xs: '1.35rem', md: '1.65rem' }, fontWeight: 900, lineHeight: 1.4 }}>
                توصيات الأمان — من الفلاشة إلى الاستجابة
              </Typography>
              <Typography sx={{ color: 'text.secondary', fontSize: '0.82rem', lineHeight: 1.8, mt: 0.8, maxWidth: 760 }}>
                ثماني توصيات عملية مستخلصة من الدليل الدفاعي: حظر الوسائط غير المصرّح بها،
                تفعيل ASR، كشف الامتدادات المزدوجة وC2 Beaconing، وخطة استجابة جاهزة.
                كل توصية مرتبطة بقسمها في <span dir="ltr" className="mc-mono">DEFENSIVE_PLAYBOOK.md</span>.
              </Typography>
            </Box>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ flex: '0 0 auto' }}>
              <Button
                variant="contained"
                startIcon={playbookBusy ? <CircularProgress size={15} color="inherit" /> : <BookOpen size={16} />}
                onClick={downloadPlaybook}
                disabled={playbookBusy}
              >
                {playbookBusy ? 'جارٍ التحميل…' : 'تحميل Playbook'}
              </Button>
              <Button
                variant="outlined"
                startIcon={guideBusy ? <CircularProgress size={15} color="inherit" /> : <Usb size={16} />}
                onClick={downloadUsbGuide}
                disabled={guideBusy}
              >
                {guideBusy ? 'جارٍ التحميل…' : 'دليل USB'}
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        {RECOMMENDATION_CATEGORIES.map((entry) => {
          const active = category === entry.id;
          return (
            <Chip
              key={entry.id}
              clickable
              label={entry.label}
              onClick={() => setCategory(entry.id)}
              sx={{
                fontWeight: 700,
                bgcolor: active ? 'rgba(0,240,255,.14)' : 'rgba(255,255,255,.035)',
                color: active ? 'primary.main' : 'text.secondary',
                border: `1px solid ${active ? 'rgba(0,240,255,.45)' : 'rgba(255,255,255,.10)'}`,
              }}
            />
          );
        })}
      </Stack>

      <Grid container spacing={2}>
        {visible.map((item) => {
          const severity = SEVERITY_STYLE[item.severity];
          return (
            <Grid item xs={12} md={6} key={item.id}>
              <Card
                sx={{
                  height: '100%',
                  border: '1px solid rgba(255,255,255,.08)',
                  transition: 'border-color .2s ease, transform .2s ease',
                  '&:hover': {
                    borderColor: alpha('#00F0FF', 0.32),
                    transform: 'translateY(-2px)',
                  },
                }}
              >
                <CardContent sx={{ p: 2.2 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1}>
                    <Stack direction="row" spacing={0.7} useFlexGap flexWrap="wrap">
                      <Chip
                        size="small"
                        label={SEVERITY_LABELS[item.severity]}
                        sx={{
                          height: 22,
                          bgcolor: severity.bg,
                          color: severity.color,
                          border: `1px solid ${severity.border}`,
                          fontSize: '0.62rem',
                          fontWeight: 800,
                        }}
                      />
                      <Chip
                        size="small"
                        label={CATEGORY_LABELS[item.category]}
                        sx={{ height: 22, bgcolor: 'rgba(255,255,255,.045)', color: 'text.secondary', fontSize: '0.62rem' }}
                      />
                    </Stack>
                    <Download size={15} color="#4B5B73" />
                  </Stack>

                  <Typography sx={{ fontWeight: 900, fontSize: '0.98rem', lineHeight: 1.5, mt: 1.2 }}>
                    {item.title}
                  </Typography>
                  <Typography sx={{ color: 'text.secondary', fontSize: '0.76rem', lineHeight: 1.85, mt: 0.7 }}>
                    {item.summary}
                  </Typography>

                  <Divider sx={{ my: 1.5, borderColor: 'rgba(255,255,255,.07)' }} />

                  <Box
                    sx={{
                      p: 1.3,
                      borderRadius: 2,
                      bgcolor: 'rgba(2,7,15,.72)',
                      border: '1px solid rgba(0,240,255,.10)',
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                      fontSize: '0.68rem',
                      lineHeight: 1.8,
                      color: '#A9C7E8',
                      whiteSpace: 'pre-line',
                      overflowWrap: 'anywhere',
                    }}
                  >
                    {item.implementation}
                  </Box>

                  <Stack direction="row" spacing={0.6} alignItems="center" sx={{ mt: 1.2 }}>
                    <BookOpen size={12} color="#6E8299" />
                    <Typography sx={{ fontSize: '0.64rem', color: 'text.disabled', fontFamily: 'monospace' }}>
                      {item.reference}
                    </Typography>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>
          );
        })}
      </Grid>

      <Card sx={{ border: '1px dashed rgba(255,255,255,.12)', bgcolor: 'rgba(255,255,255,.02)' }}>
        <CardContent sx={{ py: 1.6 }}>
          <Typography sx={{ fontSize: '0.72rem', color: 'text.secondary', lineHeight: 1.8 }}>
            <strong>ملاحظة:</strong> هذه الصفحة تعرض توصيات دفاعية فقط. لا تحتوي على
            تعليمات لتنفيذ هجمات أو تعطيل ضوابط أمنية. اختبر كل قاعدة في وضع Audit قبل
            تفعيلها في الإنتاج، وراجع الاستثناءات مع فريق أمن المعلومات.
          </Typography>
        </CardContent>
      </Card>
    </Stack>
  );
}
