/**
 * SMS (smishing) landing page — `/sms-lure/:trackingUuid`.
 *
 * The skin is chosen, in order, from:
 *   1. the `?page=` query parameter resolved by the campaign launcher
 *      (`cisco_vpn`, `supplier_portal`, `hr_portal`, `teams_invite`,
 *      `microsoft_login`, `general_login`);
 *   2. the `landing_page` field of `/api/v1/track/context/{uuid}`;
 *   3. the template's department (`template_category`).
 *
 * Opening the link is score-neutral (`sms_clicked`); submitting the form is the
 * failure outcome and applies the -40 smishing penalty once. Only the typed
 * identifier is transmitted — never the password.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import {
  CalendarClock,
  FileText,
  Lock,
  LockKeyhole,
  ShieldCheck,
  Video,
  Wallet,
} from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';

import { trackingApi } from '@/api/endpoints';

type Skin = 'it' | 'finance' | 'hr' | 'executive' | 'microsoft' | 'generic';

interface SkinConfig {
  header: string;
  product: string;
  icon: typeof ShieldCheck;
  color: string;
  accent: string;
  identifierLabel: string;
  identifierPlaceholder: string;
  passwordLabel: string;
  cta: string;
  note: string;
  detail: { label: string; value: string }[];
  light?: boolean;
}

const SKINS: Record<Skin, SkinConfig> = {
  it: {
    header: 'Cisco AnyConnect',
    product: 'Secure Mobility Client',
    icon: ShieldCheck,
    color: '#0B2C4D',
    accent: '#00BCEB',
    identifierLabel: 'Username',
    identifierPlaceholder: 'company\\username',
    passwordLabel: 'Password',
    cta: 'Connect',
    note: 'VPN session expired · re-authentication required by policy',
    detail: [
      { label: 'Gateway', value: 'vpn.corp.example' },
      { label: 'Profile', value: 'Employee — Full Tunnel' },
    ],
  },
  finance: {
    header: 'Supplier Portal',
    product: 'Accounts Payable · Invoice Review',
    icon: FileText,
    color: '#0F3D2E',
    accent: '#2FBF71',
    identifierLabel: 'Supplier email',
    identifierPlaceholder: 'finance@supplier.com',
    passwordLabel: 'Portal password',
    cta: 'Open invoice',
    note: 'Action required within 24 hours to avoid payment delay',
    detail: [
      { label: 'Document', value: 'Invoice #INV-4471' },
      { label: 'Amount', value: 'USD 12,480.00' },
      { label: 'Status', value: 'Pending approval' },
    ],
  },
  hr: {
    header: 'HR Portal',
    product: 'Human Resources · Policy Acknowledgement',
    icon: Wallet,
    color: '#3B2A5A',
    accent: '#A78BFA',
    identifierLabel: 'Work email',
    identifierPlaceholder: 'name@company.com',
    passwordLabel: 'Directory password',
    cta: 'Review & sign',
    note: 'Mandatory policy update · acknowledgement closes today',
    detail: [
      { label: 'Policy', value: 'Acceptable Use 2026' },
      { label: 'Deadline', value: 'Today, 23:59' },
    ],
  },
  executive: {
    header: 'Microsoft Teams',
    product: 'Meeting invite',
    icon: Video,
    color: '#464775',
    accent: '#7B83EB',
    identifierLabel: 'Work account',
    identifierPlaceholder: 'name@company.com',
    passwordLabel: 'Password',
    cta: 'Join meeting',
    note: 'Board meeting · Organizer updated the time',
    detail: [
      { label: 'Meeting', value: 'Board — Quarterly Review' },
      { label: 'Time', value: 'Today, 16:30 (moved)' },
      { label: 'Organizer', value: 'Office of the CEO' },
    ],
  },
  microsoft: {
    header: 'Microsoft',
    product: 'Sign in to your account',
    icon: LockKeyhole,
    color: '#0F6CBD',
    accent: '#0F6CBD',
    identifierLabel: 'Email, phone or Skype',
    identifierPlaceholder: 'name@company.com',
    passwordLabel: 'Password',
    cta: 'Sign in',
    note: 'Your session expired — sign in again to continue',
    detail: [
      { label: 'Account', value: 'Microsoft 365' },
      { label: 'Device', value: 'Managed workstation' },
    ],
  },
  generic: {
    header: 'Secure account portal',
    product: 'Corporate access',
    icon: LockKeyhole,
    color: '#0F6CBD',
    accent: '#0F6CBD',
    identifierLabel: 'Email or username',
    identifierPlaceholder: 'name@company.com',
    passwordLabel: 'Password',
    cta: 'Verify identity',
    note: 'Opened from a text message link',
    detail: [],
  },
};

/** Landing-page slug (resolved by the backend) → visual skin. */
const PAGE_SKINS: Record<string, Skin> = {
  cisco_vpn: 'it',
  supplier_portal: 'finance',
  hr_portal: 'hr',
  teams_invite: 'executive',
  microsoft_login: 'microsoft',
  general_login: 'generic',
};

function resolveSkin(category?: string | null): Skin {
  const value = (category ?? '').trim().toLowerCase();
  if (value.startsWith('it')) return 'it';
  if (value.startsWith('financ')) return 'finance';
  if (value === 'hr' || value.startsWith('hr ') || value.startsWith('human')) return 'hr';
  if (value.startsWith('exec')) return 'executive';
  return 'generic';
}

