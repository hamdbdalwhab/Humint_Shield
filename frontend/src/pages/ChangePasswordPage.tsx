/**
 * Change the signed-in operator's password.
 *
 * The rules mirror the backend policy (`app/schemas/password_policy.py`); the
 * server remains authoritative. On success the rotated token pair replaces the
 * current session and the operator is returned to the dashboard.
 */
import { zodResolver } from '@hookform/resolvers/zod';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { Check, Eye, EyeOff, ShieldCheck, X } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { z } from 'zod';

import { authApi } from '@/api/endpoints';
import { PageHeader } from '@/components/PageHeader';
import { errorMessage } from '@/lib/errors';
import { setSession, useAppDispatch } from '@/store';

const PASSWORD_RULES = [
  { label: '8 أحرف على الأقل', test: (value: string) => value.length >= 8 },
  { label: 'حرف كبير واحد على الأقل', test: (value: string) => /[A-Z]/.test(value) },
  { label: 'حرف صغير واحد على الأقل', test: (value: string) => /[a-z]/.test(value) },
  { label: 'رقم واحد على الأقل', test: (value: string) => /\d/.test(value) },
  { label: 'رمز خاص واحد على الأقل (!@#$…)', test: (value: string) => /[^A-Za-z0-9]/.test(value) },
];

const schema = z
  .object({
    current_password: z.string().min(1, 'كلمة المرور الحالية مطلوبة'),
    new_password: z
      .string()
      .min(8, 'كلمة المرور يجب أن تكون 8 أحرف على الأقل')
      .regex(/[A-Z]/, 'يجب أن تحتوي على حرف كبير واحد على الأقل')
      .regex(/[a-z]/, 'يجب أن تحتوي على حرف صغير واحد على الأقل')
      .regex(/\d/, 'يجب أن تحتوي على رقم واحد على الأقل')
      .regex(/[^A-Za-z0-9]/, 'يجب أن تحتوي على رمز خاص واحد على الأقل'),
    confirm_password: z.string().min(1, 'يرجى تأكيد كلمة المرور الجديدة'),
  })
  .refine((values) => values.new_password === values.confirm_password, {
    path: ['confirm_password'],
    message: 'كلمتا المرور غير متطابقتين',
  });

type FormValues = z.infer<typeof schema>;

export function ChangePasswordPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { current_password: '', new_password: '', confirm_password: '' },
  });

  const candidate = watch('new_password') ?? '';

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      const result = await authApi.changePassword(values.current_password, values.new_password);
      dispatch(setSession({ user: result.user, access: result.access, refresh: result.refresh }));
      toast.success('تم تغيير كلمة المرور وتسجيل خروج الجلسات الأخرى بنجاح');
      navigate('/', { replace: true });
    } catch (caught) {
      setError(errorMessage(caught));
    }
  });

  const passwordType = reveal ? 'text' : 'password';

  return (
    <Box>
      <PageHeader
        eyebrow="HUMINT SHIELD · ACCOUNT SECURITY"
        title="تغيير كلمة المرور"
        subtitle="حدّث بيانات الدخول الخاصة بك وأبطل كل الجلسات السابقة."
      />

      <Box sx={{ maxWidth: 620 }}>
        <Card>
          <CardContent sx={{ p: { xs: 2, sm: 3 } }}>
            {error ? (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            ) : null}

            <Stack
              component="form"
              spacing={2.25}
              onSubmit={onSubmit}
              noValidate
              autoComplete="off"
            >
              <TextField
                label="كلمة المرور الحالية"
                type={passwordType}
                autoComplete="current-password"
                fullWidth
                error={Boolean(errors.current_password)}
                helperText={errors.current_password?.message}
                {...register('current_password')}
              />
              <TextField
                label="كلمة المرور الجديدة"
                type={passwordType}
                autoComplete="new-password"
                fullWidth
                error={Boolean(errors.new_password)}
                helperText={errors.new_password?.message}
                InputProps={{
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton
                        size="small"
                        aria-label={reveal ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
                        onClick={() => setReveal((value) => !value)}
                      >
                        {reveal ? <EyeOff size={17} /> : <Eye size={17} />}
                      </IconButton>
                    </InputAdornment>
                  ),
                }}
                {...register('new_password')}
              />
              <TextField
                label="تأكيد كلمة المرور الجديدة"
                type={passwordType}
                autoComplete="new-password"
                fullWidth
                error={Boolean(errors.confirm_password)}
                helperText={errors.confirm_password?.message}
                {...register('confirm_password')}
              />

              <Divider />

              <Box>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                  متطلبات كلمة المرور
                </Typography>
                <Stack component="ul" spacing={0.5} sx={{ listStyle: 'none', m: 0, p: 0 }}>
                  {PASSWORD_RULES.map((rule) => {
                    const met = rule.test(candidate);
                    return (
                      <Stack
                        key={rule.label}
                        component="li"
                        direction="row"
                        spacing={1}
                        alignItems="center"
                        sx={{ color: met ? 'success.main' : 'text.secondary', fontSize: '0.78rem' }}
                      >
                        {met ? <Check size={14} /> : <X size={14} />}
                        <span>{rule.label}</span>
                      </Stack>
                    );
                  })}
                </Stack>
              </Box>

              <Alert severity="info" icon={<ShieldCheck size={18} />}>
                عند الحفظ تُسجَّل خروج كل الأجهزة الأخرى ويُستبدل رمز جلستك الحالية تلقائياً.
              </Alert>

              <Stack direction="row" spacing={1.5} justifyContent="flex-end">
                <Button variant="text" onClick={() => navigate('/')} disabled={isSubmitting}>
                  إلغاء
                </Button>
                <Button
                  type="submit"
                  variant="contained"
                  disabled={isSubmitting}
                  startIcon={
                    isSubmitting ? <CircularProgress size={16} color="inherit" /> : <ShieldCheck size={16} />
                  }
                >
                  {isSubmitting ? 'جارٍ التحديث…' : 'تحديث كلمة المرور'}
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}
