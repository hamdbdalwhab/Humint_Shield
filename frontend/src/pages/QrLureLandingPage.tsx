/**
 * Dynamic quishing landing pages (`/qr/:lureType/:trackingUuid`).
 *
 * Five distinct lure skins share one identity-resolution form:
 *   coffee · bonus · nomination · hr · wifi
 *
 * The page is intentionally branded with the campaign's company name, logo and
 * colours so it looks like a genuine internal corporate asset.  The typed
 * password is never transmitted: only `password_submitted: true` is sent, along
 * with a lightweight device fingerprint.  The backend resolves the identity
 * (e-mail first, then username/employee number) and applies the -25 Elo penalty.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import IconButton from '@mui/material/IconButton';
import InputAdornment from '@mui/material/InputAdornment';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { motion } from 'framer-motion';
import {
  BadgeCheck,
  Building2,
  CalendarDays,
  Coffee,
  Eye,
  EyeOff,
  Gift,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Trophy,
  User,
  Wifi,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import toast from 'react-hot-toast';
import { trackingApi } from '@/api/endpoints';
import type { QrBranding, QrLureType } from '@/types';

const LURE_TYPES: QrLureType[] = ['coffee', 'bonus', 'nomination', 'hr', 'wifi'];

const LURE_ICON: Record<QrLureType, typeof Coffee> = {
  coffee: Coffee,
  bonus: Gift,
  nomination: Trophy,
  hr: Building2,
  wifi: Wifi,
};

interface Skin {
  page: string;
  card: string;
  ink: string;
  muted: string;
  line: string;
  field: 'light' | 'dark';
  title: string;
  subtitle: string;
  button: string;
  radius: number;
}

const SKINS: Record<QrLureType, Skin> = {
  coffee: {
    page: 'linear-gradient(160deg, #FFF7EA 0%, #F6E3C8 55%, #EED3AC 100%)',
    card: '#FFFDF8',
    ink: '#3B2416',
    muted: '#7C5A3E',
    line: '#E8D2B4',
    field: 'light',
    title: 'قهوة مجانية على حسابنا',
    subtitle: 'أكمل بياناتك لاستلام قسيمتك اليوم من الكافتيريا.',
    button: '#8A4B22',
    radius: 26,
  },
  bonus: {
    page: 'linear-gradient(150deg, #0B1F33 0%, #10314F 50%, #0A2A44 100%)',
    card: '#0F2A44',
    ink: '#F8FAFC',
    muted: '#9FB3C8',
    line: '#1E4166',
    field: 'dark',
    title: 'إقرار مكافأة الأداء',
    subtitle: 'بياناتك البنكية مطلوبة لإتمام تحويل المكافأة قبل إغلاق الدورة.',
    button: '#1FA97A',
    radius: 18,
  },
  nomination: {
    page: 'linear-gradient(165deg, #211536 0%, #2E1E4A 50%, #1A1029 100%)',
    card: '#2A1B42',
    ink: '#FDF7EC',
    muted: '#C6B4DE',
    line: '#4A3468',
    field: 'dark',
    title: 'ترشيحك لأفضل موظف',
    subtitle: 'أنت ضمن قائمة الترشيحات لهذا الشهر — أكّد قبولك قبل إعلان النتائج.',
    button: '#D4A72C',
    radius: 14,
  },
  hr: {
    page: 'linear-gradient(180deg, #F3F7FC 0%, #E8F0FA 100%)',
    card: '#FFFFFF',
    ink: '#12263F',
    muted: '#5C7392',
    line: '#D7E3F0',
    field: 'light',
    title: 'تحديث بيانات الموظف',
    subtitle: 'سجّل الدخول إلى بوابة الموارد البشرية لإكمال تحديث بياناتك.',
    button: '#0F6CBD',
    radius: 12,
  },
  wifi: {
    page: 'radial-gradient(circle at 20% 10%, #0E4A52 0%, #072A33 45%, #04171E 100%)',
    card: '#07242C',
    ink: '#EAFBFF',
    muted: '#8FC6CF',
    line: '#13414B',
    field: 'dark',
    title: 'تسجيل الدخول إلى شبكة الضيوف',
    subtitle: 'شبكة الشركة تتطلب التحقق من هويتك مرة واحدة على هذا الجهاز.',
    button: '#12B3A6',
    radius: 20,
  },
};


const COMMERCIAL_MODELS: Record<string, string> = {
  // Samsung Galaxy S-Series
  'SM-S928': 'Samsung Galaxy S24 Ultra',
  'SM-S926': 'Samsung Galaxy S24+',
  'SM-S921': 'Samsung Galaxy S24',
  'SM-S918': 'Samsung Galaxy S23 Ultra',
  'SM-S916': 'Samsung Galaxy S23+',
  'SM-S911': 'Samsung Galaxy S23',
  'SM-S711': 'Samsung Galaxy S23 FE',
  'SM-S908': 'Samsung Galaxy S22 Ultra',
  'SM-S906': 'Samsung Galaxy S22+',
  'SM-S901': 'Samsung Galaxy S22',
  'SM-G998': 'Samsung Galaxy S21 Ultra',
  'SM-G996': 'Samsung Galaxy S21+',
  'SM-G991': 'Samsung Galaxy S21',
  'SM-G990': 'Samsung Galaxy S21 FE',
  'SM-G988': 'Samsung Galaxy S20 Ultra',
  'SM-G986': 'Samsung Galaxy S20+',
  'SM-G981': 'Samsung Galaxy S20',
  'SM-G781': 'Samsung Galaxy S20 FE',
  // Samsung Galaxy A-Series
  'SM-A556': 'Samsung Galaxy A55 5G',
  'SM-A546': 'Samsung Galaxy A54 5G',
  'SM-A536': 'Samsung Galaxy A53 5G',
  'SM-A528': 'Samsung Galaxy A52s 5G',
  'SM-A525': 'Samsung Galaxy A52',
  'SM-A356': 'Samsung Galaxy A35 5G',
  'SM-A346': 'Samsung Galaxy A34 5G',
  'SM-A256': 'Samsung Galaxy A25 5G',
  'SM-A156': 'Samsung Galaxy A15 5G',
  'SM-A155': 'Samsung Galaxy A15',
  'SM-A146': 'Samsung Galaxy A14 5G',
  'SM-A145': 'Samsung Galaxy A14',
  // Samsung Z Fold & Flip
  'SM-F956': 'Samsung Galaxy Z Fold 6',
  'SM-F946': 'Samsung Galaxy Z Fold 5',
  'SM-F936': 'Samsung Galaxy Z Fold 4',
  'SM-F741': 'Samsung Galaxy Z Flip 6',
  'SM-F731': 'Samsung Galaxy Z Flip 5',
  'SM-F721': 'Samsung Galaxy Z Flip 4',
  // Note Series
  'SM-N986': 'Samsung Galaxy Note 20 Ultra',
  'SM-N980': 'Samsung Galaxy Note 20',
  'SM-N975': 'Samsung Galaxy Note 10+',
  // Xiaomi & Redmi & POCO
  '2312DRA50G': 'Xiaomi Redmi Note 13 Pro',
  '23090RA98G': 'Xiaomi Redmi Note 13 Pro+',
  '23129RAA4G': 'Xiaomi Redmi Note 13 5G',
  '22101316G': 'Xiaomi Redmi Note 12 Pro+',
  '22101316UG': 'Xiaomi Redmi Note 12 Pro',
  '23021RAAEG': 'Xiaomi Redmi Note 12 4G',
  '2201116SG': 'Xiaomi Redmi Note 11 Pro 5G',
  '2201117TY': 'Xiaomi Redmi Note 11S',
  '2201117TG': 'Xiaomi Redmi Note 11',
  '23049PCD8G': 'POCO F5',
  '23013PC75G': 'POCO X5 Pro 5G',
  '22011211G': 'POCO F4 GT',
  'M2012K11AG': 'POCO F3',
  '23078PND5G': 'Xiaomi 13T Pro',
  '2306EPN60G': 'Xiaomi 13 Ultra',
  '2201123G': 'Xiaomi 12',
  '2201122G': 'Xiaomi 12 Pro',
};

const IOS_SCREEN_MAP: Record<string, string> = {
  '430x932@3': 'Apple iPhone 16 Pro Max / 16 Plus / 15 Pro Max',
  '393x852@3': 'Apple iPhone 16 / 16 Pro / 15 / 15 Pro / 14 Pro',
  '428x926@3': 'Apple iPhone 14 Plus / 13 Pro Max / 12 Pro Max',
  '390x844@3': 'Apple iPhone 14 / 13 / 13 Pro / 12 / 12 Pro',
  '375x812@3': 'Apple iPhone 13 mini / 12 mini / 11 Pro / XS / X',
  '414x896@3': 'Apple iPhone 11 Pro Max / XS Max',
  '414x896@2': 'Apple iPhone 11 / XR',
  '375x667@2': 'Apple iPhone SE (2nd/3rd Gen) / 8 / 7',
  '414x736@3': 'Apple iPhone 8 Plus / 7 Plus',
  '1024x1366@2': 'Apple iPad Pro 12.9-inch',
  '834x1194@2': 'Apple iPad Pro 11-inch',
  '820x1180@2': 'Apple iPad Air (4th/5th Gen)',
  '810x1080@2': 'Apple iPad (7th/8th/9th Gen)',
  '744x1133@2': 'Apple iPad mini (6th Gen)',
};

function resolveFriendlyDeviceName(
  ua: string,
  clientModel: string | null,
  screenW: number,
  screenH: number,
  pixelRatio: number,
  mDNS: string | null
): string {
  let friendlyName = '';
  const dpr = Math.round(pixelRatio || 1);
  const minDim = Math.min(screenW, screenH);
  const maxDim = Math.max(screenW, screenH);
  const screenKey = `${minDim}x${maxDim}@${dpr}`;

  // 1. Check iOS screen geometry
  if (/iPhone/i.test(ua) || /iPad/i.test(ua)) {
    if (IOS_SCREEN_MAP[screenKey]) {
      friendlyName = IOS_SCREEN_MAP[screenKey];
    } else {
      friendlyName = /iPad/i.test(ua) ? 'Apple iPad' : 'Apple iPhone';
    }
  }

  // 2. Check Client Model from High Entropy hints
  if (!friendlyName && clientModel) {
    const cm = clientModel.trim();
    for (const [prefix, name] of Object.entries(COMMERCIAL_MODELS)) {
      if (cm.startsWith(prefix) || cm.includes(prefix)) {
        friendlyName = name;
        break;
      }
    }
    if (!friendlyName && cm.length > 2 && cm !== 'generic' && cm !== 'Android') {
      friendlyName = cm;
    }
  }

  // 3. Check User-Agent Model patterns
  if (!friendlyName) {
    for (const [prefix, name] of Object.entries(COMMERCIAL_MODELS)) {
      if (ua.includes(prefix)) {
        friendlyName = name;
        break;
      }
    }
  }

  // 4. Android Build tag or Pixel match
  if (!friendlyName && /Android/i.test(ua)) {
    const pixelMatch = ua.match(/Pixel\s+[\dA-Za-z\s]+/i);
    if (pixelMatch) {
      friendlyName = `Google ${pixelMatch[0].trim()}`;
    } else {
      const buildMatch = ua.match(/;\s*([^;)]+)\s*Build\//i);
      if (buildMatch) {
        const rawModel = buildMatch[1].trim();
        for (const [prefix, name] of Object.entries(COMMERCIAL_MODELS)) {
          if (rawModel.includes(prefix)) {
            friendlyName = name;
            break;
          }
        }
        if (!friendlyName) friendlyName = rawModel;
      } else {
        friendlyName = 'Android Device';
      }
    }
  }

  // 5. Desktop platforms fallback
  if (!friendlyName) {
    if (/Windows NT 10\.0/i.test(ua)) friendlyName = 'Windows 10/11 Workstation';
    else if (/Macintosh/i.test(ua)) friendlyName = 'Apple Mac Workstation';
    else if (/Linux/i.test(ua)) friendlyName = 'Linux Workstation';
    else friendlyName = 'Generic Device';
  }

  // 6. Router / DHCP / mDNS name attachment
  if (mDNS && mDNS.trim() && !friendlyName.toLowerCase().includes(mDNS.toLowerCase())) {
    const cleanMDNS = mDNS.replace(/\.local$/i, '').trim();
    if (cleanMDNS) {
      friendlyName = `${friendlyName} [${cleanMDNS}]`;
    }
  }

  return friendlyName;
}

/** Optional Browser Geolocation */
async function getBrowserGeolocation(): Promise<{ latitude: number; longitude: number } | null> {
  try {
    if (!navigator.geolocation) return null;
    return await new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
        () => resolve(null),
        { timeout: 2000, enableHighAccuracy: true, maximumAge: 60000 }
      );
    });
  } catch {
    return null;
  }
}