export function SmsLureLandingPage() {
  const { trackingUuid = '' } = useParams<{ trackingUuid: string }>();
  const [searchParams] = useSearchParams();
  const pageParam = searchParams.get('page');
  const [company, setCompany] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const [contextPage, setContextPage] = useState<string | null>(null);
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    trackingApi
      .context(trackingUuid)
      .then((context) => {
        if (!active) return;
        const payload = context as {
          company_name?: string;
          template_category?: string | null;
          landing_page?: string | null;
        };
        if (payload.company_name) setCompany(payload.company_name);
        if (payload.landing_page) setContextPage(payload.landing_page);
        if (payload.template_category) setCategory(payload.template_category);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [trackingUuid]);

  const skin = useMemo(() => {
    const slug = (pageParam || contextPage || '').trim().toLowerCase();
    if (slug && PAGE_SKINS[slug]) return PAGE_SKINS[slug];
    return resolveSkin(category);
  }, [pageParam, contextPage, category]);
  const config = SKINS[skin];
  const Icon = config.icon;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if (!identifier.trim() || !password.trim()) {
      setError('أكمل جميع الحقول للمتابعة.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await trackingApi.submitSms(
        trackingUuid,
        identifier.trim(),
        password,
      );
      window.location.assign(result.redirect_url || `/training/${trackingUuid}?channel=sms`);
    } catch {
      setSubmitting(false);
      setError('تعذّر التحقق من البيانات. أعد المحاولة.');
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100vh',
        px: 2,
        py: 4,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        bgcolor: skin === 'executive' ? '#1F1F2E' : '#0A0F1C',
        background:
          skin === 'finance'
            ? 'linear-gradient(180deg, #0B2A20 0%, #07130F 100%)'
            : skin === 'executive'
              ? 'linear-gradient(180deg, #2B2B45 0%, #15151F 100%)'
              : skin === 'hr'
                ? 'linear-gradient(180deg, #241C36 0%, #100C18 100%)'
                : 'linear-gradient(180deg, #0D2135 0%, #05080F 100%)',
      }}
    >
      <Box
        sx={{
          width: '100%',
          maxWidth: 430,
          bgcolor: '#ffffff',
          borderRadius: 2,
          overflow: 'hidden',
          boxShadow: '0 30px 70px rgba(0,0,0,0.55)',
        }}
      >
        <Box sx={{ bgcolor: config.color, color: '#fff', px: 3, py: 2.25 }}>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <Box
              sx={{
                width: 38,
                height: 38,
                borderRadius: 1.5,
                bgcolor: 'rgba(255,255,255,0.12)',
                display: 'grid',
                placeItems: 'center',
              }}
            >
              <Icon size={22} />
            </Box>
            <Box>
              <Typography sx={{ fontWeight: 800, fontSize: '1.02rem', lineHeight: 1.2 }}>
                {config.header}
              </Typography>
              <Typography sx={{ fontSize: '0.72rem', opacity: 0.78 }}>
                {config.product}
              </Typography>
            </Box>
          </Stack>
        </Box>

        <Box sx={{ p: 3 }}>
          <Typography sx={{ fontSize: '0.82rem', color: 'text.secondary', mb: 2 }}>
            {company ? `${company} · ` : ''}
            {config.note}
          </Typography>

          {config.detail.length > 0 ? (
            <Box
              sx={{
                mb: 2.5,
                p: 1.5,
                borderRadius: 1.5,
                bgcolor: '#F6F8FB',
                border: '1px solid #E3E8EF',
              }}
            >
              <Stack spacing={0.75}>
                {config.detail.map((row) => (
                  <Stack key={row.label} direction="row" justifyContent="space-between">
                    <Typography sx={{ fontSize: '0.74rem', color: '#667085' }}>
                      {row.label}
                    </Typography>
                    <Typography sx={{ fontSize: '0.74rem', fontWeight: 700, color: '#101828' }}>
                      {row.value}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>
          ) : null}

          <form onSubmit={handleSubmit} noValidate>
            <Stack spacing={2}>
              <TextField
                label={config.identifierLabel}
                placeholder={config.identifierPlaceholder}
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                autoComplete="username"
                fullWidth
                size="small"
              />
              <TextField
                label={config.passwordLabel}
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                fullWidth
                size="small"
              />
              {error ? <Alert severity="error">{error}</Alert> : null}
              <Button
                type="submit"
                variant="contained"
                disabled={submitting}
                startIcon={
                  submitting ? (
                    <CircularProgress size={16} color="inherit" />
                  ) : (
                    <Lock size={16} />
                  )
                }
                sx={{
                  py: 1.1,
                  fontWeight: 700,
                  bgcolor: config.accent,
                  color: skin === 'it' ? '#04202F' : '#fff',
                  '&:hover': { bgcolor: config.accent, filter: 'brightness(0.92)' },
                }}
              >
                {submitting ? 'جارٍ المتابعة…' : config.cta}
              </Button>
            </Stack>
          </form>

          <Divider sx={{ my: 2 }} />
          <Stack direction="row" spacing={0.75} alignItems="center">
            <CalendarClock size={14} color="#98A2B3" />
            <Typography sx={{ fontSize: '0.68rem', color: 'text.disabled' }}>
              TLS 1.3 · single sign-on enforced · do not share credentials
            </Typography>
          </Stack>
        </Box>
      </Box>
    </Box>
  );
}

export default SmsLureLandingPage;
