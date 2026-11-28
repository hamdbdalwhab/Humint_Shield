/**
 * Impact evidence panel for the training experience.
 *
 * After a recipient falls for a simulation the page has to prove the risk with
 * facts, not adjectives: exactly what was captured (masked), where it came
 * from (device / network / time), and what it cost them and their department.
 * The data comes from `GET /api/v1/track/evidence/:uuid`, which never returns
 * a password value and only the recipient's own row.
 */
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { useQuery } from '@tanstack/react-query';
import {
  Clock3,
  Fingerprint,
  Globe2,
  KeyRound,
  Laptop,
  ShieldAlert,
  TrendingDown,
  Users,
} from 'lucide-react';

import { trackingApi, type TrackingEvidence } from '@/api/endpoints';

type Tone = 'danger' | 'warn' | 'info';

const TONES: Record<Tone, { border: string; bg: string; text: string }> = {
  danger: {
    border: 'rgba(255,23,68,.32)',
    bg: 'rgba(255,23,68,.09)',
    text: '#FF6B81',
  },
  warn: {
    border: 'rgba(255,171,0,.32)',
    bg: 'rgba(255,171,0,.09)',
    text: '#FFC94D',
  },
  info: {
    border: 'rgba(64,196,255,.3)',
    bg: 'rgba(64,196,255,.08)',
    text: '#6FD3FF',
  },
};

interface EvidenceTileProps {
  icon: typeof Clock3;
  label: string;
  value: string;
  hint?: string;
  tone: Tone;
}

function EvidenceTile({ icon: Icon, label, value, hint, tone }: EvidenceTileProps) {
  const palette = TONES[tone];
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 3,
        border: `1px solid ${palette.border}`,
        bgcolor: palette.bg,
        minHeight: 104,
        display: 'flex',
        flexDirection: 'column',
        gap: 0.6,
      }}
    >
      <Stack direction="row" spacing={0.7} alignItems="center">
        <Icon size={15} color={palette.text} />
        <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 700 }}>
          {label}
        </Typography>
      </Stack>
      <Typography
        sx={{
          fontWeight: 900,
          fontSize: '0.95rem',
          lineHeight: 1.45,
          color: palette.text,
          wordBreak: 'break-word',
        }}
      >
        {value}
      </Typography>
      {hint ? (
        <Typography variant="caption" sx={{ color: 'rgba(255,255,255,.5)', lineHeight: 1.5 }}>
          {hint}
        </Typography>
      ) : null}
    </Box>
  );
}

function percent(part: number, total: number): number {
  if (!total) return 0;
  return Math.min(100, Math.round((part / total) * 100));
}

function secondsLabel(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (value < 60) return `${Math.round(value)} ثانية`;
  const minutes = Math.floor(value / 60);
  const rest = Math.round(value % 60);
  return rest ? `${minutes} د ${rest} ث` : `${minutes} دقيقة`;
}

function countLabel(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : String(value);
}