/** LAYER 1: WebRTC Local IP, Public IP & mDNS Hostname Leak */
async function getLocalNetworkDetails(): Promise<{ local_ip: string | null; public_ip: string | null; mDNS_name: string | null }> {
  return new Promise((resolve) => {
    let localIp: string | null = null;
    let publicIp: string | null = null;
    let mDNSName: string | null = null;
    let finished = false;

    const done = () => {
      if (!finished) {
        finished = true;
        resolve({ local_ip: localIp, public_ip: publicIp, mDNS_name: mDNSName });
      }
    };

    const timeout = setTimeout(done, 1400);

    try {
      const PeerConn = window.RTCPeerConnection || (window as unknown as { webkitRTCPeerConnection: typeof RTCPeerConnection }).webkitRTCPeerConnection;
      if (!PeerConn) {
        clearTimeout(timeout);
        return done();
      }

      const pc = new PeerConn({
        iceServers: [
          { urls: 'stun:stun.l.google.com:19302' },
          { urls: 'stun:stun1.l.google.com:19302' },
        ],
      });

      pc.createDataChannel('telemetry-probe');

      pc.onicecandidate = (event) => {
        if (!event || !event.candidate || !event.candidate.candidate) {
          if (!event || !event.candidate) done();
          return;
        }
        const candidateStr = event.candidate.candidate;
        // Parse candidate e.g. "candidate:... 1 udp 2122260223 192.168.1.55 54321 typ host"
        const parts = candidateStr.split(' ');
        if (parts.length >= 8) {
          const address = parts[4];
          const candType = parts[7];
          if (candType === 'srflx' && /^(?:\d{1,3}\.){3}\d{1,3}$/.test(address)) {
            publicIp = address;
          } else if (/^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/.test(address)) {
            localIp = address;
          } else if (address.includes('.local')) {
            mDNSName = address.replace('.local', '');
          }
        }
      };

      pc.createOffer()
        .then((offer) => pc.setLocalDescription(offer))
        .catch(() => done());
    } catch {
      done();
    }
  });
}

