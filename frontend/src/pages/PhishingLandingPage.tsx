/**
 * Public simulated sign-in landing page.
 *
 * Two high-fidelity skins:
 *  - Microsoft 365 (light, pixel-close enterprise SSO)
 *  - Corporate HR (dark glassmorphism)
 *
 * The page writes a real form-view event, then captures every value the
 * recipient types and sends it to the same backend endpoint as the standalone
 * form. A 1.5s artificial authentication delay makes the interaction feel real
 * before the educational reveal.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { motion } from 'framer-motion';
import {
  ArrowLeft,
  Eye,
  EyeOff,
  Fingerprint,
  KeyRound,
  LockKeyhole,
  Mail,
  Shield,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { trackingApi } from '@/api/endpoints';
import type { TrackingContext } from '@/types';

const authButtonSx = {
  width: '100%',
  py: 1.35,
  borderRadius: 1,
  fontSize: '0.92rem',
  fontWeight: 700,
  boxShadow: 'none',
} as const;

function delay(ms: number) {
  if (process.env.NODE_ENV === 'test') return Promise.resolve();
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function MicrosoftLogo({ size = 21 }: { size?: number }) {
  const cell = size / 2 - 1;
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: `${cell}px ${cell}px`, gap: '2px', width: size, height: size }}>
      <Box sx={{ bgcolor: '#f25022' }} />
      <Box sx={{ bgcolor: '#7fba00' }} />
      <Box sx={{ bgcolor: '#00a4ef' }} />
      <Box sx={{ bgcolor: '#ffb900' }} />
    </Box>
  );
}

function InvalidLink() {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 2 }}>
      <Box
        sx={{
          maxWidth: 460,
          width: '100%',
          p: 4,
          borderRadius: 4,
          textAlign: 'center',
          bgcolor: 'rgba(21,30,50,.8)',
          border: '1px solid rgba(255,23,68,.25)',
          boxShadow: '0 30px 90px rgba(0,0,0,.5)',
        }}
      >
        <ShieldAlert size={42} color="#FF1744" />
        <Typography sx={{ fontSize: '1.2rem', fontWeight: 800, mt: 2, mb: 1 }}>
          رابط التدريب غير معروف
        </Typography>
        <Typography variant="body2" color="text.secondary">
          هذا الرابط غير صالح أو انتهت صلاحيته. تواصل مع فريق الأمن السيبراني في مؤسستك.
        </Typography>
      </Box>
    </Box>
  );
}

interface SkinProps {
  context: TrackingContext;
  identifier: string;
  password: string;
  showPassword: boolean;
  submitting: boolean;
  error: string | null;
  step: 'credentials' | 'otp';
  otpCode: string;
  onOtpCode: (value: string) => void;
  onOtpSubmit: (event: FormEvent) => void;
  onIdentifier: (value: string) => void;
  onPassword: (value: string) => void;
  onTogglePassword: () => void;
  onSubmit: (event: FormEvent) => void;
  onReport: () => void;
  onBack: () => void;
}

function MicrosoftSkin(props: SkinProps) {
  return (
    <Box
      dir="ltr"
      sx={{
        minHeight: '100vh',
        position: 'relative',
        overflow: 'hidden',
        background: 'linear-gradient(135deg, #eaf0f8 0%, #dce6f4 38%, #e8eef7 100%)',
        fontFamily: "'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Arial, sans-serif",
        display: 'flex',
        flexDirection: 'column',
        textAlign: 'start',
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          width: 620,
          height: 620,
          borderRadius: '50%',
          top: -260,
          right: -180,
          background: 'radial-gradient(circle, rgba(0,120,212,.20), transparent 66%)',
          filter: 'blur(10px)',
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          width: 560,
          height: 560,
          borderRadius: '50%',
          bottom: -240,
          left: -160,
          background: 'radial-gradient(circle, rgba(112,0,255,.14), transparent 68%)',
          filter: 'blur(12px)',
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          inset: 0,
          opacity: 0.45,
          backgroundImage:
            'linear-gradient(rgba(0,103,184,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(0,103,184,.045) 1px, transparent 1px)',
          backgroundSize: '42px 42px',
          maskImage: 'radial-gradient(circle at 50% 40%, black, transparent 72%)',
        }}
      />

      <Box
        component="form"
        onSubmit={props.step === 'otp' ? props.onOtpSubmit : props.onSubmit}
        sx={{
          position: 'relative',
          zIndex: 1,
          width: '100%',
          maxWidth: 448,
          mx: 'auto',
          my: 'auto',
          px: { xs: 2, sm: 0 },
          py: 4,
        }}
      >
        <Box
          sx={{
            background: '#ffffff',
            borderRadius: 0.5,
            px: { xs: 3, sm: 5 },
            py: { xs: 4, sm: 5 },
            boxShadow: '0 12px 40px rgba(0,0,0,.16), 0 1px 2px rgba(0,0,0,.08)',
            color: '#1b1b1b',
          }}
        >
          <Stack direction="row" alignItems="center" sx={{ mb: 3.2, gap: 1.1 }}>
            <MicrosoftLogo />
            <Typography sx={{ fontSize: '1rem', fontWeight: 600, color: '#5e5e5e', letterSpacing: '-.01em' }}>
              Microsoft
            </Typography>
          </Stack>

          {props.step === 'otp' ? (
            <>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
                <Box
                  component="button"
                  type="button"
                  onClick={props.onBack}
                  sx={{ border: 0, background: 'transparent', cursor: 'pointer', p: 0, display: 'flex' }}
                >
                  <ArrowLeft size={16} color="#0067b8" />
                </Box>
                <Typography sx={{ fontSize: '0.86rem', color: '#1b1b1b', fontWeight: 600 }}>
                  {props.identifier || props.context.email}
                </Typography>
              </Stack>

              <Typography sx={{ fontSize: '1.55rem', fontWeight: 600, color: '#1b1b1b', lineHeight: 1.25, mb: 1 }}>
                Enter verification code
              </Typography>
              <Typography sx={{ fontSize: '0.84rem', color: '#5e5e5e', mb: 2.5, lineHeight: 1.5 }}>
                Enter the 6-digit code displayed in your authenticator app or sent to your phone.
              </Typography>

              {props.error ? (
                <Box
                  sx={{
                    mb: 2,
                    p: 1.25,
                    borderRadius: 1,
                    bgcolor: '#fde7e9',
                    border: '1px solid #f1bbbc',
                    color: '#a4262c',
                    fontSize: '0.8rem',
                    lineHeight: 1.5,
                  }}
                >
                  {props.error}
                </Box>
              ) : null}

              <Box
                component="input"
                aria-label="6-digit verification code"
                placeholder="000000"
                value={props.otpCode}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  props.onOtpCode(event.target.value.replace(/\D/g, '').slice(0, 6))
                }
                autoFocus
                maxLength={6}
                sx={{
                  width: '100%',
                  boxSizing: 'border-box',
                  border: 'none',
                  borderBottom: '2px solid #0067b8',
                  outline: 'none',
                  bgcolor: 'transparent',
                  fontSize: '1.4rem',
                  letterSpacing: '0.35em',
                  textAlign: 'center',
                  color: '#1b1b1b',
                  px: 1,
                  py: 1,
                  mb: 3,
                  fontFamily: 'inherit',
                  fontWeight: 700,
                }}
              />

              <Button
                type="submit"
                variant="contained"
                disabled={props.submitting}
                sx={{
                  ...authButtonSx,
                  background: '#0067b8',
                  backgroundImage: 'none',
                  color: '#fff',
                  '&:hover': { background: '#005da6', backgroundImage: 'none', boxShadow: 'none' },
                  '&.Mui-disabled': { background: '#c8c6c4', backgroundImage: 'none', color: '#fff' },
                }}
              >
                {props.submitting ? <CircularProgress size={20} sx={{ color: '#fff' }} /> : 'Verify'}
              </Button>
            </>
          ) : (
            <>
              <Typography sx={{ fontSize: '1.65rem', fontWeight: 600, color: '#1b1b1b', lineHeight: 1.25, mb: 1 }}>
                Sign in
              </Typography>
              <Typography sx={{ fontSize: '0.88rem', color: '#5e5e5e', mb: 2.8 }}>
                to continue to Microsoft 365
              </Typography>

              {props.error ? (
                <Box
                  sx={{
                    mb: 2,
                    p: 1.25,
                    borderRadius: 1,
                    bgcolor: '#fde7e9',
                    border: '1px solid #f1bbbc',
                    color: '#a4262c',
                    fontSize: '0.8rem',
                    lineHeight: 1.5,
                  }}
                >
                  {props.error}
                </Box>
              ) : null}

              <Box
                component="input"
                aria-label="Email, phone, or Skype"
                placeholder="Email, phone, or Skype"
                value={props.identifier}
                onChange={(event: ChangeEvent<HTMLInputElement>) => props.onIdentifier(event.target.value)}
                autoComplete="username"
                sx={{
                  width: '100%',
                  boxSizing: 'border-box',
                  border: 'none',
                  borderBottom: '1px solid #8a8886',
                  outline: 'none',
                  bgcolor: 'transparent',
                  fontSize: '0.92rem',
                  color: '#1b1b1b',
                  px: 0,
                  py: 1.1,
                  fontFamily: 'inherit',
                  '&:focus': { borderBottomColor: '#0067b8', borderBottomWidth: 2 },
                }}
              />
              <Typography sx={{ fontSize: '0.72rem', color: '#5e5e5e', mt: 0.7 }}>
                No account? <Box component="span" sx={{ color: '#0067b8' }}>Create one!</Box>
              </Typography>

              <Box
                sx={{
                  mt: 3,
                  mb: 1,
                  p: 1.6,
                  borderRadius: 0.75,
                  bgcolor: '#f3f2f1',
                  border: '1px solid #e1dfdd',
                }}
              >
                <Stack direction="row" alignItems="center" sx={{ mb: 1.1, gap: 1 }}>
                  <LockKeyhole size={15} color="#0067b8" />
                  <Typography sx={{ fontSize: '0.78rem', fontWeight: 600, color: '#323130' }}>
                    Verify your identity
                  </Typography>
                </Stack>
                <Stack direction="row" alignItems="center" sx={{ gap: 1 }}>
                  <Box
                    component="input"
                    aria-label="Password"
                    type={props.showPassword ? 'text' : 'password'}
                    placeholder="Password"
                    value={props.password}
                    onChange={(event: ChangeEvent<HTMLInputElement>) => props.onPassword(event.target.value)}
                    autoComplete="current-password"
                    sx={{
                      flex: 1,
                      border: '1px solid #8a8886',
                      borderRadius: 0.5,
                      bgcolor: '#fff',
                      px: 1.2,
                      py: 1,
                      fontSize: '0.9rem',
                      color: '#1b1b1b',
                      outline: 'none',
                      fontFamily: 'inherit',
                      '&:focus': { borderColor: '#0067b8', boxShadow: '0 0 0 1px #0067b8' },
                    }}
                  />
                  <Box
                    component="button"
                    type="button"
                    aria-label={props.showPassword ? 'Hide password' : 'Show password'}
                    onClick={props.onTogglePassword}
                    sx={{
                      border: 0,
                      background: 'transparent',
                      color: '#0067b8',
                      cursor: 'pointer',
                      p: 0.5,
                      display: 'grid',
                      placeItems: 'center',
                    }}
                  >
                    {props.showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </Box>
                </Stack>
              </Box>

              <Typography sx={{ fontSize: '0.74rem', color: '#0067b8', mb: 2.6 }}>
                Forgot password?
              </Typography>

              <Button
                type="submit"
                variant="contained"
                disabled={props.submitting}
                sx={{
                  ...authButtonSx,
                  background: '#0067b8',
                  backgroundImage: 'none',
                  color: '#fff',
                  '&:hover': { background: '#005da6', backgroundImage: 'none', boxShadow: 'none' },
                  '&.Mui-disabled': { background: '#c8c6c4', backgroundImage: 'none', color: '#fff' },
                }}
              >
                {props.submitting ? <CircularProgress size={20} sx={{ color: '#fff' }} /> : 'Sign in'}
              </Button>

              <Stack direction="row" alignItems="center" sx={{ mt: 2.2, color: '#0067b8', gap: 0.5 }}>
                <KeyRound size={14} />
                <Typography sx={{ fontSize: '0.76rem' }}>Sign-in options</Typography>
              </Stack>
            </>
          )}
        </Box>

        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="center"
          sx={{ mt: 2.5, color: '#5e5e5e', fontSize: '0.7rem', px: 1 }}
        >
          <Stack direction="row" sx={{ gap: 2 }}>
            <Box component="span">Terms of use</Box>
            <Box component="span">Privacy &amp; cookies</Box>
          </Stack>
          <Box
            component="button"
            type="button"
            onClick={props.onReport}
            sx={{ border: 0, background: 'transparent', color: '#5e5e5e', cursor: 'pointer', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: 0.5 }}
          >
            <ShieldCheck size={12} /> Report this page
          </Box>
        </Stack>

        <Box
          sx={{
            mt: 2,
            p: 1.4,
            borderRadius: 1,
            bgcolor: 'rgba(255,255,255,.66)',
            border: '1px solid rgba(0,103,184,.14)',
            color: '#5e5e5e',
            fontSize: '0.68rem',
            lineHeight: 1.6,
          }}
        >
          <strong>Security simulation.</strong> This is an authorized awareness exercise
          for {props.context.company_name ?? 'your organization'}. No real Microsoft
          service is involved.
        </Box>
      </Box>
    </Box>
  );
}

function HrSkin(props: SkinProps) {
  return (
    <Box
      sx={{
        minHeight: '100vh',
        position: 'relative',
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        p: 2,
        background:
          'radial-gradient(circle at 15% 20%, rgba(0,240,255,.16), transparent 38%), radial-gradient(circle at 85% 80%, rgba(112,0,255,.22), transparent 42%), linear-gradient(145deg, #08101e, #0d1526 52%, #080d18)',
      }}
    >
      <Box className="mc-grid-overlay" />
      <Box className="mc-orb mc-orb--cyan" />
      <Box className="mc-orb mc-orb--violet" />

      <motion.div
        initial={{ opacity: 0, y: 22, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        style={{ width: '100%', maxWidth: 470, position: 'relative', zIndex: 1 }}
      >
        <Box
          component="form"
          onSubmit={props.step === 'otp' ? props.onOtpSubmit : props.onSubmit}
          sx={{
            p: { xs: 2.6, sm: 4 },
            borderRadius: 4,
            background: 'linear-gradient(160deg, rgba(27,39,64,.90), rgba(10,16,29,.94))',
            border: '1px solid rgba(0,240,255,.18)',
            boxShadow: '0 40px 120px rgba(0,0,0,.62), 0 0 50px rgba(0,240,255,.08)',
            backdropFilter: 'blur(20px)',
          }}
        >
          <Stack direction="row" spacing={1.2} alignItems="center" sx={{ mb: 3 }}>
            <Box
              sx={{
                width: 44,
                height: 44,
                borderRadius: 2,
                display: 'grid',
                placeItems: 'center',
                color: 'primary.main',
                bgcolor: 'rgba(0,240,255,.08)',
                border: '1px solid rgba(0,240,255,.25)',
              }}
            >
              <Shield size={22} />
            </Box>
            <Box>
              <Typography sx={{ fontWeight: 800, fontSize: '1rem', lineHeight: 1.3 }}>
                {props.context.company_name ?? 'Corporate Portal'}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary', letterSpacing: '.08em' }}>
                HUMAN RESOURCES · SECURE ACCESS
              </Typography>
            </Box>
          </Stack>

          {props.step === 'otp' ? (
            <>
              <Typography sx={{ fontSize: '1.4rem', fontWeight: 800, mb: 0.5 }}>
                رمز التحقق الثنائي (2FA)
              </Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary', mb: 3 }}>
                أدخل رمز التحقق المكون من 6 أرقام المرسل إلى هاتفك أو تطبيق المصادقة للمتابعة إلى بوابتك الوظيفية.
              </Typography>

              {props.error ? (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {props.error}
                </Alert>
              ) : null}

              <Box sx={{ mb: 3 }}>
                <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 0.8, textAlign: 'center' }}>
                  رمز التحقق (6 أرقام)
                </Typography>
                <Box
                  component="input"
                  aria-label="رمز التحقق"
                  placeholder="••••••"
                  value={props.otpCode}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    props.onOtpCode(event.target.value.replace(/\D/g, '').slice(0, 6))
                  }
                  autoFocus
                  maxLength={6}
                  sx={{
                    width: '100%',
                    boxSizing: 'border-box',
                    border: '1px solid rgba(0,240,255,.35)',
                    borderRadius: 2,
                    bgcolor: 'rgba(8,14,25,.75)',
                    color: '#00F0FF',
                    py: 1.6,
                    px: 1,
                    fontFamily: 'monospace',
                    fontSize: '1.6rem',
                    letterSpacing: '0.45em',
                    textAlign: 'center',
                    outline: 'none',
                    fontWeight: 800,
                    '&:focus': { borderColor: 'primary.main', boxShadow: '0 0 0 3px rgba(0,240,255,.18)' },
                  }}
                />
              </Box>

              <Button
                type="submit"
                variant="contained"
                disabled={props.submitting}
                startIcon={props.submitting ? <CircularProgress size={17} color="inherit" /> : <LockKeyhole size={17} />}
                sx={{ width: '100%', py: 1.45, mb: 2 }}
              >
                {props.submitting ? 'جارٍ التحقق من الرمز…' : 'تأكيد الرمز ومتابعة الدخول'}
              </Button>
            </>
          ) : (
            <>
              <Typography sx={{ fontSize: '1.4rem', fontWeight: 800, mb: 0.5 }}>
                بوابة الموارد البشرية
              </Typography>
              <Typography variant="body2" sx={{ color: 'text.secondary', mb: 3 }}>
                سجّل الدخول لمراجعة سجلك الوظيفي وتحديث بياناتك قبل نهاية الأسبوع.
              </Typography>

              {props.error ? (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {props.error}
                </Alert>
              ) : null}

              <Stack spacing={1.2}>
                <Box>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 0.6 }}>
                    البريد المؤسسي
                  </Typography>
                  <Stack
                    direction="row"
                    alignItems="center"
                    sx={{
                      border: '1px solid rgba(255,255,255,.13)',
                      borderRadius: 2,
                      bgcolor: 'rgba(8,14,25,.55)',
                      px: 1.4,
                      '&:focus-within': { borderColor: 'primary.main', boxShadow: '0 0 0 3px rgba(0,240,255,.10)' },
                    }}
                  >
                    <Mail size={16} color="#8B9BB4" />
                    <Box
                      component="input"
                      aria-label="البريد المؤسسي"
                      value={props.identifier}
                      onChange={(event: ChangeEvent<HTMLInputElement>) => props.onIdentifier(event.target.value)}
                      autoComplete="username"
                      sx={{
                        flex: 1,
                        border: 0,
                        outline: 0,
                        bgcolor: 'transparent',
                        color: 'text.primary',
                        py: 1.35,
                        px: 1,
                        fontFamily: 'inherit',
                        fontSize: '0.88rem',
                      }}
                    />
                  </Stack>
                </Box>

                <Box>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 0.6 }}>
                    كلمة المرور
                  </Typography>
                  <Stack
                    direction="row"
                    alignItems="center"
                    sx={{
                      border: '1px solid rgba(255,255,255,.13)',
                      borderRadius: 2,
                      bgcolor: 'rgba(8,14,25,.55)',
                      px: 1.4,
                      '&:focus-within': { borderColor: 'primary.main', boxShadow: '0 0 0 3px rgba(0,240,255,.10)' },
                    }}
                  >
                    <LockKeyhole size={16} color="#8B9BB4" />
                    <Box
                      component="input"
                      aria-label="كلمة المرور"
                      type={props.showPassword ? 'text' : 'password'}
                      placeholder="••••••••"
                      value={props.password}
                      onChange={(event: ChangeEvent<HTMLInputElement>) => props.onPassword(event.target.value)}
                      autoComplete="current-password"
                      sx={{
                        flex: 1,
                        border: 0,
                        outline: 0,
                        bgcolor: 'transparent',
                        color: 'text.primary',
                        py: 1.35,
                        px: 1,
                        fontFamily: 'inherit',
                        fontSize: '0.88rem',
                      }}
                    />
                    <Box
                      component="button"
                      type="button"
                      onClick={props.onTogglePassword}
                      aria-label={props.showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
                      sx={{ border: 0, background: 'transparent', color: 'text.secondary', cursor: 'pointer', display: 'grid', placeItems: 'center', p: 0.4 }}
                    >
                      {props.showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                    </Box>
                  </Stack>
                </Box>
              </Stack>

              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mt: 1.5, mb: 2.4 }}>
                <Stack direction="row" spacing={0.8} alignItems="center">
                  <Box
                    component="input"
                    type="checkbox"
                    defaultChecked
                    aria-label="تذكرني"
                    sx={{ accentColor: '#00F0FF', width: 14, height: 14 }}
                  />
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    تذكرني على هذا الجهاز
                  </Typography>
                </Stack>
                <Typography variant="caption" sx={{ color: 'primary.main', cursor: 'pointer' }}>
                  نسيت كلمة المرور؟
                </Typography>
              </Stack>

              <Button
                type="submit"
                variant="contained"
                disabled={props.submitting}
                startIcon={props.submitting ? <CircularProgress size={17} color="inherit" /> : <Fingerprint size={17} />}
                sx={{ width: '100%', py: 1.45 }}
              >
                {props.submitting ? 'جارٍ التحقق من الهوية…' : 'دخول آمن'}
              </Button>
            </>
          )}

          <Stack direction="row" justifyContent="center" spacing={0.6} alignItems="center" sx={{ mt: 2.4 }}>
            <ShieldCheck size={14} color="#00E676" />
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              اتصال مشفّر · وصول مُسجّل · MFA جاهز
            </Typography>
          </Stack>

          <Stack direction="row" justifyContent="space-between" sx={{ mt: 2.3, pt: 2, borderTop: '1px solid rgba(255,255,255,.07)' }}>
            <Box
              component="button"
              type="button"
              onClick={props.onReport}
              sx={{ border: 0, background: 'transparent', color: 'text.secondary', cursor: 'pointer', fontSize: '0.7rem', display: 'flex', gap: 0.5, alignItems: 'center' }}
            >
              <ShieldCheck size={12} /> أبلغ عن هذه الصفحة
            </Box>
            <Box
              component="button"
              type="button"
              onClick={props.onBack}
              sx={{ border: 0, background: 'transparent', color: 'primary.main', cursor: 'pointer', fontSize: '0.7rem', display: 'flex', gap: 0.5, alignItems: 'center' }}
            >
              <ArrowLeft size={12} /> رجوع
            </Box>
          </Stack>
        </Box>
        <Typography
          variant="caption"
          sx={{ display: 'block', textAlign: 'center', color: 'text.disabled', mt: 2, fontSize: '0.64rem' }}
        >
          محاكاة تدريبية مصرّح بها · {props.context.company_name}
        </Typography>
      </motion.div>
    </Box>
  );
}

export function PhishingLandingPage() {
  const { trackingUuid } = useParams<{ trackingUuid: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const startedAt = useRef(Date.now());
  const firstInputAt = useRef<number | null>(null);
  const viewLogged = useRef(false);

  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState<'credentials' | 'otp'>('credentials');
  const [otpCode, setOtpCode] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submittedRef = useRef(false);

  const contextQuery = useQuery({
    queryKey: ['tracking-context', trackingUuid],
    queryFn: () => trackingApi.context(trackingUuid as string),
    enabled: Boolean(trackingUuid),
    staleTime: 60_000,
    retry: 1,
  });

  useEffect(() => {
    if (!contextQuery.data?.email) return;
    setIdentifier((current) => current || (contextQuery.data.email as string));
  }, [contextQuery.data]);

  useEffect(() => {
    if (!trackingUuid || viewLogged.current) return;
    viewLogged.current = true;
    void trackingApi.formViewed(trackingUuid).catch(() => undefined);
  }, [trackingUuid]);

  useEffect(() => {
    // Only skip the form when the recipient has actually submitted it (or
    // reported the message). `already_completed` alone can mean an older
    // recipient was sent straight to the awareness page by a previous build;
    // those recipients must still see the simulated sign-in form first.
    if (
      !submittedRef.current &&
      (contextQuery.data?.form_submitted || contextQuery.data?.is_reported_safe) &&
      trackingUuid
    ) {
      navigate(`/training-experience/${trackingUuid}`, { replace: true });
    }
  }, [contextQuery.data, navigate, trackingUuid]);

  function markFirstInput() {
    if (firstInputAt.current === null) firstInputAt.current = Date.now();
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!trackingUuid || submitting) return;
    if (!password) {
      setError('أدخل كلمة المرور للمتابعة.');
      return;
    }
    setSubmitting(true);
    setError(null);
    const now = Date.now();
    try {
      const result = await trackingApi.submit(trackingUuid, {
        identifier,
        password,
        password_length: password.length,
        fields: { identifier, password, remember: 'true' },
        client: {
          page_loaded_at: new Date(startedAt.current).toISOString(),
          first_input_at: firstInputAt.current ? new Date(firstInputAt.current).toISOString() : null,
          submitted_at: new Date(now).toISOString(),
          seconds_on_form: Math.round((now - startedAt.current) / 1000),
          fill_time_ms: firstInputAt.current === null ? null : now - firstInputAt.current,
          language: navigator.language || null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
          viewport: `${window.innerWidth}x${window.innerHeight}`,
          referrer: document.referrer || null,
        },
      });
      await delay(1200);
      if (!result.success) {
        setError('تعذّر التحقق من الجلسة. حاول مرة أخرى.');
        setSubmitting(false);
        return;
      }
      setSubmitting(false);
      setError(null);
      setStep('otp');
    } catch {
      await delay(1200);
      setError('تعذّر الاتصال بخادم الهوية. تحقّق من الشبكة وحاول مرة أخرى.');
      setSubmitting(false);
    }
  }

  async function handleOtpSubmit(event: FormEvent) {
    event.preventDefault();
    if (!trackingUuid || submitting) return;
    const cleanOtp = otpCode.trim();
    if (!cleanOtp) {
      setError('أدخل رمز التحقق المكون من 6 أرقام للمتابعة.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await trackingApi.submitOtp(trackingUuid, cleanOtp);
      await delay(1200);
      submittedRef.current = true;
      navigate(`/training-experience/${trackingUuid}?mfa=true`, { replace: true });
    } catch {
      await delay(1200);
      submittedRef.current = true;
      navigate(`/training-experience/${trackingUuid}?mfa=true`, { replace: true });
    }
  }

  async function handleReport() {
    if (!trackingUuid) return;
    try {
      await trackingApi.report(trackingUuid);
    } catch {
      // Reporting is best effort; the reveal still explains the simulation.
    }
    navigate(`/training-experience/${trackingUuid}`, { replace: true });
  }

  if (contextQuery.isLoading) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
        <Stack alignItems="center" spacing={2}>
          <CircularProgress />
          <Typography variant="body2" color="text.secondary">
            جارٍ تحميل بوابة الدخول…
          </Typography>
        </Stack>
      </Box>
    );
  }

  if (!trackingUuid || contextQuery.error || !contextQuery.data?.found) {
    return <InvalidLink />;
  }

  const requestedSkin = params.get('skin');
  const skin =
    requestedSkin === 'hr' || requestedSkin === 'microsoft'
      ? requestedSkin
      : contextQuery.data.skin === 'hr'
        ? 'hr'
        : 'microsoft';

  const shared: SkinProps = {
    context: contextQuery.data,
    identifier,
    password,
    showPassword,
    submitting,
    error,
    step,
    otpCode,
    onOtpCode: setOtpCode,
    onOtpSubmit: handleOtpSubmit,
    onIdentifier: (value) => {
      markFirstInput();
      setIdentifier(value);
    },
    onPassword: (value) => {
      markFirstInput();
      setPassword(value);
    },
    onTogglePassword: () => setShowPassword((value) => !value),
    onSubmit: handleSubmit,
    onReport: () => void handleReport(),
    onBack: () => {
      if (step === 'otp') {
        setStep('credentials');
        setError(null);
      } else {
        navigate(-1);
      }
    },
  };

  return skin === 'hr' ? <HrSkin {...shared} /> : <MicrosoftSkin {...shared} />;
}
