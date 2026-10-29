/**
 * Public CEO-pretexting simulation (`/simulation/ceo/:trackingUuid`).
 *
 * A WhatsApp/Teams-style conversation with a spoofed CEO auto-plays the two
 * social-engineering messages.  The recipient can either:
 *
 *  - buy the cards and send the codes -> `financial_fraud` (-30 Elo)
 *  - refuse and report to security   -> `reported_phish` (+20 Elo)
 *
 * No real money, gift-card code or message leaves the browser.  The tracking
 * UUID is the only credential the page needs.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { motion } from 'framer-motion';
import {
  BadgeCheck,
  Building2,
  CheckCheck,
  Flag,
  Gift,
  MessageSquareWarning,
  Phone,
  ShieldCheck,
  Video,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { trackingApi } from '@/api/endpoints';
import type { SimulationChoiceResponse } from '@/types';

const DEFAULT_MESSAGES = [
  'مرحباً، أنا في اجتماع مهم ولا أستطيع التحدث.',
  'أحتاج منك شراء 3 بطاقات جوجل بلاي (100$) وإرسال الأكواد هنا فوراً. سأعوضك لاحقاً.',
];
const DEFAULT_SENDER = 'محمد العتيبي';

export function PretextingSimulationPage() {
  const { trackingUuid = '' } = useParams<{ trackingUuid: string }>();
  const navigate = useNavigate();
  const [visibleCount, setVisibleCount] = useState(0);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState<'financial_fraud' | 'reported_phish' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<SimulationChoiceResponse | null>(null);
  const visitLogged = useRef(false);

  const contextQuery = useQuery({
    queryKey: ['pretexting-context', trackingUuid],
    queryFn: () => trackingApi.context(trackingUuid),
    enabled: Boolean(trackingUuid),
    retry: false,
  });
  const context = contextQuery.data;
  const messages = useMemo(() => {
    const custom = context?.channel_config?.pretexting?.message?.trim();
    return custom ? [DEFAULT_MESSAGES[0], custom] : DEFAULT_MESSAGES;
  }, [context?.channel_config?.pretexting?.message]);
  const sender = context?.channel_config?.pretexting?.sender_name?.trim() || DEFAULT_SENDER;
  const primary = context?.brand_primary_color || '#25D366';

  useEffect(() => {
    if (!trackingUuid || visitLogged.current) return;
    visitLogged.current = true;
    void trackingApi.visit(trackingUuid, 'pretexting').catch(() => undefined);
  }, [trackingUuid]);

  useEffect(() => {
    setVisibleCount(0);
    const timers = [
      window.setTimeout(() => setVisibleCount((count) => Math.max(count, 1)), 550),
      window.setTimeout(() => setVisibleCount((count) => Math.max(count, 2)), 1900),
    ];
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [messages]);

  const choose = async (choice: 'financial_fraud' | 'reported_phish') => {
    if (!trackingUuid || busy) return;
    setBusy(choice);
    setError(null);
    if (choice === 'financial_fraud') setSent(true);
    try {
      const response = await trackingApi.pretextingChoice(trackingUuid, choice);
      setOutcome(response);
      window.setTimeout(
        () => navigate(`/training/${trackingUuid}?channel=pretexting`),
        1100,
      );
    } catch {
      setError('تعذّر تسجيل النتيجة. تحقق من الرابط أو أعد المحاولة.');
      setBusy(null);
      setSent(false);
    }
  };

  if (!trackingUuid) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 3 }}>
        <Alert severity="error">رابط المحاكاة غير صالح.</Alert>
      </Box>
    );
  }

  const actionsVisible = visibleCount >= messages.length || sent || Boolean(outcome);
  const locked = Boolean(busy) || Boolean(outcome);

  return (
    <Box
      dir="rtl"
      sx={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        p: { xs: 1.5, sm: 3 },
        background:
          'radial-gradient(circle at 16% 12%, rgba(37,211,102,.09), transparent 36%), radial-gradient(circle at 84% 88%, rgba(0,240,255,.08), transparent 34%), #050A14',
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45 }}
        style={{ width: '100%', maxWidth: 500 }}
      >
        <Box
          sx={{
            overflow: 'hidden',
            borderRadius: { xs: 4, sm: 5 },
            border: '1px solid rgba(255,255,255,.12)',
            bgcolor: '#0B141A',
            boxShadow: '0 40px 120px rgba(0,0,0,.65)',
          }}
        >
          <Box
            sx={{
              px: 1.6,
              py: 1.2,
              bgcolor: '#111F2B',
              borderBottom: '1px solid rgba(255,255,255,.08)',
            }}
          >
            <Stack direction="row" spacing={1.1} alignItems="center">
              <Box
                sx={{
                  width: 42,
                  height: 42,
                  borderRadius: '50%',
                  display: 'grid',
                  placeItems: 'center',
                  bgcolor: 'rgba(255,255,255,.08)',
                  border: '1px solid rgba(255,255,255,.12)',
                  flex: '0 0 auto',
                }}
              >
                <Building2 size={20} color={primary} />
              </Box>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography sx={{ fontWeight: 800, fontSize: '0.86rem', color: '#F8FAFC' }}>
                  {sender}
                </Typography>
                <Typography sx={{ color: '#25D366', fontSize: '0.64rem' }}>
                  متصل الآن · الرئيس التنفيذي
                </Typography>
              </Box>
              <Video size={18} color="#8B9BB4" />
              <Phone size={17} color="#8B9BB4" />
            </Stack>
          </Box>

          <Box
            sx={{
              p: 2,
              minHeight: 330,
              backgroundImage:
                'radial-gradient(circle at 18% 24%, rgba(37,211,102,.035), transparent 30%), radial-gradient(circle at 82% 76%, rgba(0,240,255,.035), transparent 34%)',
            }}
          >
            <Stack alignItems="center" sx={{ mb: 1.6 }}>
              <Chip
                size="small"
                label="اليوم"
                sx={{
                  bgcolor: 'rgba(255,255,255,.05)',
                  color: 'rgba(255,255,255,.5)',
                  fontSize: '0.6rem',
                }}
              />
            </Stack>

            {messages.slice(0, visibleCount).map((text, index) => (
              <motion.div
                key={`${index}-${text.slice(0, 12)}`}
                initial={{ opacity: 0, x: 14 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.35 }}
              >
                <Box sx={{ mb: 1.4, display: 'flex', justifyContent: 'flex-start' }}>
                  <Box
                    sx={{
                      maxWidth: '90%',
                      p: 1.35,
                      borderRadius: '4px 16px 16px 16px',
                      bgcolor: '#1F2C34',
                      border: '1px solid rgba(255,255,255,.05)',
                    }}
                  >
                    <Typography sx={{ fontSize: '0.82rem', lineHeight: 2, color: '#F8FAFC' }}>
                      {text}
                    </Typography>
                    <Stack
                      direction="row"
                      spacing={0.5}
                      justifyContent="flex-end"
                      alignItems="center"
                      sx={{ mt: 0.6 }}
                    >
                      <Typography sx={{ fontSize: '0.56rem', color: 'rgba(255,255,255,.4)' }}>
                        {index === 0 ? '09:41' : '09:42'}
                      </Typography>
                      <CheckCheck size={13} color="#53BDEB" />
                    </Stack>
                  </Box>
                </Box>
              </motion.div>
            ))}

            {visibleCount >= 2 ? (
              <motion.div initial={{ opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }}>
                <Box sx={{ mb: 1.4, display: 'flex', justifyContent: 'flex-start' }}>
                  <Box
                    sx={{
                      maxWidth: '88%',
                      p: 1.2,
                      borderRadius: '4px 14px 14px 14px',
                      bgcolor: 'rgba(255,193,7,.07)',
                      border: '1px dashed rgba(255,193,7,.25)',
                    }}
                  >
                    <Stack direction="row" spacing={0.8} alignItems="center">
                      <Gift size={15} color="#FFC857" />
                      <Typography sx={{ fontSize: '0.7rem', color: '#FFC857', fontWeight: 700 }}>
                        طلب شراء 3 بطاقات جوجل بلاي × 100$ — إجمالي 300$
                      </Typography>
                    </Stack>
                  </Box>
                </Box>
              </motion.div>
            ) : (
              <Stack direction="row" spacing={0.5} alignItems="center" sx={{ mt: 1, width: 58, p: 1 }}>
                {[0, 1, 2].map((dot) => (
                  <Box
                    key={dot}
                    sx={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      bgcolor: 'rgba(255,255,255,.4)',
                      animation: 'mcPulse 1.2s ease-in-out infinite',
                      animationDelay: `${dot * 0.16}s`,
                    }}
                  />
                ))}
              </Stack>
            )}

            {sent ? (
              <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                <Box sx={{ mt: 2, display: 'flex', justifyContent: 'flex-end' }}>
                  <Box
                    sx={{
                      maxWidth: '82%',
                      p: 1.2,
                      borderRadius: '16px 4px 16px 16px',
                      bgcolor: 'rgba(0,92,75,.58)',
                      border: '1px solid rgba(37,211,102,.18)',
                    }}
                  >
                    <Typography
                      sx={{ fontSize: '0.76rem', color: 'rgba(255,255,255,.88)', lineHeight: 1.8 }}
                    >
                      تم الشراء. أكواد البطاقات: GPLAY-••••-••••، GPLAY-••••-••••، GPLAY-••••-••••
                    </Typography>
                    <Typography
                      sx={{
                        fontSize: '0.56rem',
                        color: 'rgba(255,255,255,.4)',
                        textAlign: 'left',
                        mt: 0.4,
                      }}
                    >
                      09:43 ✓✓
                    </Typography>
                  </Box>
                </Box>
              </motion.div>
            ) : null}

            {outcome ? (
              <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                <Alert
                  severity={outcome.choice === 'reported_phish' ? 'success' : 'warning'}
                  icon={
                    outcome.choice === 'reported_phish' ? (
                      <BadgeCheck size={18} />
                    ) : (
                      <MessageSquareWarning size={18} />
                    )
                  }
                  sx={{ mt: 2, textAlign: 'right', fontSize: '0.74rem' }}
                >
                  {outcome.message} جارٍ نقلك إلى التدريب…
                </Alert>
              </motion.div>
            ) : null}
          </Box>

          <Box
            sx={{
              px: 1.4,
              py: 1.2,
              bgcolor: '#111F2B',
              borderTop: '1px solid rgba(255,255,255,.08)',
            }}
          >
            {actionsVisible ? (
              <Stack spacing={1}>
                <Button
                  fullWidth
                  variant="contained"
                  color="error"
                  size="large"
                  disabled={locked}
                  onClick={() => void choose('financial_fraud')}
                  startIcon={
                    busy === 'financial_fraud' ? (
                      <CircularProgress size={16} color="inherit" />
                    ) : (
                      <Gift size={18} />
                    )
                  }
                  sx={{ py: 1.15, fontWeight: 900 }}
                >
                  {busy === 'financial_fraud'
                    ? 'جارٍ إرسال الأكواد…'
                    : 'شراء البطاقات وإرسال الأكواد'}
                </Button>
                <Button
                  fullWidth
                  variant="outlined"
                  color="success"
                  size="large"
                  disabled={locked}
                  onClick={() => void choose('reported_phish')}
                  startIcon={
                    busy === 'reported_phish' ? (
                      <CircularProgress size={16} color="inherit" />
                    ) : (
                      <Flag size={18} />
                    )
                  }
                  sx={{ py: 1.15, fontWeight: 800 }}
                >
                  {busy === 'reported_phish' ? 'جارٍ تسجيل البلاغ…' : 'رفض وإبلاغ الأمن'}
                </Button>
              </Stack>
            ) : (
              <Typography sx={{ color: 'rgba(255,255,255,.36)', fontSize: '0.68rem', textAlign: 'center' }}>
                تظهر خيارات الرد بعد اكتمال الرسائل…
              </Typography>
            )}
          </Box>

          <Box sx={{ px: 2, py: 1.2, textAlign: 'center', bgcolor: '#0B141A' }}>
            <Stack direction="row" spacing={0.7} justifyContent="center" alignItems="center">
              <ShieldCheck size={13} color="#8B9BB4" />
              <Typography sx={{ color: 'rgba(255,255,255,.34)', fontSize: '0.61rem', lineHeight: 1.6 }}>
                محاكاة تدريبية مصرّح بها — لا ترسل أموالاً أو أكواداً حقيقية.
              </Typography>
            </Stack>
          </Box>
        </Box>

        {error ? (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        ) : null}
      </motion.div>
    </Box>
  );
}

export default PretextingSimulationPage;
