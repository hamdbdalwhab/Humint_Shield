/**
 * Public quishing simulation (`/simulation/qr/:trackingUuid`).
 *
 * A realistic mobile captive-portal sign-in page reached by scanning the
 * printed QR poster.  The page:
 *
 *  1. writes `qr_scanned` through the neutral visit endpoint,
 *  2. collects an identifier and a password-looking value for realism,
 *  3. sends **only** the identifier, password length and non-secret metadata to
 *     `POST /api/v1/track/submit/{uuid}` with `capture_secret: false`,
 *  4. lets the backend apply the once-only -25 quishing penalty,
 *  5. redirects to the attack-chain reveal and then micro-training.
 *
 * The typed password is never placed in the request payload, never logged and
 * never persisted.  The tracking UUID is the only credential needed.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { motion } from 'framer-motion';
import {
  BatteryFull,
  Building2,
  Eye,
  EyeOff,
  HeartPulse,
  LockKeyhole,
  ShieldCheck,
  Signal,
  Wifi,
} from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { trackingApi } from '@/api/endpoints';

const NETWORK_NAME = 'Company-WiFi-5G';

export function QrSimulationPage() {
  const { trackingUuid = '' } = useParams<{ trackingUuid: string }>();
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const startedAt = useRef<number>(0);
  const visitLogged = useRef(false);

  const contextQuery = useQuery({
    queryKey: ['qr-context', trackingUuid],
    queryFn: () => trackingApi.context(trackingUuid),
    enabled: Boolean(trackingUuid),
    retry: false,
  });
  const context = contextQuery.data;
  const primary = context?.brand_primary_color || '#22D3EE';
  const company = context?.company_name?.trim() || 'بوابة الشركة';
  const firstName = context?.first_name?.trim();

  useEffect(() => {
    if (!trackingUuid || visitLogged.current) return;
    visitLogged.current = true;
    void trackingApi.visit(trackingUuid, 'qr').catch(() => undefined);
  }, [trackingUuid]);

  useEffect(() => {
    if (!context?.email) return;
    setIdentifier((current) => current || context.email || '');
  }, [context?.email]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (!trackingUuid) {
      setError('رابط المحاكاة غير صالح.');
      return;
    }
    if (!identifier.trim()) {
      setError('أدخل البريد المؤسسي أو اسم المستخدم.');
      return;
    }
    if (!password) {
      setError('أدخل كلمة مرور الشبكة.');
      return;
    }
    setBusy(true);
    setError(null);
    startedAt.current = startedAt.current || performance.now();
    try {
      // A short network-style delay makes the portal feel like a real SSO
      // handshake.  The password itself is intentionally absent from the
      // payload: only its length is sent for behavioural evidence.
      await new Promise((resolve) => window.setTimeout(resolve, 950));
      const response = await trackingApi.submit(trackingUuid, {
        identifier: identifier.trim(),
        password_length: password.length,
        fields: {
          portal: 'company-wifi',
          network: NETWORK_NAME,
          service: 'wifi-and-health-insurance',
        },
        client: {
          submit_delay_ms: Math.round(performance.now() - startedAt.current),
          screen: `${window.screen.width}x${window.screen.height}`,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          language: navigator.language,
        },
        capture_secret: false,
      });
      setPassword('');
      if (!response.success) {
        setError('تعذّر إكمال الاتصال. تحقق من بيانات الدخول أو أعد المحاولة.');
        setBusy(false);
        return;
      }
      navigate(`/hacked/${trackingUuid}?channel=qr`);
    } catch {
      setError('تعذّر الاتصال بالشبكة. تحقق من الرابط أو أعد المحاولة.');
      setBusy(false);
    }
  };

  if (!trackingUuid) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 3 }}>
        <Alert severity="error">رابط المحاكاة غير صالح.</Alert>
      </Box>
    );
  }

  if (contextQuery.isLoading) {
    return (
      <Box
        dir="rtl"
        sx={{
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          bgcolor: '#050A14',
          color: '#F8FAFC',
        }}
      >
        <Stack alignItems="center" spacing={2}>
          <CircularProgress size={30} sx={{ color: primary }} />
          <Typography sx={{ color: 'rgba(255,255,255,.55)', fontSize: '0.82rem' }}>
            جارٍ الاتصال بالبوابة الآمنة…
          </Typography>
        </Stack>
      </Box>
    );
  }

  if (context && context.found === false) {
    return (
      <Box dir="rtl" sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 3, bgcolor: '#050A14' }}>
        <Alert severity="error">رابط المحاكاة غير صالح أو منتهي.</Alert>
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
        p: { xs: 1, sm: 3 },
        background:
          'radial-gradient(circle at 14% 12%, rgba(34,211,238,.13), transparent 34%), radial-gradient(circle at 86% 88%, rgba(167,139,250,.10), transparent 34%), #040810',
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.45 }}
        style={{ width: '100%', maxWidth: 430 }}
      >
        <Box
          sx={{
            position: 'relative',
            borderRadius: '46px',
            p: '9px',
            bgcolor: '#101722',
            border: '1px solid rgba(255,255,255,.14)',
            boxShadow: '0 50px 140px rgba(0,0,0,.78), 0 0 0 1px rgba(34,211,238,.06)',
          }}
        >
          <Box
            sx={{
              position: 'relative',
              overflow: 'hidden',
              borderRadius: '38px',
              bgcolor: '#07101C',
              minHeight: { xs: 720, sm: 780 },
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {/* Status bar + notch */}
            <Box
              sx={{
                position: 'relative',
                zIndex: 2,
                px: 2.4,
                pt: 1.3,
                pb: 0.6,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                color: 'rgba(255,255,255,.74)',
                fontSize: '0.68rem',
              }}
            >
              <span className="mc-mono">9:41</span>
              <Box
                sx={{
                  position: 'absolute',
                  left: '50%',
                  top: 8,
                  transform: 'translateX(-50%)',
                  width: 104,
                  height: 24,
                  borderRadius: 99,
                  bgcolor: '#000',
                }}
              />
              <Stack direction="row" spacing={0.7} alignItems="center">
                <Signal size={13} />
                <Wifi size={14} />
                <BatteryFull size={17} />
              </Stack>
            </Box>

            <Box sx={{ px: 2.4, pt: 1.2, pb: 2.2, flex: 1 }}>
              <Stack direction="row" alignItems="center" justifyContent="space-between">
                <Stack direction="row" spacing={1.1} alignItems="center">
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '13px',
                      display: 'grid',
                      placeItems: 'center',
                      color: '#04121C',
                      background: `linear-gradient(135deg, ${primary}, #A78BFA)`,
                      boxShadow: `0 12px 30px ${primary}33`,
                    }}
                  >
                    <Building2 size={21} />
                  </Box>
                  <Box>
                    <Typography sx={{ fontWeight: 900, fontSize: '0.84rem', color: '#F8FAFC' }}>
                      {company}
                    </Typography>
                    <Typography sx={{ fontSize: '0.62rem', color: 'rgba(255,255,255,.45)' }}>
                      بوابة الشبكة والخدمات
                    </Typography>
                  </Box>
                </Stack>
                <Chip
                  size="small"
                  icon={<LockKeyhole size={12} color="#22D3EE" />}
                  label="اتصال مشفّر"
                  sx={{
                    bgcolor: 'rgba(34,211,238,.08)',
                    color: '#A5F3FC',
                    border: '1px solid rgba(34,211,238,.22)',
                    fontSize: '0.6rem',
                    '& .MuiChip-icon': { ml: 0.6 },
                  }}
                />
              </Stack>

              <Box
                sx={{
                  mt: 3.2,
                  width: 92,
                  height: 92,
                  mx: 'auto',
                  borderRadius: '50%',
                  display: 'grid',
                  placeItems: 'center',
                  position: 'relative',
                  border: `1px solid ${primary}44`,
                  background: `radial-gradient(circle at 40% 30%, ${primary}2E, rgba(255,255,255,.02))`,
                  boxShadow: `0 0 60px ${primary}22`,
                }}
              >
                <Box
                  className="mc-ring"
                  sx={{
                    position: 'absolute',
                    inset: -13,
                    borderRadius: '50%',
                    border: `1px solid ${primary}33`,
                  }}
                />
                <Wifi size={42} color={primary} />
                <Box
                  sx={{
                    position: 'absolute',
                    right: 2,
                    bottom: 4,
                    width: 26,
                    height: 26,
                    borderRadius: '50%',
                    bgcolor: '#00E676',
                    border: '3px solid #07101C',
                    display: 'grid',
                    placeItems: 'center',
                  }}
                >
                  <ShieldCheck size={13} color="#04121C" />
                </Box>
              </Box>

              <Typography
                sx={{
                  mt: 2.4,
                  textAlign: 'center',
                  fontSize: '1.32rem',
                  fontWeight: 900,
                  color: '#F8FAFC',
                  letterSpacing: '-0.01em',
                }}
              >
                اتصال آمن بالشبكة
              </Typography>
              <Typography
                sx={{
                  mt: 0.8,
                  textAlign: 'center',
                  fontSize: '0.76rem',
                  lineHeight: 1.9,
                  color: 'rgba(255,255,255,.52)',
                  px: 1.5,
                }}
              >
                {firstName ? `${firstName}، سجّل الدخول` : 'سجّل الدخول'} لتفعيل الإنترنت وتحديث
                بيانات التأمين الصحي في خطوة واحدة.
              </Typography>

              <Box
                sx={{
                  mt: 2.2,
                  p: 1.35,
                  borderRadius: 3,
                  bgcolor: 'rgba(255,255,255,.035)',
                  border: '1px solid rgba(255,255,255,.08)',
                }}
              >
                <Stack direction="row" alignItems="center" spacing={1.1}>
                  <Box
                    sx={{
                      width: 34,
                      height: 34,
                      borderRadius: 2,
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: 'rgba(34,211,238,.08)',
                      color: primary,
                    }}
                  >
                    <Wifi size={17} />
                  </Box>
                  <Box sx={{ flex: 1 }}>
                    <Typography sx={{ fontSize: '0.76rem', fontWeight: 800, color: '#F8FAFC' }}>
                      {NETWORK_NAME}
                    </Typography>
                    <Typography sx={{ fontSize: '0.6rem', color: 'rgba(255,255,255,.42)' }}>
                      إشارة قوية · WPA3 Enterprise · الضيوف
                    </Typography>
                  </Box>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#00E676', boxShadow: '0 0 10px #00E676' }} />
                </Stack>
              </Box>

              <Box component="form" onSubmit={(event) => void handleSubmit(event)} sx={{ mt: 2 }}>
                <Stack spacing={1.6}>
                  <TextField
                    fullWidth
                    size="small"
                    label="البريد المؤسسي أو اسم المستخدم"
                    value={identifier}
                    onChange={(event) => setIdentifier(event.target.value)}
                    autoComplete="username"
                    inputProps={{ dir: 'ltr', style: { textAlign: 'left' } }}
                    InputLabelProps={{ shrink: true }}
                  />
                  <TextField
                    fullWidth
                    size="small"
                    label="كلمة مرور الشبكة"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="current-password"
                    inputProps={{ dir: 'ltr', style: { textAlign: 'left' } }}
                    InputLabelProps={{ shrink: true }}
                    InputProps={{
                      endAdornment: (
                        <InputAdornment position="end">
                          <IconButton
                            type="button"
                            size="small"
                            aria-label={showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
                            onClick={() => setShowPassword((value) => !value)}
                            edge="end"
                          >
                            {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                          </IconButton>
                        </InputAdornment>
                      ),
                    }}
                  />
                  <Button
                    fullWidth
                    type="submit"
                    variant="contained"
                    size="large"
                    disabled={busy}
                    startIcon={
                      busy ? <CircularProgress size={17} color="inherit" /> : <LockKeyhole size={18} />
                    }
                    sx={{
                      py: 1.35,
                      fontWeight: 900,
                      color: '#04121C',
                      background: `linear-gradient(135deg, ${primary}, #A78BFA)`,
                      boxShadow: `0 16px 36px ${primary}2E`,
                      '&:hover': { background: `linear-gradient(135deg, ${primary}, #8B5CF6)` },
                    }}
                  >
                    {busy ? 'جارٍ التحقق الآمن…' : 'اتصال آمن'}
                  </Button>
                </Stack>
              </Box>

              {error ? (
                <Alert severity="error" sx={{ mt: 2, textAlign: 'right', fontSize: '0.75rem' }}>
                  {error}
                </Alert>
              ) : null}

              <Stack
                direction="row"
                spacing={0.8}
                alignItems="center"
                justifyContent="center"
                sx={{ mt: 2.2, color: 'rgba(255,255,255,.38)' }}
              >
                <HeartPulse size={13} />
                <Typography sx={{ fontSize: '0.61rem' }}>
                  التأمين الصحي · الموارد البشرية · الدعم الفني
                </Typography>
              </Stack>
            </Box>

            <Box sx={{ px: 2.4, pb: 1.8, textAlign: 'center' }}>
              <Typography sx={{ color: 'rgba(255,255,255,.28)', fontSize: '0.58rem', lineHeight: 1.8 }}>
                اتصال محمي وفق سياسة الاستخدام المقبول. لا تشارك كلمة المرور مع أي شخص.
              </Typography>
            </Box>
          </Box>
        </Box>
      </motion.div>
    </Box>
  );
}

export default QrSimulationPage;