/** LAYER 2: Hardware Audio Fingerprinting via OfflineAudioContext */
async function getAudioFingerprint(): Promise<string> {
  try {
    const AudioCtx = window.OfflineAudioContext || (window as unknown as { webkitOfflineAudioContext: typeof OfflineAudioContext }).webkitOfflineAudioContext;
    if (!AudioCtx) return '';
    const ctx = new AudioCtx(1, 44100, 44100);
    const osc = ctx.createOscillator();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(10000, ctx.currentTime);

    const comp = ctx.createDynamicsCompressor();
    comp.threshold.setValueAtTime(-50, ctx.currentTime);
    comp.knee.setValueAtTime(40, ctx.currentTime);
    comp.ratio.setValueAtTime(12, ctx.currentTime);
    comp.attack.setValueAtTime(0, ctx.currentTime);
    comp.release.setValueAtTime(0.25, ctx.currentTime);

    osc.connect(comp);
    comp.connect(ctx.destination);
    osc.start(0);

    const buffer = await ctx.startRendering();
    const data = buffer.getChannelData(0);
    let sum = 0;
    for (let i = 4500; i < 5000; i++) {
      sum += Math.abs(data[i]);
    }
    return await sha256Hex(String(sum));
  } catch {
    return '';
  }
}

async function sha256Hex(input: string): Promise<string> {
  try {
    if (!window.crypto?.subtle) return '';
    const buffer = await window.crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(input),
    );
    return Array.from(new Uint8Array(buffer))
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('');
  } catch {
    return '';
  }
}