export function ImpactEvidenceCard({ trackingUuid }: { trackingUuid?: string }) {
  const evidenceQuery = useQuery<TrackingEvidence>({
    queryKey: ['tracking-evidence', trackingUuid],
    queryFn: () => trackingApi.evidence(trackingUuid as string),
    enabled: Boolean(trackingUuid),
    staleTime: 30_000,
    retry: 1,
  });

  const evidence = evidenceQuery.data;
  if (!evidence?.found || !evidence.captured) return null;

  const captured = evidence.captured;
  const attacker = evidence.attacker_view;
  const impact = evidence.impact;

  const identifier =
    captured.identifier_masked ?? captured.email_masked ?? 'لم تُسجَّل قيمة';
  const passwordLine = captured.password_length
    ? `${captured.password_length} حرفًا · ${captured.password_strength ?? 'غير محددة'}`
    : 'لم تُكتب كلمة مرور';

  const deptRate = percent(
    impact?.department_submitted ?? 0,
    impact?.department_targeted ?? 0,
  );
  const orgRate = percent(impact?.org_submitted ?? 0, impact?.org_targeted ?? 0);

  return (
    <Box
      dir="rtl"
      sx={{
        mb: { xs: 3, md: 4 },
        p: { xs: 2, sm: 2.8 },
        borderRadius: 4,
        border: '1px solid rgba(255,23,68,.28)',
        background:
          'radial-gradient(circle at 0% 0%, rgba(255,23,68,.14), transparent 46%), linear-gradient(155deg, rgba(30,16,26,.92), rgba(11,14,24,.94))',
        boxShadow: '0 26px 70px rgba(0,0,0,.38)',
      }}
    >
      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'flex-start', sm: 'center' }}
        spacing={1.2}
        sx={{ mb: 2 }}
      >
        <Stack direction="row" spacing={1.1} alignItems="center">
          <Box
            sx={{
              width: 42,
              height: 42,
              borderRadius: 2.4,
              display: 'grid',
              placeItems: 'center',
              bgcolor: 'rgba(255,23,68,.12)',
              border: '1px solid rgba(255,23,68,.3)',
              color: '#FF6B81',
            }}
          >
            <Fingerprint size={21} />
          </Box>
          <Box>
            <Typography sx={{ fontWeight: 900, fontSize: { xs: '1.04rem', sm: '1.18rem' } }}>
              دليل الأثر الرقمي — ما حدث فعليًا
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              كل قيمة أدناه سُجِّلت من تفاعلك الحقيقي، وليست مثالًا توضيحيًا.
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={0.8} alignItems="center">
          {evidence.case_id ? (
            <Chip
              size="small"
              label={`رقم الحالة ${evidence.case_id}`}
              sx={{ fontWeight: 800, bgcolor: 'rgba(255,255,255,.06)' }}
            />
          ) : null}
          <Chip size="small" color="error" variant="outlined" label="محاكاة آمنة" sx={{ fontWeight: 800 }} />
        </Stack>
      </Stack>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0,1fr))', md: 'repeat(4, minmax(0,1fr))' },
          gap: 1.2,
          mb: 2,
        }}
      >
        <EvidenceTile
          icon={KeyRound}
          tone="danger"
          label="ما كتبته في الحقل"
          value={identifier}
          hint={passwordLine}
        />
        <EvidenceTile
          icon={Clock3}
          tone="warn"
          label="زمن الاستجابة"
          value={secondsLabel(captured.seconds_to_submit)}
          hint={`من النقر حتى التسليم · ${countLabel(captured.attempts)} محاولة`}
        />
        <EvidenceTile
          icon={Laptop}
          tone="info"
          label="الجهاز والمتصفح"
          value={attacker?.device ?? 'جهاز غير معروف'}
          hint={[attacker?.browser, attacker?.os].filter(Boolean).join(' · ') || 'لم يُحدَّد'}
        />
        <EvidenceTile
          icon={Globe2}
          tone="info"
          label="الشبكة التي ظهر منها الطلب"
          value={attacker?.ip_address ?? 'غير متاحة'}
          hint={attacker?.observed_at ? new Date(attacker.observed_at).toLocaleString('ar') : 'غير مسجّل'}
        />
      </Box>

      {captured.fields.length ? (
        <Box sx={{ mb: 2 }}>
          <Typography sx={{ fontWeight: 800, mb: 0.8, fontSize: '0.94rem' }}>
            الحقول التي التقطها المهاجم
          </Typography>
          <Stack direction="row" spacing={0.8} flexWrap="wrap" useFlexGap>
            {captured.fields.map((field) => (
              <Chip
                key={field}
                size="small"
                icon={<ShieldAlert size={13} />}
                label={field}
                sx={{
                  fontWeight: 800,
                  bgcolor: 'rgba(255,23,68,.1)',
                  border: '1px solid rgba(255,23,68,.26)',
                  color: '#FFB3BE',
                  '& .MuiChip-icon': { color: '#FF6B81' },
                }}
              />
            ))}
          </Stack>
          <Typography variant="caption" sx={{ display: 'block', mt: 0.9, color: 'rgba(255,255,255,.55)' }}>
            {captured.storage_note}
          </Typography>
        </Box>
      ) : null}

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0,1fr))' },
          gap: 1.2,
          mb: 2,
        }}
      >
        <Box
          sx={{
            p: 1.6,
            borderRadius: 3,
            border: '1px solid rgba(255,255,255,.08)',
            bgcolor: 'rgba(255,255,255,.025)',
          }}
        >
          <Stack direction="row" spacing={0.8} alignItems="center" sx={{ mb: 0.8 }}>
            <TrendingDown size={16} color="#FF6B81" />
            <Typography sx={{ fontWeight: 800, fontSize: '0.92rem' }}>أثر ذلك على تقييمك الأمني</Typography>
          </Stack>
          <Stack direction="row" spacing={1.6} alignItems="baseline" sx={{ mb: 0.6 }}>
            <Typography sx={{ fontSize: '1.5rem', fontWeight: 900, color: '#FF6B81' }}>
              {countLabel(impact?.elo_now)}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              من {countLabel(impact?.elo_before)} · الانخفاض {Math.abs(impact?.elo_delta ?? 0)} نقطة
            </Typography>
          </Stack>
          <LinearProgress
            variant="determinate"
            value={Math.max(2, Math.min(100, Math.round(((impact?.elo_now ?? 0) - 400) / 8)))}
            sx={{
              height: 7,
              borderRadius: 99,
              bgcolor: 'rgba(255,255,255,.08)',
              '& .MuiLinearProgress-bar': { bgcolor: '#FF4D6D', borderRadius: 99 },
            }}
          />
          <Typography variant="caption" sx={{ display: 'block', mt: 0.8, color: 'rgba(255,255,255,.55)' }}>
            تصنيف الخطورة الحالي: {impact?.threat_label ?? '—'}
          </Typography>
        </Box>

        <Box
          sx={{
            p: 1.6,
            borderRadius: 3,
            border: '1px solid rgba(255,255,255,.08)',
            bgcolor: 'rgba(255,255,255,.025)',
          }}
        >
          <Stack direction="row" spacing={0.8} alignItems="center" sx={{ mb: 0.8 }}>
            <Users size={16} color="#6FD3FF" />
            <Typography sx={{ fontWeight: 800, fontSize: '0.92rem' }}>أثر ذلك على مؤسستك</Typography>
          </Stack>
          <Typography sx={{ fontSize: '0.9rem', lineHeight: 1.9 }}>
            في قسمك: <b>{countLabel(impact?.department_submitted)}</b> من{' '}
            <b>{countLabel(impact?.department_targeted)}</b> موظفًا سلّموا بياناتهم ({deptRate}%).
          </Typography>
          <Typography sx={{ fontSize: '0.9rem', lineHeight: 1.9 }}>
            على مستوى المؤسسة: <b>{countLabel(impact?.org_submitted)}</b> من{' '}
            <b>{countLabel(impact?.org_targeted)}</b> ({orgRate}%).
          </Typography>
          <Typography variant="caption" sx={{ display: 'block', mt: 0.4, color: 'rgba(255,255,255,.55)' }}>
            كل حساب واحد يُخترق يُستخدم بعدها لتصيّد زملائه — هذا ما يجعل الأثر مؤسسيًا لا فرديًا.
          </Typography>
        </Box>
      </Box>

      {evidence.next_steps?.length ? (
        <Box>
          <Typography sx={{ fontWeight: 800, mb: 0.8, fontSize: '0.94rem' }}>
            ما كان المهاجم سيفعله بهذه البيانات
          </Typography>
          <Stack spacing={0.7}>
            {evidence.next_steps.map((step, index) => (
              <Stack key={step} direction="row" spacing={1} alignItems="flex-start">
                <Box
                  sx={{
                    minWidth: 22,
                    height: 22,
                    borderRadius: 99,
                    display: 'grid',
                    placeItems: 'center',
                    fontSize: '0.7rem',
                    fontWeight: 900,
                    bgcolor: 'rgba(255,23,68,.14)',
                    color: '#FFB3BE',
                    mt: '2px',
                  }}
                >
                  {index + 1}
                </Box>
                <Typography sx={{ fontSize: '0.88rem', lineHeight: 1.75, color: 'rgba(255,255,255,.82)' }}>
                  {step}
                </Typography>
              </Stack>
            ))}
          </Stack>
        </Box>
      ) : null}
    </Box>
  );
}
