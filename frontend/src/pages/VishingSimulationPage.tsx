/**
 * Public vishing simulation (`/simulation/vishing/:trackingUuid`).
 *
 * The page intentionally looks like a mobile incoming call.  It plays the
 * Arabic social-engineering script with the browser Speech Synthesis API and
 * records exactly one outcome:
 *
 *  - reading the one-time code back to the caller -> `credential_disclosed`
 *  - hanging up and calling the real support desk -> `reported_phish`
 *
 * The page never asks for or transmits a real code.  It is a training artefact
 * and the tracking UUID is the only credential it needs.
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
  CheckCircle2,
  KeyRound,
  Mic,
  Phone,
  PhoneCall,
  PhoneOff,
  ShieldCheck,
  Volume2,
  VolumeX,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { trackingApi } from '@/api/endpoints';
import type { SimulationChoiceResponse } from '@/types';

const DEFAULT_SCRIPT =
  'مرحباً، أنا أحمد من الدعم الفني. لقد لاحظنا اختراقاً في حسابك. هل يمكنك إعطائي الرمز الذي وصلك في رسالة نصية؟';
const FAKE_CODE = '482 913';

function pickArabicVoice(): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  return (
    voices.find((voice) => voice.lang.toLowerCase().startsWith('ar')) ??
    voices.find((voice) => /arab/i.test(voice.name)) ??
    null
  );
}

export function VishingSimulationPage() {
  const { trackingUuid = '' } = useParams<{ trackingUuid: string }>();
  const navigate = useNavigate();
  const [answered, setAnswered] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [busy, setBusy] = useState<'credential_disclosed' | 'reported_phish' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<SimulationChoiceResponse | null>(null);
  const visitLogged = useRef(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  const contextQuery = useQuery({
    queryKey: ['vishing-context', trackingUuid],
    queryFn: () => trackingApi.context(trackingUuid),
    enabled: Boolean(trackingUuid),
    retry: false,
  });
  const context = contextQuery.data;
  const script = useMemo(
    () => context?.channel_config?.vishing?.script?.trim() || DEFAULT_SCRIPT,
    [context?.channel_config?.vishing?.script],
  );
  const caller =
    context?.channel_config?.vishing?.caller_name?.trim() || 'أحمد — الدعم الفني';
  const primary = context?.brand_primary_color || '#00F0FF';

  useEffect(() => {
    if (!trackingUuid || visitLogged.current) return;
    visitLogged.current = true;
    void trackingApi.visit(trackingUuid, 'vishing').catch(() => undefined);
  }, [trackingUuid]);

  const stopSpeaking = useCallback(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setSpeaking(false);
  }, []);

  useEffect(() => stopSpeaking, [stopSpeaking]);

  const speak = useCallback(() => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      setError('متصفحك لا يدعم قراءة النص صوتياً. يمكنك قراءة السيناريو أدناه.');
      return;
    }
    stopSpeaking();
    const utterance = new SpeechSynthesisUtterance(script);
    utterance.lang = 'ar-SA';
    utterance.rate = 0.92;
    utterance.pitch = 0.9;
    const voice = pickArabicVoice();
    if (voice) utterance.voice = voice;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    utteranceRef.current = utterance;
    setSpeaking(true);
    window.speechSynthesis.speak(utterance);
  }, [script, stopSpeaking]);

  const choose = async (choice: 'credential_disclosed' | 'reported_phish') => {
    if (!trackingUuid || busy) return;
    setBusy(choice);
    setError(null);
    stopSpeaking();
    try {
      const response = await trackingApi.vishingChoice(trackingUuid, choice);
      setOutcome(response);
      // A short beat lets the recipient see the outcome before the training
      // page explains what the attacker would have gained.
      window.setTimeout(() => navigate(`/training/${trackingUuid}?channel=vishing`), 900);
    } catch {
      setError('تعذّر تسجيل النتيجة. تحقق من الرابط أو أعد المحاولة.');
      setBusy(null);
    }
  };

  if (!trackingUuid) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 3 }}>
        <Alert severity="error">رابط المحاكاة غير صالح.</Alert>
      </Box>
    );
  }

  return (
    <Box
      dir="rtl"
      sx={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        p: { xs: 1.5, sm: 3 },
        color: '#F8FAFC',
        background:
          'radial-gradient(circle at 20% 10%, rgba(0,240,255,.12), transparent 38%), radial-gradient(circle at 80% 90%, rgba(179,136,255,.10), transparent 36%), #050A14',
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 18, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45 }}
        style={{ width: '100%', maxWidth: 430 }}
      >
        <Box
          sx={{
            position: 'relative',
            overflow: 'hidden',
            borderRadius: { xs: 5, sm: 6 },
            border: '1px solid rgba(255,255,255,.12)',
            bgcolor: '#07101C',
            boxShadow: '0 40px 120px rgba(0,0,0,.65), 0 0 0 1px rgba(0,240,255,.06)',
          }}
        >
          {/* phone status bar */}
          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="center"
            sx={{ px: 2.2, pt: 1.6, color: 'rgba(255,255,255,.62)', fontSize: '0.68rem' }}
          >
            <span className="mc-mono">9:41</span>
            <Stack direction="row" spacing={0.7} alignItems="center">
              <span className="mc-mono">5G</span>
              <Box sx={{ width: 22, height: 10, borderRadius: 0.6, border: '1px solid rgba(255,255,255,.45)', p: '1px' }}>
                <Box sx={{ width: '72%', height: '100%', borderRadius: 0.3, bgcolor: '#00E676' }} />
              </Box>
            </Stack>
          </Stack>

          <Box sx={{ px: 2.4, pt: 4, pb: 3, textAlign: 'center' }}>
            <Typography sx={{ color: 'rgba(255,255,255,.55)', fontSize: '0.72rem', letterSpacing: '.08em' }}>
              {answered ? 'مكالمة جارية' : 'مكالمة واردة'}
            </Typography>
            <Box
              sx={{
                width: 104,
                height: 104,
                mx: 'auto',
                mt: 2.4,
                borderRadius: '50%',
                display: 'grid',
                placeItems: 'center',
                bgcolor: 'rgba(255,255,255,.05)',
                border: `1px solid ${primary}55`,
                boxShadow: `0 0 55px ${primary}33`,
                position: 'relative',
              }}
            >
              {!answered ? (
                <Box className="mc-ring" sx={{ position: 'absolute', inset: -10, borderRadius: '50%', border: `1px solid ${primary}44` }} />
              ) : null}
              <PhoneCall size={46} color={primary} />
            </Box>
            <Typography sx={{ fontSize: '1.45rem', fontWeight: 900, mt: 2 }}>{caller}</Typography>
            <Typography sx={{ color: 'rgba(255,255,255,.5)', fontFamily: 'monospace', fontSize: '0.8rem', mt: 0.4 }} dir="ltr">
              +966 11 000 0000
            </Typography>
            <Chip
              size="small"
              label="رقم غير معروف"
              sx={{ mt: 1.2, bgcolor: 'rgba(255,23,68,.12)', color: '#FF8A9A', border: '1px solid rgba(255,23,68,.3)' }}
            />

            {!answered ? (
              <Stack direction="row" spacing={2} justifyContent="center" sx={{ mt: 5 }}>
                <Stack alignItems="center" spacing={0.8}>
                  <Box
                    component="button"
                    type="button"
                    aria-label="رفض المكالمة والإبلاغ"
                    disabled={Boolean(busy) || Boolean(outcome)}
                    onClick={() => void choose('reported_phish')}
                    sx={{
                      width: 62,
                      height: 62,
                      borderRadius: '50%',
                      border: '1px solid rgba(255,23,68,.35)',
                      bgcolor: 'rgba(255,23,68,.16)',
                      color: '#FF6B81',
                      display: 'grid',
                      placeItems: 'center',
                      cursor: 'pointer',
                    }}
                  >
                    <PhoneOff size={26} />
                  </Box>
                  <Typography sx={{ fontSize: '0.68rem', color: 'rgba(255,255,255,.55)' }}>رفض</Typography>
                </Stack>
                <Stack alignItems="center" spacing={0.8}>
                  <Box
                    component="button"
                    type="button"
                    aria-label="الرد على المكالمة"
                    onClick={() => {
                      setAnswered(true);
                      speak();
                    }}
                    sx={{
                      width: 62,
                      height: 62,
                      borderRadius: '50%',
                      border: '1px solid rgba(0,230,118,.4)',
                      bgcolor: 'rgba(0,230,118,.18)',
                      color: '#00E676',
                      display: 'grid',
                      placeItems: 'center',
                      cursor: 'pointer',
                      boxShadow: '0 0 30px rgba(0,230,118,.22)',
                    }}
                  >
                    <Phone size={26} />
                  </Box>
                  <Typography sx={{ fontSize: '0.68rem', color: 'rgba(255,255,255,.55)' }}>رد</Typography>
                </Stack>
              </Stack>
            ) : (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                <Box
                  sx={{
                    mt: 3,
                    p: 1.6,
                    borderRadius: 3,
                    textAlign: 'right',
                    bgcolor: 'rgba(255,255,255,.04)',
                    border: '1px solid rgba(255,255,255,.09)',
                  }}
                >
                  <Stack direction="row" spacing={0.8} alignItems="center" sx={{ mb: 0.8 }}>
                    <Mic size={15} color={primary} />
                    <Typography sx={{ fontSize: '0.7rem', color: 'rgba(255,255,255,.55)', fontWeight: 700 }}>
                      النص المسموع
                    </Typography>
                    <Box sx={{ flex: 1 }} />
                    <Button
                      size="small"
                      variant="text"
                      onClick={speaking ? stopSpeaking : speak}
                      startIcon={speaking ? <VolumeX size={14} /> : <Volume2 size={14} />}
                      sx={{ minWidth: 0, fontSize: '0.66rem' }}
                    >
                      {speaking ? 'إيقاف' : 'إعادة'}
                    </Button>
                  </Stack>
                  <Typography sx={{ fontSize: '0.84rem', lineHeight: 1.95 }}>{script}</Typography>
                </Box>

                <Box
                  sx={{
                    mt: 2,
                    p: 1.6,
                    borderRadius: 3,
                    bgcolor: 'rgba(255,193,7,.06)',
                    border: '1px solid rgba(255,193,7,.22)',
                    textAlign: 'right',
                  }}
                >
                  <Stack direction="row" spacing={0.8} alignItems="center" sx={{ mb: 0.8 }}>
                    <KeyRound size={15} color="#FFC857" />
                    <Typography sx={{ fontSize: '0.7rem', color: '#FFC857', fontWeight: 800 }}>
                      رمز تحقق وهمي ظهر على شاشتك
                    </Typography>
                  </Stack>
                  <Typography className="mc-mono" sx={{ fontSize: '1.55rem', letterSpacing: '.18em', fontWeight: 900, direction: 'ltr', textAlign: 'center' }}>
                    {FAKE_CODE}
                  </Typography>
                  <Typography sx={{ fontSize: '0.62rem', color: 'rgba(255,255,255,.42)', textAlign: 'center', mt: 0.5 }}>
                    هذا الرمز جزء من المحاكاة فقط — لا يوجد رمز حقيقي.
                  </Typography>
                </Box>

                <Stack spacing={1.1} sx={{ mt: 2.5 }}>
                  <Button
                    fullWidth
                    variant="contained"
                    color="error"
                    size="large"
                    disabled={Boolean(busy) || Boolean(outcome)}
                    onClick={() => void choose('credential_disclosed')}
                    startIcon={busy === 'credential_disclosed' ? <CircularProgress size={16} color="inherit" /> : <KeyRound size={18} />}
                    sx={{ py: 1.3, fontWeight: 900 }}
                  >
                    {busy === 'credential_disclosed' ? 'جارٍ قراءة الكود…' : 'إعطاء الرمز'}
                  </Button>
                  <Button
                    fullWidth
                    variant="outlined"
                    color="success"
                    size="large"
                    disabled={Boolean(busy) || Boolean(outcome)}
                    onClick={() => void choose('reported_phish')}
                    startIcon={busy === 'reported_phish' ? <CircularProgress size={16} color="inherit" /> : <ShieldCheck size={18} />}
                    sx={{ py: 1.3, fontWeight: 800 }}
                  >
                    {busy === 'reported_phish' ? 'جارٍ تسجيل البلاغ…' : 'إغلاق المكالمة والإبلاغ'}
                  </Button>
                </Stack>
              </motion.div>
            )}

            {error ? (
              <Alert severity="error" sx={{ mt: 2, textAlign: 'right' }}>
                {error}
              </Alert>
            ) : null}
            {outcome ? (
              <Alert
                severity={outcome.choice === 'reported_phish' ? 'success' : 'warning'}
                icon={outcome.choice === 'reported_phish' ? <CheckCircle2 size={18} /> : undefined}
                sx={{ mt: 2, textAlign: 'right' }}
              >
                {outcome.message} جارٍ نقلك إلى التدريب…
              </Alert>
            ) : null}
          </Box>

          <Box sx={{ px: 2.2, pb: 2, textAlign: 'center' }}>
            <Typography sx={{ color: 'rgba(255,255,255,.32)', fontSize: '0.6rem', lineHeight: 1.7 }}>
              محاكاة تدريبية مصرّح بها من {context?.company_name ?? 'مؤسستك'} — لا تشارك رموز التحقق مع أي شخص.
            </Typography>
          </Box>
        </Box>
      </motion.div>
    </Box>
  );
}

export default VishingSimulationPage;