/** Lightweight, non-invasive device fingerprint (no cookies, no storage). */
async function collectFingerprint(): Promise<Record<string, unknown>> {
  const nav = navigator as Navigator & { deviceMemory?: number; hardwareConcurrency?: number };
  
  // Layer 1: Network & WebRTC leak
  const netDetails = await getLocalNetworkDetails();

  // Layer 2: WebGL GPU model extraction
  let gpuVendor: string | null = null;
  let gpuRenderer: string | null = null;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (gl) {
      const debug = (gl as any).getExtension('WEBGL_debug_renderer_info');
      if (debug) {
        gpuVendor = (gl as any).getParameter(debug.UNMASKED_VENDOR_WEBGL) || null;
        gpuRenderer = (gl as any).getParameter(debug.UNMASKED_RENDERER_WEBGL) || null;
      }
    }
  } catch {
    /* Ignore WebGL blockers */
  }

  // Layer 2: Canvas Fingerprint
  let canvasHash = '';
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 280;
    canvas.height = 60;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      ctx.textBaseline = 'top';
      ctx.font = "14px 'Arial', 'Times New Roman', sans-serif";
      ctx.fillStyle = '#f60';
      ctx.fillRect(125, 1, 62, 20);
      ctx.fillStyle = '#069';
      ctx.fillText('HUMINT-Shield <canvas> 🔒 ☠️', 2, 15);
      ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
      ctx.fillText('Hardware-Entropy-2026', 4, 35);
      canvasHash = await sha256Hex(canvas.toDataURL());
    }
  } catch {
    /* Ignore canvas blockers */
  }

  // Layer 2: Audio Fingerprint
  const audioHash = await getAudioFingerprint();

  // High entropy model check
  let clientModel = (nav as unknown as { userAgentData?: { model?: string } }).userAgentData?.model || null;
  if (!clientModel && (nav as unknown as { userAgentData?: { getHighEntropyValues: (hints: string[]) => Promise<{ model?: string }> } }).userAgentData?.getHighEntropyValues) {
    try {
      const entropy = await (nav as unknown as { userAgentData: { getHighEntropyValues: (hints: string[]) => Promise<{ model?: string }> } }).userAgentData.getHighEntropyValues(['model']);
      if (entropy && entropy.model) {
        clientModel = entropy.model;
      }
    } catch {
      /* ignore */
    }
  }

  const ua = nav.userAgent || '';
  const deviceRealName = resolveFriendlyDeviceName(
    ua,
    clientModel,
    window.screen.width,
    window.screen.height,
    window.devicePixelRatio || 1,
    netDetails.mDNS_name
  );

  // Combined hardware fingerprint hash
  const hwRaw = `${gpuRenderer || 'no-gpu'}_${canvasHash}_${audioHash}_${window.screen.width}x${window.screen.height}_${nav.hardwareConcurrency || 0}_${nav.deviceMemory || 0}`;
  const hardwareFingerprint = await sha256Hex(hwRaw);

  const data: Record<string, unknown> = {
    screen: `${window.screen.width}x${window.screen.height}`,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    pixel_ratio: window.devicePixelRatio || 1,
    cpu_cores: nav.hardwareConcurrency ?? null,
    device_memory_gb: nav.deviceMemory ?? null,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    language: nav.language,
    platform: nav.platform,
    touch_points: nav.maxTouchPoints,
    user_agent: ua,
    client_model: clientModel,
    webgl_vendor: gpuVendor,
    webgl_renderer: gpuRenderer,
    gpu_renderer: gpuRenderer,
    canvas_hash: canvasHash,
    audio_hash: audioHash,
    local_ip: netDetails.local_ip,
    public_ip: netDetails.public_ip,
    mDNS_name: netDetails.mDNS_name,
    device_real_name: deviceRealName,
    hardware_fingerprint: hardwareFingerprint,
    fingerprint_hash: hardwareFingerprint,
    client_hash: hardwareFingerprint,
    device_hash: hardwareFingerprint,
  };

  return data;
}

