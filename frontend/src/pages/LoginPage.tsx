/** Immersive sign-in page for the HUMINT Shield command centre. */
import { zodResolver } from '@hookform/resolvers/zod';
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
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';
import {
  Activity,
  Eye,
  EyeOff,
  Fingerprint,
  LockKeyhole,
  Shield,
  ShieldCheck,
  Sparkles,
  UserRound,
} from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { z } from 'zod';

import { errorMessage } from '@/lib/errors';
import { useAuth } from '@/hooks/useAuth';

const schema = z.object({
  username: z.string().min(1, 'اسم المستخدم مطلوب'),
  password: z.string().min(1, 'كلمة المرور مطلوبة'),
});

type FormValues = z.infer<typeof schema>;

const FEATURES = [
  { icon: Activity, title: 'مراقبة حيّة', text: 'كل فتح ونقرة تظهر لحظياً على لوحة القيادة.' },
  { icon: Fingerprint, title: 'أدلة دقيقة', text: 'كل قيمة تُكتب تُسجّل بالثانية مع السياق الكامل.' },
  { icon: ShieldCheck, title: 'توعية فورية', text: 'صفحة تدريب عربية تُعلّم الموظف دون إذلاله.' },
];

export function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const from = (location.state as { from?: string } | null)?.from ?? '/';

  if (isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await login(values.username.trim(), values.password);
      navigate(from, { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    }
  });

  return (
    <Box
      sx={{
        minHeight: '100vh',
        position: 'relative',
        overflow: 'hidden',
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', lg: '1.05fr 0.95fr' },
        bgcolor: 'background.default',
      }}
    >
      <Box className="mc-grid-overlay" />
      <Box className="mc-orb mc-orb--cyan" />
      <Box className="mc-orb mc-orb--violet" />

      {/* ---------- story / brand panel ---------- */}
      <Box
        sx={{
          position: 'relative',
          zIndex: 1,
          display: { xs: 'none', lg: 'flex' },
          flexDirection: 'column',
          justifyContent: 'space-between',
          p: { lg: 6, xl: 8 },
          borderInlineStart: '1px solid rgba(255,255,255,.06)',
          background:
            'radial-gradient(circle at 80% 10%, rgba(0,240,255,.10), transparent 42%), radial-gradient(circle at 10% 90%, rgba(112,0,255,.16), transparent 45%)',
        }}
      >
        <Stack direction="row" spacing={1.5} alignItems="center">
          <Box
            sx={{
              width: 48,
              height: 48,
              borderRadius: 2.5,
              display: 'grid',
              placeItems: 'center',
              color: 'primary.main',
              bgcolor: 'rgba(0,240,255,.08)',
              border: '1px solid rgba(0,240,255,.35)',
              boxShadow: '0 0 32px rgba(0,240,255,.22)',
            }}
          >
            <Shield size={26} />
          </Box>
          <Box>
            <Typography sx={{ fontWeight: 800, fontSize: '1.1rem', lineHeight: 1.2 }}>
              HUMINT <Box component="span" sx={{ color: 'primary.main' }}>Shield</Box>
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', letterSpacing: '.12em', fontSize: '0.62rem' }}>
              HUMAN RISK COMMAND
            </Typography>
          </Box>
        </Stack>

        <Box sx={{ maxWidth: 560 }}>
          <Chip
            size="small"
            icon={<Sparkles size={13} />}
            label="منصة محاكاة التوعية الأمنية"
            color="primary"
            variant="outlined"
            sx={{ mb: 2.5 }}
          />
          <Typography
            component="h1"
            sx={{
              fontSize: { lg: '2.6rem', xl: '3.2rem' },
              fontWeight: 800,
              lineHeight: 1.25,
              letterSpacing: '-0.03em',
              mb: 1.5,
            }}
          >
            لا تُدرّب الموظفين
            <br />
            على <Box component="span" className="mc-neon-text">الخوف</Box> —
            <br />
            درّبهم على <Box component="span" sx={{ color: 'primary.main' }}>الملاحظة</Box>.
          </Typography>
          <Typography sx={{ color: 'text.secondary', fontSize: '0.98rem', maxWidth: 480, mb: 4 }}>
            غرفة عمليات واحدة تجمع الحملات، التتبع اللحظي، أدلة الإدخال، والتوعية العربية.
            كل ما تحتاجه لتحويل الحوادث البشرية إلى مناعة مؤسسية.
          </Typography>

          <Stack spacing={2}>
            {FEATURES.map((feature, index) => (
              <motion.div
                key={feature.title}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.15 + index * 0.1, duration: 0.45 }}
              >
                <Stack direction="row" spacing={1.5} alignItems="flex-start">
                  <Box
                    sx={{
                      width: 38,
                      height: 38,
                      borderRadius: 2,
                      display: 'grid',
                      placeItems: 'center',
                      color: index === 1 ? 'secondary.light' : 'primary.main',
                      bgcolor: index === 1 ? 'rgba(112,0,255,.10)' : 'rgba(0,240,255,.07)',
                      border: `1px solid ${index === 1 ? 'rgba(179,136,255,.25)' : 'rgba(0,240,255,.20)'}`,
                      flex: '0 0 auto',
                    }}
                  >
                    <feature.icon size={18} />
                  </Box>
                  <Box>
                    <Typography sx={{ fontWeight: 700, fontSize: '0.88rem' }}>{feature.title}</Typography>
                    <Typography sx={{ color: 'text.secondary', fontSize: '0.78rem' }}>{feature.text}</Typography>
                  </Box>
                </Stack>
              </motion.div>
            ))}
          </Stack>
        </Box>

        <Stack direction="row" spacing={2} alignItems="center">
          <Box className="mc-live-dot" />
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            النظام جاهز · كل الأحداث تُسجّل بالثانية
          </Typography>
        </Stack>
      </Box>

      {/* ---------- sign-in card ---------- */}
      <Box
        sx={{
          position: 'relative',
          zIndex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          p: { xs: 2, sm: 4, lg: 6 },
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 24, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
          style={{ width: '100%', maxWidth: 460 }}
        >
          <Box
            sx={{
              p: { xs: 2.5, sm: 4 },
              borderRadius: 4,
              background: 'linear-gradient(155deg, rgba(27,39,64,.92), rgba(11,17,30,.92))',
              border: '1px solid rgba(255,255,255,.10)',
              boxShadow: '0 40px 120px rgba(0,0,0,.55), 0 0 60px rgba(0,240,255,.07)',
              backdropFilter: 'blur(18px)',
            }}
          >
            <Stack alignItems="center" spacing={1} sx={{ mb: 3 }}>
              <Box
                sx={{
                  width: 58,
                  height: 58,
                  borderRadius: 3,
                  display: 'grid',
                  placeItems: 'center',
                  color: 'primary.main',
                  background:
                    'linear-gradient(135deg, rgba(0,240,255,.16), rgba(112,0,255,.22))',
                  border: '1px solid rgba(0,240,255,.35)',
                  boxShadow: '0 0 40px rgba(0,240,255,.22)',
                  mb: 0.5,
                }}
              >
                <LockKeyhole size={26} />
              </Box>
              <Typography sx={{ fontSize: '1.45rem', fontWeight: 800 }}>دخول مركز القيادة</Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary', textAlign: 'center' }}>
                جلسة مشفّرة · صلاحيات إدارية · تسجيل كامل للعمليات
              </Typography>
            </Stack>

            {error ? (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            ) : null}

            <Stack spacing={2.25} component="form" onSubmit={onSubmit} noValidate>
              <TextField
                label="اسم المستخدم"
                autoComplete="username"
                autoFocus
                fullWidth
                error={Boolean(errors.username)}
                helperText={errors.username?.message}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <UserRound size={17} color="#8B9BB4" />
                    </InputAdornment>
                  ),
                }}
                {...register('username')}
              />
              <TextField
                label="كلمة المرور"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                fullWidth
                error={Boolean(errors.password)}
                helperText={errors.password?.message}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <LockKeyhole size={17} color="#8B9BB4" />
                    </InputAdornment>
                  ),
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton
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
                {...register('password')}
              />
              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={isSubmitting}
                startIcon={isSubmitting ? <CircularProgress size={18} color="inherit" /> : <ShieldCheck size={18} />}
                sx={{ mt: 0.5 }}
              >
                {isSubmitting ? 'جارٍ التحقق…' : 'تأمين الدخول'}
              </Button>
            </Stack>

            <Box
              sx={{
                mt: 3,
                p: 1.5,
                borderRadius: 2,
                border: `1px solid ${alpha('#00F0FF', 0.12)}`,
                bgcolor: 'rgba(0,240,255,.035)',
              }}
            >
              <Typography variant="caption" sx={{ color: 'text.secondary', lineHeight: 1.8, display: 'block' }}>
                الاستخدام مصرّح به فقط. كل حملة تستهدف عناوين الشركة وتُسجّل لأغراض
                الامتثال والتوعية. لا تُدخل كلمات مرور حقيقية في نماذج المحاكاة.
              </Typography>
            </Box>
          </Box>
        </motion.div>
      </Box>
    </Box>
  );
}