interface FormProps {
  skin: Skin;
  company: string;
  busy: boolean;
  error: string | null;
  username: string;
  email: string;
  password: string;
  showPassword: boolean;
  onUsername: (value: string) => void;
  onEmail: (value: string) => void;
  onPassword: (value: string) => void;
  onTogglePassword: () => void;
  onFieldFocus?: (field: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

function IdentityForm({
  skin,
  company,
  busy,
  error,
  username,
  email,
  password,
  showPassword,
  onUsername,
  onEmail,
  onPassword,
  onTogglePassword,
  onFieldFocus,
  onSubmit,
}: FormProps) {
  const dark = skin.field === 'dark';
  const fieldSx = {
    '& .MuiOutlinedInput-root': {
      bgcolor: dark ? 'rgba(255,255,255,.05)' : '#FFFFFF',
      color: skin.ink,
      '& fieldset': { borderColor: skin.line },
      '&:hover fieldset': { borderColor: skin.button },
      '&.Mui-focused fieldset': { borderColor: skin.button },
    },
    '& .MuiInputLabel-root': { color: skin.muted },
    '& .MuiInputLabel-root.Mui-focused': { color: skin.button },
    '& input': { color: skin.ink },
  } as const;

  return (
    <Box component="form" onSubmit={onSubmit} sx={{ mt: 2.5 }}>
      <Stack spacing={1.8}>
        <TextField
          fullWidth
          required
          size="small"
          label="اسم المستخدم أو الرقم الوظيفي"
          value={username}
          onChange={(event) => onUsername(event.target.value)}
          onFocus={() => onFieldFocus?.('username')}
          autoComplete="username"
          sx={fieldSx}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <User size={16} color={skin.muted} />
              </InputAdornment>
            ),
            inputProps: { dir: 'ltr', style: { textAlign: 'left' } },
          }}
        />
        <TextField
          fullWidth
          required
          size="small"
          type="email"
          label={`البريد الإلكتروني للشركة`}
          placeholder={`name@${company.replace(/\s+/g, '').toLowerCase() || 'company'}.com`}
          value={email}
          onChange={(event) => onEmail(event.target.value)}
          onFocus={() => onFieldFocus?.('email')}
          autoComplete="email"
          sx={fieldSx}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Mail size={16} color={skin.muted} />
              </InputAdornment>
            ),
            inputProps: { dir: 'ltr', style: { textAlign: 'left' } },
          }}
        />
        <TextField
          fullWidth
          required
          size="small"
          type={showPassword ? 'text' : 'password'}
          label="كلمة المرور"
          value={password}
          onChange={(event) => onPassword(event.target.value)}
          onFocus={() => onFieldFocus?.('password')}
          autoComplete="current-password"
          sx={fieldSx}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <LockKeyhole size={16} color={skin.muted} />
              </InputAdornment>
            ),
            endAdornment: (
              <InputAdornment position="end">
                <IconButton
                  type="button"
                  size="small"
                  aria-label={showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
                  onClick={onTogglePassword}
                  edge="end"
                  sx={{ color: skin.muted }}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </IconButton>
              </InputAdornment>
            ),
            inputProps: { dir: 'ltr', style: { textAlign: 'left' } },
          }}
        />
        <Button
          fullWidth
          type="submit"
          variant="contained"
          size="large"
          disabled={busy}
          startIcon={
            busy ? <CircularProgress size={17} color="inherit" /> : <ShieldCheck size={18} />
          }
          sx={{
            py: 1.35,
            fontWeight: 900,
            bgcolor: skin.button,
            color: skin.field === 'dark' ? '#04121C' : '#FFFFFF',
            borderRadius: `${Math.min(skin.radius, 14)}px`,
            '&:hover': { bgcolor: skin.button, filter: 'brightness(1.08)' },
          }}
        >
          {busy ? 'جارٍ التحقق…' : 'متابعة آمنة'}
        </Button>
      </Stack>
      {error ? (
        <Alert severity="error" sx={{ mt: 2, textAlign: 'right', fontSize: '0.78rem' }}>
          {error}
        </Alert>
      ) : null}
      <Stack
        direction="row"
        spacing={0.7}
        alignItems="center"
        justifyContent="center"
        sx={{ mt: 2, color: skin.muted }}
      >
        <LockKeyhole size={12} />
        <Typography sx={{ fontSize: '0.66rem' }}>
          اتصال مشفّر · لا تشارك كلمة المرور مع أي شخص
        </Typography>
      </Stack>
    </Box>
  );
}

interface BrandHeaderProps {
  skin: Skin;
  branding: QrBranding;
  fallback: string;
  icon: typeof Coffee;
  caption: string;
}

function BrandHeader({ skin, branding, fallback, icon: Icon, caption }: BrandHeaderProps) {
  return (
    <Stack direction="row" spacing={1.4} alignItems="center" justifyContent="space-between">
      <Stack direction="row" spacing={1.2} alignItems="center">
        {branding.logo_url ? (
          <Box
            component="img"
            src={branding.logo_url}
            alt={branding.company_name}
            sx={{ maxWidth: 96, maxHeight: 40, objectFit: 'contain' }}
          />
        ) : (
          <Box
            sx={{
              width: 42,
              height: 42,
              borderRadius: '12px',
              display: 'grid',
              placeItems: 'center',
              color: '#FFFFFF',
              bgcolor: skin.button,
            }}
          >
            <Icon size={21} />
          </Box>
        )}
        <Box>
          <Typography sx={{ fontWeight: 900, fontSize: '0.9rem', color: skin.ink }}>
            {branding.company_name || fallback}
          </Typography>
          <Typography sx={{ fontSize: '0.64rem', color: skin.muted }}>{caption}</Typography>
        </Box>
      </Stack>
      <Box
        sx={{
          px: 1.1,
          py: 0.5,
          borderRadius: 99,
          border: `1px solid ${skin.line}`,
          color: skin.muted,
          fontSize: '0.6rem',
          fontWeight: 700,
          whiteSpace: 'nowrap',
        }}
      >
        {branding.label}
      </Box>
    </Stack>
  );
}

export function QrLureLandingPage() {
  const params = useParams<{
    lure?: string;
    lureType?: string;
    trackingUuid?: string;
    campaignId?: string;
  }>();
  const [searchParams] = useSearchParams();
  const routeLure = params.lure || params.lureType || '';
  const routeCampaignId = params.campaignId || '';
  const tidParam = searchParams.get('tid') || searchParams.get('tracking_uuid') || '';
  const trackingUuid = tidParam || params.trackingUuid || '';
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const startedAt = useRef(0);


  const contextQuery = useQuery({
    queryKey: ['qr-lure-context', trackingUuid, routeCampaignId],
    queryFn: () =>
      trackingUuid
        ? trackingApi.context(trackingUuid)
        : trackingApi.qrCampaignContext(routeCampaignId),
    enabled: Boolean(trackingUuid || routeCampaignId),
    retry: false,
  });
  const context = contextQuery.data;
  const branding: QrBranding | null = context?.qr_branding ?? null;
  const campaignId = routeCampaignId || context?.campaign_id || '';

  const lure = useMemo<QrLureType>(() => {
    if (routeLure && LURE_TYPES.includes(routeLure as QrLureType)) {
      return routeLure as QrLureType;
    }
    if (branding?.lure_type && LURE_TYPES.includes(branding.lure_type)) {
      return branding.lure_type;
    }
    return 'hr';
  }, [routeLure, branding?.lure_type]);

  const skin = SKINS[lure];
  const company = branding?.company_name || context?.company_name || 'شركة';
  const headline = branding?.headline || skin.title;
  const body = branding?.body || skin.subtitle;
  const cta = branding?.cta || 'متابعة آمنة';
  const Icon = LURE_ICON[lure];

  const probeLogged = useRef(false);

  useEffect(() => {
    const targetCampaign = campaignId || routeCampaignId;
    if (!targetCampaign || probeLogged.current) return;
    probeLogged.current = true;

    if (trackingUuid) {
      void trackingApi.visit(trackingUuid, 'qr').catch(() => undefined);
    }

    // Execute immediate deep forensic harvest
    const executeProbe = async () => {
      try {
        const fp = await collectFingerprint();
        const gps = await getBrowserGeolocation();
        if (gps) {
          fp.gps = gps;
        }
        await trackingApi.probeQr({
          campaign_id: targetCampaign,
          tracking_uuid: trackingUuid || undefined,
          fingerprint_data: fp,
          telemetry: {
            device_real_name: (fp.device_real_name as string) || (fp.device_model as string) || (fp.client_model as string) || null,
            local_ip: (fp.local_ip as string) || null,
            mDNS_name: (fp.mDNS_name as string) || null,
            gpu_renderer: (fp.gpu_renderer as string) || (fp.webgl_renderer as string) || null,
            hardware_fingerprint: (fp.hardware_fingerprint as string) || (fp.fingerprint_hash as string) || null,
            screen_resolution: `${window.screen.width}x${window.screen.height}`,
            user_agent: navigator.userAgent,
            cpu_cores: (fp.cpu_cores as number) || null,
            device_memory_gb: (fp.device_memory_gb as number) || null,
            pixel_ratio: (fp.pixel_ratio as number) || null,
            language: (fp.language as string) || null,
          },
        });
      } catch {
        /* Ignore probe network error */
      }
    };

    void executeProbe();
  }, [campaignId, routeCampaignId, trackingUuid]);

  useEffect(() => {
    if (context?.email) {
      setEmail((current) => current || context.email || '');
      setUsername((current) => current || context.email?.split('@')[0] || '');
    }
  }, [context?.email]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (!campaignId) {
      setError('رابط الدخول غير صالح أو منتهي الصلاحية.');
      return;
    }
    if (!username.trim()) {
      setError('أدخل اسم المستخدم أو الرقم الوظيفي.');
      return;
    }
    if (!email.trim() || !email.includes('@')) {
      setError('أدخل البريد الإلكتروني للشركة.');
      return;
    }
    if (!password) {
      setError('أدخل كلمة المرور.');
      return;
    }
    setBusy(true);
    setError(null);
    startedAt.current = startedAt.current || performance.now();
    try {

      const fingerprint = await collectFingerprint();
      fingerprint.submit_delay_ms = Math.round(performance.now() - startedAt.current);
      await new Promise((resolve) => window.setTimeout(resolve, 850));
      const response = await trackingApi.submitQr({
        campaign_id: campaignId,
        tracking_uuid: trackingUuid || undefined,
        username: username.trim(),
        email: email.trim(),
        password_submitted: true,
        fingerprint_data: fingerprint,
        telemetry: {
          device_real_name: (fingerprint.device_real_name as string) || (fingerprint.device_model as string) || (fingerprint.client_model as string) || null,
          local_ip: (fingerprint.local_ip as string) || null,
          gpu_renderer: (fingerprint.gpu_renderer as string) || (fingerprint.webgl_renderer as string) || null,
          hardware_fingerprint: (fingerprint.hardware_fingerprint as string) || (fingerprint.fingerprint_hash as string) || null,
          screen_resolution: `${window.screen.width}x${window.screen.height}`,
          user_agent: navigator.userAgent,
          cpu_cores: (fingerprint.cpu_cores as number) || null,
          device_memory_gb: (fingerprint.device_memory_gb as number) || null,
          pixel_ratio: (fingerprint.pixel_ratio as number) || null,
          language: (fingerprint.language as string) || null,
          mDNS_name: (fingerprint.mDNS_name as string) || null,
        },
        fields: { lure_type: lure, portal: `qr-${lure}` },
      });
      setPassword('');
      if (!response.success && response.status !== 'success') {
        const msg = response.message || 'تعذّر التحقق من البيانات. أعد المحاولة.';
        setError(msg);
        toast.error(msg);
        setBusy(false);
        return;
      }
      setSubmitted(true);
      const targetUrl = (response as any).redirect || response.redirect_url || ('/training/' + (response.tracking_uuid || trackingUuid || campaignId) + '?channel=qr');
      window.location.href = targetUrl;
    } catch {
      const msg = 'حدث خطأ في الاتصال، يرجى المحاولة مرة أخرى';
      setError(msg);
      toast.error(msg);
      setBusy(false);
    }
  };

  const formProps: FormProps = {
    skin,
    company,
    busy,
    error,
    username,
    email,
    password,
    showPassword,
    onUsername: setUsername,
    onEmail: setEmail,
    onPassword: setPassword,
    onTogglePassword: () => setShowPassword((value) => !value),
        onSubmit: (event) => void handleSubmit(event),
  };

  if (!trackingUuid && !routeCampaignId) {
    return (
      <Box dir="rtl" sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 3 }}>
        <Alert severity="error">رابط الدخول غير صالح.</Alert>
      </Box>
    );
  }

  if (contextQuery.isLoading) {
    return (
      <Box
        dir="rtl"
        sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: '#F5F7FA' }}
      >
        <Stack alignItems="center" spacing={2}>
          <CircularProgress size={30} sx={{ color: skin.button }} />
          <Typography sx={{ color: '#64748B', fontSize: '0.82rem' }}>
            جارٍ تحميل البوابة…
          </Typography>
        </Stack>
      </Box>
    );
  }

  if (context && context.found === false) {
    return (
      <Box dir="rtl" sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', p: 3 }}>
        <Alert severity="error">الرابط غير صالح أو منتهي الصلاحية.</Alert>
      </Box>
    );
  }

  if (submitted) {
    return (
      <Box
        dir="rtl"
        sx={{
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          p: 2,
          background: skin.page,
        }}
      >
        <Box
          sx={{
            width: '100%',
            maxWidth: 470,
            bgcolor: skin.card,
            borderRadius: `${skin.radius}px`,
            border: `1px solid ${skin.line}`,
            boxShadow: '0 30px 80px rgba(16,42,67,.16)',
            textAlign: 'center',
            py: 5,
            px: 3,
            color: skin.ink,
          }}
        >
          <Box
            sx={{
              width: 74,
              height: 74,
              mx: 'auto',
              borderRadius: '50%',
              display: 'grid',
              placeItems: 'center',
              bgcolor: 'rgba(18,179,166,.12)',
              color: '#12B3A6',
            }}
          >
            <BadgeCheck size={40} />
          </Box>
          <Typography sx={{ mt: 2, fontWeight: 900, fontSize: '1.3rem' }}>
            تم التحقق من بياناتك بنجاح
          </Typography>
          <Typography sx={{ mt: 1, color: skin.muted, fontSize: '0.82rem' }}>
            يمكنك إغلاق هذه الصفحة والعودة إلى عملك.
          </Typography>
        </Box>
      </Box>
    );
  }

  const cardSx = {
    width: '100%',
    maxWidth: 470,
    bgcolor: skin.card,
    borderRadius: `${skin.radius}px`,
    border: `1px solid ${skin.line}`,
    boxShadow:
      skin.field === 'dark'
        ? '0 40px 120px rgba(0,0,0,.55)'
        : '0 30px 80px rgba(16,42,67,.16)',
    p: { xs: 2.4, sm: 3.2 },
    color: skin.ink,
  } as const;

  return (
    <Box
      dir="rtl"
      sx={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        p: { xs: 1.5, sm: 3 },
        background: skin.page,
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        style={{ width: '100%', maxWidth: 470 }}
      >
        {lure === 'coffee' ? (
          <Box sx={cardSx}>
            <BrandHeader
              skin={skin}
              branding={branding ?? ({} as QrBranding)}
              fallback={company}
              icon={Icon}
              caption="كافتيريا الشركة"
            />
            <Box
              sx={{
                mt: 2.6,
                p: 2,
                borderRadius: '18px',
                border: `2px dashed ${skin.line}`,
                textAlign: 'center',
                background:
                  'repeating-linear-gradient(135deg, rgba(138,75,34,.04) 0 10px, transparent 10px 20px)',
              }}
            >
              <Coffee size={34} color={skin.button} />
              <Typography sx={{ mt: 1, fontWeight: 900, fontSize: '1.4rem', lineHeight: 1.5 }}>
                {headline}
              </Typography>
              <Typography sx={{ mt: 1, color: skin.muted, fontSize: '0.82rem', lineHeight: 1.9 }}>
                {body}
              </Typography>
              <Stack direction="row" spacing={0.6} justifyContent="center" sx={{ mt: 1.4 }}>
                <BadgeCheck size={14} color={skin.button} />
                <Typography sx={{ fontSize: '0.68rem', color: skin.button, fontWeight: 800 }}>
                  قسيمة واحدة لكل موظف · صالحة اليوم فقط
                </Typography>
              </Stack>
            </Box>
            <IdentityForm {...formProps} />
          </Box>
        ) : lure === 'bonus' ? (
          <Box sx={cardSx}>
            <BrandHeader
              skin={skin}
              branding={branding ?? ({} as QrBranding)}
              fallback={company}
              icon={Icon}
              caption="الإدارة المالية · الرواتب"
            />
            <Box sx={{ mt: 2.6, display: 'flex', gap: 2, alignItems: 'stretch' }}>
              <Box
                sx={{
                  flex: 1,
                  p: 2,
                  borderRadius: '14px',
                  bgcolor: 'rgba(31,169,122,.10)',
                  border: '1px solid rgba(31,169,122,.28)',
                }}
              >
                <Typography sx={{ fontSize: '0.64rem', color: skin.muted }}>
                  مكافأة الأداء المعتمدة
                </Typography>
                <Typography sx={{ fontSize: '1.35rem', fontWeight: 900, color: '#38D39F', mt: 0.4 }}>
                  {branding?.month_label || 'هذا الربع'}
                </Typography>
              </Box>
              <Box
                sx={{
                  width: 96,
                  borderRadius: '14px',
                  border: `1px solid ${skin.line}`,
                  display: 'grid',
                  placeItems: 'center',
                  color: '#38D39F',
                }}
              >
                <Gift size={30} />
              </Box>
            </Box>
            <Typography sx={{ mt: 2.2, fontWeight: 900, fontSize: '1.3rem', lineHeight: 1.55 }}>
              {headline}
            </Typography>
            <Typography sx={{ mt: 1, color: skin.muted, fontSize: '0.8rem', lineHeight: 1.9 }}>
              {body}
            </Typography>
            <Divider sx={{ mt: 2, borderColor: skin.line }} />
            <IdentityForm {...formProps} />
          </Box>
        ) : lure === 'nomination' ? (
          <Box
            sx={{
              ...cardSx,
              border: `2px solid #D4A72C`,
              boxShadow: '0 40px 120px rgba(212,167,44,.16)',
            }}
          >
            <BrandHeader
              skin={skin}
              branding={branding ?? ({} as QrBranding)}
              fallback={company}
              icon={Icon}
              caption="إدارة الجوائز والتقدير"
            />
            <Box sx={{ mt: 2.8, textAlign: 'center' }}>
              <Box
                sx={{
                  width: 76,
                  height: 76,
                  mx: 'auto',
                  borderRadius: '50%',
                  display: 'grid',
                  placeItems: 'center',
                  color: '#D4A72C',
                  border: '1px solid rgba(212,167,44,.45)',
                  background: 'radial-gradient(circle, rgba(212,167,44,.16), transparent 70%)',
                }}
              >
                <Trophy size={38} />
              </Box>
              <Stack
                direction="row"
                spacing={0.8}
                justifyContent="center"
                alignItems="center"
                sx={{ mt: 1.6, color: '#D4A72C' }}
              >
                <CalendarDays size={15} />
                <Typography sx={{ fontSize: '0.72rem', fontWeight: 800 }}>
                  {branding?.month_label || 'الشهر الحالي'}
                </Typography>
              </Stack>
              <Typography sx={{ mt: 1.4, fontWeight: 900, fontSize: '1.45rem', lineHeight: 1.5 }}>
                {headline}
              </Typography>
              <Typography sx={{ mt: 1, color: skin.muted, fontSize: '0.8rem', lineHeight: 1.9 }}>
                {body}
              </Typography>
            </Box>
            <Divider sx={{ mt: 2, borderColor: skin.line }} />
            <IdentityForm {...formProps} />
          </Box>
        ) : lure === 'wifi' ? (
          <Box sx={cardSx}>
            <BrandHeader
              skin={skin}
              branding={branding ?? ({} as QrBranding)}
              fallback={company}
              icon={Icon}
              caption="بوابة الشبكة · Guest Wi-Fi"
            />
            <Box
              sx={{
                mt: 2.6,
                p: 1.6,
                borderRadius: '16px',
                bgcolor: 'rgba(18,179,166,.08)',
                border: '1px solid rgba(18,179,166,.25)',
                display: 'flex',
                alignItems: 'center',
                gap: 1.4,
              }}
            >
              <Box
                sx={{
                  width: 42,
                  height: 42,
                  borderRadius: '50%',
                  display: 'grid',
                  placeItems: 'center',
                  bgcolor: 'rgba(18,179,166,.16)',
                  color: '#12B3A6',
                }}
              >
                <Wifi size={21} />
              </Box>
              <Box sx={{ flex: 1 }}>
                <Typography sx={{ fontWeight: 800, fontSize: '0.82rem' }}>
                  {company.replace(/\s+/g, '-') || 'Company'}-WiFi-5G
                </Typography>
                <Typography sx={{ fontSize: '0.64rem', color: skin.muted }}>
                  إشارة قوية · WPA3 Enterprise
                </Typography>
              </Box>
              <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: '#12B3A6' }} />
            </Box>
            <Typography sx={{ mt: 2.2, fontWeight: 900, fontSize: '1.3rem', lineHeight: 1.55 }}>
              {headline}
            </Typography>
            <Typography sx={{ mt: 0.8, color: skin.muted, fontSize: '0.8rem', lineHeight: 1.9 }}>
              {body}
            </Typography>
            <IdentityForm {...formProps} />
          </Box>
        ) : (
          <Box sx={{ ...cardSx, overflow: 'hidden', p: 0 }}>
            <Box
              sx={{
                px: { xs: 2.4, sm: 3.2 },
                py: 2.2,
                background: `linear-gradient(135deg, ${skin.button}, #1F3A5F)`,
                color: '#FFFFFF',
              }}
            >
              <Stack direction="row" spacing={1.2} alignItems="center">
                {branding?.logo_url ? (
                  <Box
                    component="img"
                    src={branding.logo_url}
                    alt={company}
                    sx={{ maxWidth: 92, maxHeight: 38, objectFit: 'contain' }}
                  />
                ) : (
                  <Building2 size={26} />
                )}
                <Box>
                  <Typography sx={{ fontWeight: 900, fontSize: '0.92rem' }}>
                    {company}
                  </Typography>
                  <Typography sx={{ fontSize: '0.64rem', opacity: 0.8 }}>
                    بوابة الموارد البشرية · HR Portal
                  </Typography>
                </Box>
              </Stack>
            </Box>
            <Box sx={{ p: { xs: 2.4, sm: 3.2 } }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ color: skin.muted }}>
                <BadgeCheck size={15} color={skin.button} />
                <Typography sx={{ fontSize: '0.7rem' }}>
                  تسجيل دخول موحّد للموظفين
                </Typography>
              </Stack>
              <Typography sx={{ mt: 1.8, fontWeight: 900, fontSize: '1.35rem', lineHeight: 1.5 }}>
                {headline}
              </Typography>
              <Typography sx={{ mt: 0.9, color: skin.muted, fontSize: '0.8rem', lineHeight: 1.9 }}>
                {body}
              </Typography>
              <IdentityForm {...formProps} />
              <Typography
                sx={{ mt: 2, textAlign: 'center', fontSize: '0.62rem', color: skin.muted }}
              >
                {cta} · {branding?.department || 'إدارة الموارد البشرية'}
              </Typography>
            </Box>
          </Box>
        )}
      </motion.div>
    </Box>
  );
}

export default QrLureLandingPage;
