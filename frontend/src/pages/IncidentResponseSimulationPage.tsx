/**
 * Incident Response Simulation — a safe, local SOC drill.
 *
 * Everything on this page is fictional and happens in React state.  There is no
 * WebSocket, no endpoint agent, no command execution and no network call from
 * the terminal.  The page is intentionally explicit about that boundary: the
 * goal is to teach what a SOC console looks like and what a USB incident looks
 * like, never to imply a real compromise.
 */
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Activity,
  ChevronRight,
  Clock3,
  Download,
  Laptop,
  Lock,
  LockKeyhole,
  Monitor,
  Play,
  Power,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Trash2,
  Unlock,
  Wifi,
  X,
} from 'lucide-react';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';

import { MatrixRain } from '@/components/MatrixRain';
import { SecurityRecommendationsPanel } from '@/components/SecurityRecommendationsPanel';

type SocTab = 'simulation' | 'recommendations';
type RiskLevel = 'critical' | 'high' | 'medium' | 'low';
type LineKind = 'system' | 'command' | 'success' | 'warning' | 'error' | 'output' | 'muted';

interface DemoEndpoint {
  id: string;
  name: string;
  nameEn: string;
  user: string;
  username: string;
  role: string;
  department: string;
  hostname: string;
  ip: string;
  os: string;
  risk: RiskLevel;
  riskLabel: string;
  status: 'online' | 'idle';
  lastSeen: string;
  initials: string;
  accent: string;
}

interface TerminalLine {
  id: number;
  kind: LineKind;
  text: string;
  time: string;
}

interface NewTerminalLine {
  kind: LineKind;
  text: string;
  time?: string;
}

const DEMO_ENDPOINTS: DemoEndpoint[] = [
  {
    id: 'ahmed-finance',
    name: 'حاسوب أحمد',
    nameEn: "Ahmed's Laptop",
    user: 'أحمد محمد',
    username: 'ahmed.m',
    role: 'محاسب أول',
    department: 'المالية',
    hostname: 'AHMED-LT-01',
    ip: '10.24.18.47',
    os: 'Windows 11 Pro',
    risk: 'critical',
    riskLabel: 'حرج',
    status: 'online',
    lastSeen: 'قبل 12 ثانية',
    initials: 'أح',
    accent: '#FF1744',
  },
  {
    id: 'sara-hr',
    name: 'حاسوب سارة',
    nameEn: "Sara's Laptop",
    user: 'سارة العتيبي',
    username: 'sara.a',
    role: 'أخصائية موارد بشرية',
    department: 'الموارد البشرية',
    hostname: 'SARA-HR-02',
    ip: '10.24.22.109',
    os: 'Windows 10 Enterprise',
    risk: 'high',
    riskLabel: 'مرتفع',
    status: 'online',
    lastSeen: 'قبل 41 ثانية',
    initials: 'سع',
    accent: '#FFB020',
  },
  {
    id: 'khalid-ops',
    name: 'خالد — العمليات',
    nameEn: "Khalid's Workstation",
    user: 'خالد السالم',
    username: 'khalid.s',
    role: 'مشرف عمليات',
    department: 'العمليات',
    hostname: 'KHALID-OPS-07',
    ip: '10.24.30.12',
    os: 'Windows 11 Pro',
    risk: 'medium',
    riskLabel: 'متوسط',
    status: 'idle',
    lastSeen: 'قبل 3 دقائق',
    initials: 'خا',
    accent: '#00F0FF',
  },
  {
    id: 'reception-front',
    name: 'استقبال — الطابق الأرضي',
    nameEn: 'Reception Front Desk',
    user: 'مريم الحربي',
    username: 'reception',
    role: 'موظفة استقبال',
    department: 'الاستقبال',
    hostname: 'REC-FRONT-03',
    ip: '10.24.10.5',
    os: 'Windows 11 Pro',
    risk: 'low',
    riskLabel: 'منخفض',
    status: 'online',
    lastSeen: 'قبل 8 ثوان',
    initials: 'مح',
    accent: '#00E676',
  },
];

const LINE_COLORS: Record<LineKind, string> = {
  system: '#00F0FF',
  command: '#E2E8F0',
  success: '#00E676',
  warning: '#FFB020',
  error: '#FF1744',
  output: '#A9C7E8',
  muted: '#5F7188',
};

const RISK_STYLE: Record<RiskLevel, { color: string; bg: string; border: string }> = {
  critical: { color: '#FF8A9A', bg: 'rgba(255,23,68,.10)', border: 'rgba(255,23,68,.32)' },
  high: { color: '#FFC857', bg: 'rgba(255,176,32,.10)', border: 'rgba(255,176,32,.28)' },
  medium: { color: '#8BE9FD', bg: 'rgba(0,240,255,.08)', border: 'rgba(0,240,255,.22)' },
  low: { color: '#7DFFB2', bg: 'rgba(0,230,118,.08)', border: 'rgba(0,230,118,.22)' },
};

function timestamp(): string {
  return new Date().toLocaleTimeString('en-GB', { hour12: false });
}

function bootLines(endpoint: DemoEndpoint): TerminalLine[] {
  const now = timestamp();
  return [
    { id: 1, kind: 'system', text: 'HUMINT Shield // SOC SIMULATION CONSOLE v2.4', time: now },
    {
      id: 2,
      kind: 'muted',
      text: 'SIMULATION ONLY — no real endpoint is connected and no command is executed.',
      time: now,
    },
    {
      id: 3,
      kind: 'system',
      text: `Attaching to simulated endpoint ${endpoint.hostname} (${endpoint.ip})...`,
      time: now,
    },
    {
      id: 4,
      kind: 'success',
      text: `Session established: ${endpoint.username} @ ${endpoint.hostname}`,
      time: now,
    },
    {
      id: 5,
      kind: 'output',
      text: `OS: ${endpoint.os} · Risk: ${endpoint.riskLabel} · Last check-in: ${endpoint.lastSeen}`,
      time: now,
    },
    {
      id: 6,
      kind: 'muted',
      text: 'Type "help" to list the safe simulation commands.',
      time: now,
    },
  ];
}

function StatTile({
  label,
  value,
  note,
  icon,
  color,
}: {
  label: string;
  value: string | number;
  note: string;
  icon: ReactNode;
  color: string;
}) {
  return (
    <Card
      sx={{
        height: '100%',
        border: '1px solid rgba(255,255,255,.07)',
        background: `linear-gradient(150deg, ${alpha(color, 0.10)}, rgba(8,13,24,.82) 70%)`,
      }}
    >
      <CardContent sx={{ p: 1.8 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="flex-start">
          <Typography sx={{ fontSize: '0.66rem', color: 'text.secondary', fontWeight: 700 }}>
            {label}
          </Typography>
          <Box sx={{ color, opacity: 0.9 }}>{icon}</Box>
        </Stack>
        <Typography
          sx={{
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
            fontSize: '1.5rem',
            fontWeight: 900,
            lineHeight: 1.3,
            color,
            mt: 0.6,
          }}
        >
          {value}
        </Typography>
        <Typography sx={{ fontSize: '0.58rem', color: 'text.disabled', mt: 0.2 }}>{note}</Typography>
      </CardContent>
    </Card>
  );
}

function EndpointRow({
  endpoint,
  selected,
  locked,
  onSelect,
}: {
  endpoint: DemoEndpoint;
  selected: boolean;
  locked: boolean;
  onSelect: () => void;
}) {
  const risk = RISK_STYLE[endpoint.risk];
  return (
    <Box
      component="button"
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      sx={{
        width: '100%',
        textAlign: 'right',
        display: 'flex',
        alignItems: 'center',
        gap: 1.1,
        p: 1.2,
        borderRadius: 2.2,
        cursor: 'pointer',
        color: 'inherit',
        border: `1px solid ${selected ? alpha(endpoint.accent, 0.55) : 'rgba(255,255,255,.06)'}`,
        bgcolor: selected ? alpha(endpoint.accent, 0.075) : 'rgba(255,255,255,.018)',
        boxShadow: selected ? `0 0 24px ${alpha(endpoint.accent, 0.10)}` : 'none',
        transition: 'border-color .18s ease, background .18s ease',
        '&:hover': { borderColor: alpha(endpoint.accent, 0.42) },
      }}
    >
      <Box
        sx={{
          width: 38,
          height: 38,
          borderRadius: 1.6,
          flex: '0 0 auto',
          display: 'grid',
          placeItems: 'center',
          bgcolor: alpha(endpoint.accent, 0.12),
          color: endpoint.accent,
          border: `1px solid ${alpha(endpoint.accent, 0.28)}`,
          fontWeight: 900,
          fontSize: '0.78rem',
        }}
      >
        {endpoint.initials}
      </Box>
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={0.7} alignItems="center">
          <Typography sx={{ fontWeight: 800, fontSize: '0.76rem', lineHeight: 1.4 }}>
            {endpoint.name}
          </Typography>
          <Typography
            dir="ltr"
            sx={{ fontSize: '0.56rem', color: 'text.disabled', lineHeight: 1.4 }}
          >
            {endpoint.nameEn}
          </Typography>
          {locked ? <Lock size={12} color="#FF6B81" /> : null}
        </Stack>
        <Typography
          dir="ltr"
          sx={{
            fontSize: '0.6rem',
            color: 'text.secondary',
            fontFamily: 'monospace',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {endpoint.username} · {endpoint.hostname} · {endpoint.ip}
        </Typography>
        <Stack direction="row" spacing={0.6} alignItems="center" sx={{ mt: 0.4 }}>
          <Box
            sx={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              bgcolor: endpoint.status === 'online' ? '#00E676' : '#FFB020',
              boxShadow: `0 0 7px ${endpoint.status === 'online' ? '#00E676' : '#FFB020'}`,
            }}
          />
          <Typography sx={{ fontSize: '0.56rem', color: 'text.disabled' }}>
            {endpoint.status === 'online' ? 'متصل' : 'خامل'} · {endpoint.lastSeen}
          </Typography>
        </Stack>
      </Box>
      <Stack alignItems="flex-end" spacing={0.5} sx={{ flex: '0 0 auto' }}>
        <Chip
          size="small"
          label={endpoint.riskLabel}
          sx={{
            height: 19,
            fontSize: '0.54rem',
            fontWeight: 800,
            color: risk.color,
            bgcolor: risk.bg,
            border: `1px solid ${risk.border}`,
          }}
        />
        <ChevronRight size={14} color={selected ? endpoint.accent : '#4B5B73'} />
      </Stack>
    </Box>
  );
}

function FakeSpreadsheet() {
  const rows = [
    ['Ahmed M.', 'Finance', '12,500', 'SA•• 4821'],
    ['Sara A.', 'HR', '9,800', 'SA•• 7310'],
    ['Khalid S.', 'Operations', '8,200', 'SA•• 1194'],
    ['Mariam H.', 'Reception', '6,400', 'SA•• 9088'],
    ['Faisal N.', 'IT', '11,100', 'SA•• 2207'],
  ];
  return (
    <Box
      sx={{
        position: 'absolute',
        top: { xs: 14, sm: 26 },
        left: { xs: 12, sm: 28 },
        width: { xs: '70%', sm: '54%' },
        borderRadius: 1.2,
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,.20)',
        bgcolor: '#F8FAFC',
        boxShadow: '0 18px 45px rgba(0,0,0,.38)',
      }}
    >
      <Box
        sx={{
          px: 1,
          py: 0.55,
          bgcolor: '#107C41',
          color: '#fff',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <Typography sx={{ fontSize: '0.5rem', fontWeight: 800, fontFamily: 'monospace' }}>
          Employee_Records_Q4.xlsx — Excel
        </Typography>
        <Typography sx={{ fontSize: '0.45rem', opacity: 0.75 }}>— □ ×</Typography>
      </Box>
      <Box sx={{ p: 0.8 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.5 }}>
          <Typography sx={{ fontSize: '0.42rem', color: '#B91C1C', fontWeight: 800 }}>
            SENSITIVE — FICTIONAL DATA
          </Typography>
          <Typography sx={{ fontSize: '0.4rem', color: '#64748B' }}>Sheet1</Typography>
        </Stack>
        <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'monospace' }}>
          <Box component="thead">
            <Box component="tr">
              {['Employee', 'Department', 'Salary', 'IBAN'].map((head) => (
                <Box
                  component="th"
                  key={head}
                  sx={{
                    fontSize: '0.4rem',
                    textAlign: 'left',
                    p: 0.35,
                    border: '1px solid #D1D5DB',
                    bgcolor: '#E2E8F0',
                    color: '#334155',
                  }}
                >
                  {head}
                </Box>
              ))}
            </Box>
          </Box>
          <Box component="tbody">
            {rows.map((row) => (
              <Box component="tr" key={row[0]}>
                {row.map((cell) => (
                  <Box
                    component="td"
                    key={`${row[0]}-${cell}`}
                    sx={{
                      fontSize: '0.38rem',
                      p: 0.32,
                      border: '1px solid #E5E7EB',
                      color: '#0F172A',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {cell}
                  </Box>
                ))}
              </Box>
            ))}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

function SimulatedScreenshot({
  endpoint,
  locked,
  alertMessage,
  onClose,
  onUnlock,
  onClearAlert,
}: {
  endpoint: DemoEndpoint;
  locked: boolean;
  alertMessage: string | null;
  onClose: () => void;
  onUnlock: () => void;
  onClearAlert: () => void;
}) {
  return (
    <Card
      sx={{
        mt: 2,
        overflow: 'hidden',
        border: '1px solid rgba(255,23,68,.28)',
        boxShadow: '0 30px 80px rgba(0,0,0,.45), 0 0 32px rgba(255,23,68,.08)',
      }}
    >
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ px: 1.6, py: 1, bgcolor: 'rgba(255,23,68,.07)', borderBottom: '1px solid rgba(255,23,68,.18)' }}
      >
        <Stack direction="row" spacing={0.8} alignItems="center" sx={{ minWidth: 0 }}>
          <Monitor size={15} color="#FF6B81" />
          <Typography
            dir="ltr"
            sx={{ fontFamily: 'monospace', fontSize: '0.66rem', color: '#FF8A9A', fontWeight: 700 }}
          >
            EVIDENCE // screen-capture-{endpoint.id}.png
          </Typography>
          <Chip
            size="small"
            label="SIMULATED"
            sx={{ height: 18, bgcolor: 'rgba(255,255,255,.06)', color: 'text.secondary', fontSize: '0.52rem' }}
          />
        </Stack>
        <Tooltip title="إغلاق المعاينة">
          <IconButton size="small" onClick={onClose} aria-label="إغلاق لقطة الشاشة">
            <X size={15} />
          </IconButton>
        </Tooltip>
      </Stack>

      <Box sx={{ p: 1.4 }}>
        <Box
          sx={{
            position: 'relative',
            aspectRatio: '16 / 9',
            minHeight: { xs: 210, sm: 300 },
            maxHeight: 420,
            borderRadius: 2,
            overflow: 'hidden',
            border: '1px solid rgba(255,255,255,.16)',
            background:
              'radial-gradient(circle at 18% 30%, rgba(26,90,160,.85), transparent 42%), radial-gradient(circle at 82% 68%, rgba(112,0,255,.6), transparent 40%), linear-gradient(135deg, #071a33, #0b1d3a 45%, #1a0b36)',
          }}
        >
          {/* Desktop wallpaper geometry */}
          <Box sx={{ position: 'absolute', inset: 0, opacity: 0.34 }}>
            <Box sx={{ position: 'absolute', width: '55%', height: '80%', left: '-10%', top: '12%', border: '1px solid rgba(0,240,255,.35)', transform: 'rotate(-18deg)' }} />
            <Box sx={{ position: 'absolute', width: '36%', height: '55%', right: '6%', top: '20%', border: '1px solid rgba(255,255,255,.18)', transform: 'rotate(22deg)' }} />
          </Box>

          <FakeSpreadsheet />

          {/* A second small window for depth */}
          <Box
            sx={{
              position: 'absolute',
              right: { xs: 10, sm: 24 },
              bottom: { xs: 52, sm: 78 },
              width: { xs: '48%', sm: '32%' },
              borderRadius: 1,
              overflow: 'hidden',
              border: '1px solid rgba(255,255,255,.18)',
              bgcolor: '#0f172a',
              boxShadow: '0 16px 40px rgba(0,0,0,.35)',
            }}
          >
            <Box sx={{ px: 0.8, py: 0.4, bgcolor: '#1e293b', display: 'flex', justifyContent: 'space-between' }}>
              <Typography sx={{ fontSize: '0.42rem', color: '#CBD5E1', fontFamily: 'monospace' }}>Salary_Preview.pdf</Typography>
              <Typography sx={{ fontSize: '0.4rem', color: '#94A3B8' }}>— □ ×</Typography>
            </Box>
            <Box sx={{ p: 0.8 }}>
              <Box sx={{ height: 4, width: '72%', bgcolor: 'rgba(0,240,255,.55)', mb: 0.5 }} />
              <Box sx={{ height: 3, width: '92%', bgcolor: 'rgba(255,255,255,.18)', mb: 0.35 }} />
              <Box sx={{ height: 3, width: '84%', bgcolor: 'rgba(255,255,255,.14)', mb: 0.35 }} />
              <Box sx={{ height: 3, width: '64%', bgcolor: 'rgba(255,255,255,.12)' }} />
            </Box>
          </Box>

          {/* Watermark */}
          <Typography
            sx={{
              position: 'absolute',
              top: '45%',
              left: '50%',
              transform: 'translate(-50%, -50%) rotate(-18deg)',
              fontFamily: 'monospace',
              fontWeight: 900,
              fontSize: { xs: '1.4rem', sm: '2.4rem' },
              letterSpacing: '.22em',
              color: 'rgba(255,255,255,.07)',
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
            }}
          >
            SIMULATED
          </Typography>

          {/* Windows taskbar */}
          <Box
            sx={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 0,
              height: 27,
              px: 1,
              bgcolor: 'rgba(5,10,18,.88)',
              borderTop: '1px solid rgba(255,255,255,.10)',
              display: 'flex',
              alignItems: 'center',
              gap: 0.8,
              zIndex: 2,
            }}
          >
            <Box sx={{ width: 15, height: 15, borderRadius: 0.4, bgcolor: '#00F0FF', opacity: 0.9 }} />
            <Box sx={{ width: 68, height: 12, borderRadius: 99, bgcolor: 'rgba(255,255,255,.08)' }} />
            <Box sx={{ flex: 1 }} />
            <Typography sx={{ fontFamily: 'monospace', fontSize: '0.43rem', color: '#CBD5E1' }}>
              10:42 AM · 10/28/2026
            </Typography>
          </Box>

          {/* Evidence banner */}
          <Box
            sx={{
              position: 'absolute',
              left: 0,
              right: 0,
              bottom: 27,
              px: 1.2,
              py: 0.7,
              bgcolor: 'rgba(5,10,18,.92)',
              borderTop: '1px solid rgba(255,23,68,.68)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 1,
              zIndex: 3,
            }}
          >
            <Stack direction="row" spacing={0.6} alignItems="center">
              <ShieldAlert size={14} color="#FF1744" />
              <Typography
                dir="ltr"
                sx={{
                  fontFamily: 'monospace',
                  fontWeight: 900,
                  letterSpacing: '.04em',
                  color: '#FF8A9A',
                  fontSize: { xs: '0.5rem', sm: '0.66rem' },
                }}
              >
                Proof of Unauthorized Screen Access
              </Typography>
            </Stack>
            <Typography sx={{ fontFamily: 'monospace', fontSize: '0.46rem', color: '#94A3B8', display: { xs: 'none', sm: 'block' } }}>
              {endpoint.hostname} · {timestamp()}
            </Typography>
          </Box>

          {/* Simulated Windows notification */}
          <AnimatePresence>
            {alertMessage ? (
              <motion.div
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 24 }}
                style={{ position: 'absolute', right: 12, bottom: 50, width: 'min(280px, 68%)', zIndex: 5 }}
              >
                <Box
                  sx={{
                    p: 1.1,
                    borderRadius: 1.4,
                    bgcolor: 'rgba(15,23,42,.96)',
                    border: '1px solid rgba(0,240,255,.30)',
                    boxShadow: '0 16px 36px rgba(0,0,0,.45)',
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 0.4 }}>
                    <Typography sx={{ fontSize: '0.58rem', color: '#00F0FF', fontWeight: 800 }}>
                      Security Notice
                    </Typography>
                    <Box
                      component="button"
                      type="button"
                      onClick={onClearAlert}
                      aria-label="إغلاق التنبيه"
                      sx={{ border: 0, background: 'transparent', color: '#94A3B8', cursor: 'pointer', p: 0 }}
                    >
                      <X size={11} />
                    </Box>
                  </Stack>
                  <Typography sx={{ fontSize: '0.62rem', color: '#E2E8F0', lineHeight: 1.7 }}>
                    {alertMessage}
                  </Typography>
                </Box>
              </motion.div>
            ) : null}
          </AnimatePresence>

          {/* Lock overlay */}
          <AnimatePresence>
            {locked ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                style={{ position: 'absolute', inset: 0, zIndex: 6 }}
              >
                <Box
                  sx={{
                    position: 'absolute',
                    inset: 0,
                    bgcolor: 'rgba(64,0,10,.86)',
                    backdropFilter: 'blur(3px)',
                    display: 'grid',
                    placeItems: 'center',
                    p: 2,
                  }}
                >
                  <Stack alignItems="center" spacing={1}>
                    <LockKeyhole size={52} color="#FF6B81" />
                    <Typography
                      sx={{
                        fontFamily: 'monospace',
                        fontWeight: 900,
                        letterSpacing: '.18em',
                        color: '#FF8A9A',
                        fontSize: { xs: '1.0rem', sm: '1.6rem' },
                        textAlign: 'center',
                      }}
                    >
                      ENDPOINT LOCKED
                    </Typography>
                    <Typography sx={{ color: '#FFD1D8', fontSize: '0.76rem', textAlign: 'center' }}>
                      تم قفل الجهاز — محاكاة فقط. لا يوجد جهاز حقيقي متأثر.
                    </Typography>
                    <Button
                      size="small"
                      variant="contained"
                      color="error"
                      startIcon={<Unlock size={14} />}
                      onClick={onUnlock}
                    >
                      Restore endpoint
                    </Button>
                  </Stack>
                </Box>
              </motion.div>
            ) : null}
          </AnimatePresence>
        </Box>

        <Stack direction="row" spacing={0.7} alignItems="center" sx={{ mt: 1 }}>
          <ShieldAlert size={13} color="#FF6B81" />
          <Typography sx={{ fontSize: '0.62rem', color: 'text.secondary', lineHeight: 1.7 }}>
            لقطة شاشة مُصطنعة بالكامل. البيانات والأسماء وهمية، ولا تحتوي على أي معلومات
            حقيقية. الغرض تعليمي فقط.
          </Typography>
        </Stack>
      </Box>
    </Card>
  );
}

export function IncidentResponseSimulationPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: SocTab =
    searchParams.get('tab') === 'recommendations' ? 'recommendations' : 'simulation';

  const [selectedId, setSelectedId] = useState(DEMO_ENDPOINTS[0].id);
  const selected = useMemo(
    () => DEMO_ENDPOINTS.find((endpoint) => endpoint.id === selectedId) ?? DEMO_ENDPOINTS[0],
    [selectedId],
  );

  const [lines, setLines] = useState<TerminalLine[]>(() => bootLines(DEMO_ENDPOINTS[0]));
  const [command, setCommand] = useState('');
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [lockedIds, setLockedIds] = useState<Set<string>>(new Set());
  const [screenshotOpen, setScreenshotOpen] = useState(false);
  const [alertMessage, setAlertMessage] = useState<string | null>(null);
  const [sessionClosed, setSessionClosed] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  // Boot lines use IDs 1-6; start appended lines above that range so a
  // reconnect never produces duplicate React keys.
  const lineId = useRef(100);
  const runToken = useRef(0);
  const terminalRef = useRef<HTMLDivElement | null>(null);

  const locked = lockedIds.has(selected.id);
  const uptime = `${String(Math.floor(elapsed / 3600)).padStart(2, '0')}:${String(
    Math.floor((elapsed % 3600) / 60),
  ).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;

  useEffect(() => {
    const handle = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(handle);
  }, []);

  useEffect(() => {
    const element = terminalRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lines, busy, selectedId]);

  function addLines(next: NewTerminalLine[]) {
    setLines((current) => [
      ...current,
      ...next.map((line) => ({
        id: lineId.current++,
        kind: line.kind,
        text: line.text,
        time: line.time ?? timestamp(),
      })),
    ]);
  }

  function changeTab(next: SocTab) {
    const params = new URLSearchParams(searchParams);
    if (next === 'recommendations') params.set('tab', 'recommendations');
    else params.delete('tab');
    setSearchParams(params, { replace: true });
  }

  function selectEndpoint(endpoint: DemoEndpoint) {
    if (endpoint.id === selectedId) return;
    runToken.current += 1;
    setSelectedId(endpoint.id);
    setScreenshotOpen(false);
    setAlertMessage(null);
    setSessionClosed(false);
    setBusy(false);
    setLines(bootLines(endpoint));
    setCommand('');
    setHistoryIndex(-1);
  }

  function resetDemo() {
    runToken.current += 1;
    setSelectedId(DEMO_ENDPOINTS[0].id);
    setLines(bootLines(DEMO_ENDPOINTS[0]));
    setLockedIds(new Set());
    setScreenshotOpen(false);
    setAlertMessage(null);
    setSessionClosed(false);
    setBusy(false);
    setCommand('');
    setHistory([]);
    setHistoryIndex(-1);
    setElapsed(0);
  }

  function lockEndpoint() {
    setLockedIds((current) => {
      const next = new Set(current);
      next.add(selected.id);
      return next;
    });
    setScreenshotOpen(true);
  }

  function unlockEndpoint() {
    setLockedIds((current) => {
      const next = new Set(current);
      next.delete(selected.id);
      return next;
    });
  }

  function executeCommand(raw: string) {
    const [verb, ...rest] = raw.trim().split(/\s+/);
    const action = (verb ?? '').toLowerCase();
    const argument = rest.join(' ').trim();

    if (!action) return;

    if (action === 'help') {
      addLines([
        { kind: 'system', text: 'Available simulation commands:' },
        { kind: 'output', text: '  help                 show this help' },
        { kind: 'output', text: '  whoami               show the simulated identity' },
        { kind: 'output', text: '  hostname             show the simulated host' },
        { kind: 'output', text: '  screenshot           capture a simulated screen (evidence placeholder)' },
        { kind: 'output', text: '  lock                 lock the simulated endpoint' },
        { kind: 'output', text: '  unlock               release the simulated lock' },
        { kind: 'output', text: '  msg <text>           show a simulated desktop alert' },
        { kind: 'output', text: '  processes            list simulated processes' },
        { kind: 'output', text: '  netstat              list simulated connections' },
        { kind: 'output', text: '  usb                  show the simulated USB-drop timeline' },
        { kind: 'output', text: '  select <1-4>         switch the simulated endpoint' },
        { kind: 'output', text: '  clear                clear the terminal' },
        { kind: 'output', text: '  exit                 close the simulated session' },
        { kind: 'muted', text: 'Every command only changes local React state. Nothing is executed.' },
      ]);
      return;
    }

    if (action === 'whoami') {
      addLines([
        { kind: 'output', text: `${selected.user} — ${selected.role} (${selected.department})` },
        { kind: 'output', text: `DOMAIN\\${selected.username}` },
        { kind: 'muted', text: 'Simulated identity. No credential is used or validated.' },
      ]);
      return;
    }

    if (action === 'hostname') {
      addLines([
        { kind: 'output', text: `${selected.hostname} · ${selected.os}` },
        { kind: 'output', text: `IPv4: ${selected.ip} · Status: ${selected.status}` },
      ]);
      return;
    }

    if (action === 'screenshot') {
      setScreenshotOpen(true);
      addLines([
        { kind: 'success', text: `screen-capture-${selected.id}.png captured (1920x1080, simulated)` },
        { kind: 'output', text: `SHA-256: 4f9c2a7d…demo…91e8 (placeholder, not a real hash)` },
        { kind: 'warning', text: 'Proof of Unauthorized Screen Access — evidence panel opened.' },
      ]);
      return;
    }

    if (action === 'lock') {
      lockEndpoint();
      addLines([
        { kind: 'warning', text: `workstation lock issued to ${selected.hostname}` },
        { kind: 'error', text: 'ENDPOINT LOCKED — input devices are frozen (simulation).' },
        { kind: 'muted', text: 'Type "unlock" or use the Restore button to release the simulation.' },
      ]);
      return;
    }

    if (action === 'unlock') {
      if (!locked) {
        addLines([{ kind: 'muted', text: 'The simulated endpoint is not locked.' }]);
        return;
      }
      unlockEndpoint();
      addLines([{ kind: 'success', text: `lock released on ${selected.hostname} (simulation).` }]);
      return;
    }

    if (action === 'msg' || action === 'display_alert') {
      if (!argument) {
        addLines([{ kind: 'warning', text: 'usage: msg <text> — example: msg Security alert' }]);
        return;
      }
      const message = argument.slice(0, 140);
      setAlertMessage(message);
      setScreenshotOpen(true);
      addLines([
        { kind: 'success', text: `desktop alert displayed on ${selected.hostname}: "${message}"` },
        { kind: 'muted', text: 'This is a local React overlay, not a real Windows notification.' },
      ]);
      return;
    }

    if (action === 'processes' || action === 'ps') {
      addLines([
        { kind: 'output', text: 'PID    NAME                 USER          CPU    MEM' },
        { kind: 'output', text: '4120   explorer.exe         ahmed.m       1.2%   84 MB' },
        { kind: 'output', text: '7788   EXCEL.EXE            ahmed.m       0.4%   212 MB' },
        { kind: 'output', text: '9912   chrome.exe           ahmed.m       3.1%   640 MB' },
        { kind: 'output', text: '1204   MsMpEng.exe          SYSTEM        0.8%   188 MB' },
        { kind: 'warning', text: '6632   powershell.exe       ahmed.m       0.1%   54 MB   <-- simulated suspicious process' },
        { kind: 'muted', text: 'Process names and metrics are fictional; no process is inspected.' },
      ]);
      return;
    }

    if (action === 'netstat') {
      addLines([
        { kind: 'output', text: 'Proto  Local                Remote                State        Process' },
        { kind: 'output', text: 'TCP    10.24.18.47:49812   52.109.8.14:443       ESTABLISHED  chrome.exe' },
        { kind: 'output', text: 'TCP    10.24.18.47:49830   20.190.151.4:443      ESTABLISHED  Teams.exe' },
        { kind: 'warning', text: 'TCP    10.24.18.47:50112   185.220.101.7:8443    SYN_SENT     powershell.exe  <-- simulated C2' },
        { kind: 'muted', text: 'One connection is intentionally suspicious for the exercise. It is not real traffic.' },
      ]);
      return;
    }

    if (action === 'usb') {
      addLines([
        { kind: 'system', text: 'USB-drop timeline (simulated):' },
        { kind: 'output', text: '[09:15] removable media mounted: E:\\ (SanDisk Cruzer Blade)' },
        { kind: 'output', text: '[09:18] file opened: E:\\راتب_الشهر_القادم.pdf' },
        { kind: 'warning', text: '[09:18] telemetry event usb_opened recorded for the campaign' },
        { kind: 'output', text: '[09:18] recipient redirected to /training?channel=usb' },
        { kind: 'muted', text: 'The real exercise uses a safe PDF. No executable and no autorun file is used.' },
      ]);
      return;
    }

    if (action === 'select') {
      const index = Number(argument);
      const target = Number.isInteger(index) ? DEMO_ENDPOINTS[index - 1] : undefined;
      if (!target) {
        addLines([{ kind: 'warning', text: 'usage: select <1-4> — see the endpoint list on the left.' }]);
        return;
      }
      selectEndpoint(target);
      return;
    }

    if (action === 'clear') {
      setLines([]);
      return;
    }

    if (action === 'exit' || action === 'logout') {
      setSessionClosed(true);
      addLines([
        { kind: 'warning', text: 'Closing the simulated session...' },
        { kind: 'muted', text: 'Session closed. No real connection was ever opened.' },
      ]);
      return;
    }

    addLines([
      { kind: 'error', text: `command not found: ${action}` },
      { kind: 'muted', text: 'Type "help" to list the available simulation commands.' },
    ]);
  }

  function runCommand(raw: string) {
    const trimmed = raw.trim();
    if (!trimmed || busy || sessionClosed) return;
    setHistory((current) => [trimmed, ...current].slice(0, 50));
    setHistoryIndex(-1);
    addLines([{ kind: 'command', text: trimmed }]);
    setCommand('');

    const action = trimmed.split(/\s+/)[0]?.toLowerCase();
    if (action === 'clear') {
      setLines([]);
      return;
    }
    if (action === 'exit' || action === 'logout') {
      executeCommand(trimmed);
      return;
    }

    setBusy(true);
    const token = runToken.current;
    window.setTimeout(() => {
      if (runToken.current !== token) return;
      executeCommand(trimmed);
      setBusy(false);
    }, 430);
  }

  function reconnect() {
    runToken.current += 1;
    setSessionClosed(false);
    setLines(bootLines(selected));
    setCommand('');
    addLines([{ kind: 'success', text: `reconnected to ${selected.hostname} (simulation).` }]);
  }

  function handleTerminalKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (history.length === 0) return;
      const next = Math.min(historyIndex + 1, history.length - 1);
      setHistoryIndex(next);
      setCommand(history[next] ?? '');
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (history.length === 0) return;
      const next = Math.max(historyIndex - 1, -1);
      setHistoryIndex(next);
      setCommand(next === -1 ? '' : history[next] ?? '');
    }
  }

  function downloadTranscript() {
    const header = [
      'HUMINT Shield — SOC Simulation Transcript',
      `Endpoint: ${selected.hostname} (${selected.user} / ${selected.username})`,
      `Generated: ${new Date().toISOString()}`,
      'SIMULATION ONLY — no real endpoint was accessed and no command was executed.',
      '',
    ].join('\n');
    const body = lines
      .map((line) => `[${line.time}] ${line.kind.toUpperCase()}: ${line.text}`)
      .join('\n');
    const blob = new Blob([`${header}${body}\n`], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `soc-simulation-${selected.hostname}.txt`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast.success('تم تحميل نص الجلسة.');
  }

  const quickCommands = ['help', 'whoami', 'screenshot', 'lock', 'msg Security alert', 'processes', 'usb', 'clear'];

  return (
    <Box
      sx={{
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 4,
        border: '1px solid rgba(0,240,255,.18)',
        background:
          'radial-gradient(circle at 50% 0%, rgba(0,240,255,.09), transparent 34%), linear-gradient(160deg, #07101d, #050912 62%, #080613)',
        boxShadow: '0 30px 90px rgba(0,0,0,.35)',
      }}
    >
      <MatrixRain opacity={0.14} />

      <Box sx={{ position: 'relative', zIndex: 1, p: { xs: 2, md: 3 } }}>
        <Stack
          direction={{ xs: 'column', xl: 'row' }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', xl: 'center' }}
          spacing={2}
        >
          <Stack direction="row" spacing={1.4} alignItems="flex-start">
            <Box
              sx={{
                width: 52,
                height: 52,
                borderRadius: 2.5,
                display: 'grid',
                placeItems: 'center',
                flex: '0 0 auto',
                color: '#00F0FF',
                bgcolor: 'rgba(0,240,255,.08)',
                border: '1px solid rgba(0,240,255,.28)',
                boxShadow: '0 0 28px rgba(0,240,255,.16)',
              }}
            >
              <Terminal size={26} />
            </Box>
            <Box>
              <Typography
                sx={{
                  fontFamily: 'monospace',
                  fontSize: '0.62rem',
                  letterSpacing: '.18em',
                  color: '#00F0FF',
                  mb: 0.4,
                }}
              >
                INCIDENT RESPONSE SIMULATION
              </Typography>
              <Typography sx={{ fontSize: { xs: '1.35rem', md: '1.75rem' }, fontWeight: 900, lineHeight: 1.35 }}>
                غرفة عمليات SOC — محاكاة تفاعلية
              </Typography>
              <Typography sx={{ color: 'text.secondary', fontSize: '0.8rem', lineHeight: 1.8, mt: 0.5, maxWidth: 780 }}>
                جرّب أوامر التحقيق على أجهزة وهمية، وشاهد لقطة شاشة توضيحية وقفل جهاز
                افتراضي. لا يوجد أي اتصال حقيقي بأي جهاز، وكل ما يحدث هنا هو حالة React
                محلية.
              </Typography>
            </Box>
          </Stack>

          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Button
              variant="outlined"
              startIcon={<ShieldCheck size={16} />}
              onClick={() => changeTab('recommendations')}
            >
              توصيات الأمان
            </Button>
            <Button variant="outlined" color="inherit" startIcon={<RefreshCw size={16} />} onClick={resetDemo}>
              إعادة ضبط
            </Button>
          </Stack>
        </Stack>

        <Stack direction="row" spacing={0.8} useFlexGap flexWrap="wrap" sx={{ mt: 2 }}>
          <Chip
            size="small"
            label="SIMULATION ONLY"
            sx={{
              bgcolor: 'rgba(255,176,32,.10)',
              color: '#FFC857',
              border: '1px solid rgba(255,176,32,.28)',
              fontFamily: 'monospace',
              fontSize: '0.6rem',
              fontWeight: 800,
            }}
          />
          <Chip
            size="small"
            label="NO LIVE ENDPOINTS"
            sx={{ bgcolor: 'rgba(255,255,255,.04)', color: 'text.secondary', fontSize: '0.6rem' }}
          />
          <Chip
            size="small"
            label="AUTHORIZED AWARENESS DEMO"
            sx={{ bgcolor: 'rgba(0,230,118,.07)', color: '#7DFFB2', fontSize: '0.6rem' }}
          />
          <Chip
            size="small"
            icon={<Lock size={12} />}
            label="LOCAL STATE ONLY"
            sx={{ bgcolor: 'rgba(0,240,255,.06)', color: '#8BE9FD', fontSize: '0.6rem' }}
          />
        </Stack>

        <Box
          sx={{
            mt: 2,
            p: 1.4,
            borderRadius: 2,
            border: '1px solid rgba(255,176,32,.22)',
            bgcolor: 'rgba(255,176,32,.045)',
            display: 'flex',
            gap: 1,
            alignItems: 'flex-start',
          }}
        >
          <ShieldAlert size={17} color="#FFC857" style={{ flex: '0 0 auto', marginTop: 2 }} />
          <Typography sx={{ fontSize: '0.7rem', color: 'text.secondary', lineHeight: 1.8 }}>
            <strong style={{ color: '#FFC857' }}>حدود المحاكاة:</strong> الأسماء، عناوين IP،
            العمليات، الاتصالات، ولقطة الشاشة كلها بيانات وهمية. الأوامر لا تُنفّذ على نظامك
            ولا تتصل بالشبكة. لا تستخدم هذه الصفحة لادعاء اختراق حقيقي.
          </Typography>
        </Box>

        <Tabs
          value={tab}
          onChange={(_event, value: SocTab) => changeTab(value)}
          sx={{
            mt: 2.5,
            minHeight: 42,
            borderBottom: '1px solid rgba(255,255,255,.08)',
            '& .MuiTab-root': { minHeight: 42, fontWeight: 800, fontSize: '0.78rem' },
            '& .Mui-selected': { color: '#00F0FF' },
            '& .MuiTabs-indicator': { bgcolor: '#00F0FF', boxShadow: '0 0 12px rgba(0,240,255,.7)' },
          }}
        >
          <Tab icon={<Terminal size={15} />} iconPosition="start" label="SOC Simulation" value="simulation" />
          <Tab
            icon={<ShieldCheck size={15} />}
            iconPosition="start"
            label="Security Recommendations"
            value="recommendations"
          />
        </Tabs>

        {tab === 'recommendations' ? (
          <Box sx={{ mt: 2.5 }}>
            <SecurityRecommendationsPanel />
          </Box>
        ) : (
          <Box sx={{ mt: 2.5 }}>
            <Grid container spacing={2} sx={{ mb: 2 }}>
              <Grid item xs={6} md={3}>
                <StatTile
                  label="أجهزة نشطة"
                  value={DEMO_ENDPOINTS.length}
                  note="كلها وهمية — لا اتصال حقيقي"
                  icon={<Laptop size={18} />}
                  color="#00F0FF"
                />
              </Grid>
              <Grid item xs={6} md={3}>
                <StatTile
                  label="تنبيهات حرجة"
                  value={2}
                  note="تحتاج مراجعة في السيناريو"
                  icon={<ShieldAlert size={18} />}
                  color="#FF1744"
                />
              </Grid>
              <Grid item xs={6} md={3}>
                <StatTile
                  label="اتصالات C2 محجوبة"
                  value={37}
                  note="آخر 24 ساعة (محاكاة)"
                  icon={<Wifi size={18} />}
                  color="#00E676"
                />
              </Grid>
              <Grid item xs={6} md={3}>
                <StatTile
                  label="مدة الجلسة"
                  value={uptime}
                  note="منذ فتح الصفحة"
                  icon={<Clock3 size={18} />}
                  color="#FFC857"
                />
              </Grid>
            </Grid>

            <Grid container spacing={2}>
              <Grid item xs={12} lg={4}>
                <Card sx={{ height: '100%', border: '1px solid rgba(255,255,255,.07)' }}>
                  <CardContent sx={{ p: 2 }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Box>
                        <Typography sx={{ fontWeight: 900, fontSize: '0.92rem' }}>Active Endpoints</Typography>
                        <Typography sx={{ fontSize: '0.62rem', color: 'text.secondary', mt: 0.2 }}>
                          أجهزة افتراضية للتدريب
                        </Typography>
                      </Box>
                      <Chip
                        size="small"
                        label="4 / 4 ONLINE"
                        sx={{ height: 20, bgcolor: 'rgba(0,230,118,.08)', color: '#7DFFB2', fontSize: '0.54rem' }}
                      />
                    </Stack>

                    <Stack spacing={1} sx={{ mt: 1.8 }}>
                      {DEMO_ENDPOINTS.map((endpoint) => (
                        <EndpointRow
                          key={endpoint.id}
                          endpoint={endpoint}
                          selected={endpoint.id === selectedId}
                          locked={lockedIds.has(endpoint.id)}
                          onSelect={() => selectEndpoint(endpoint)}
                        />
                      ))}
                    </Stack>

                    <Divider sx={{ my: 1.6, borderColor: 'rgba(255,255,255,.07)' }} />

                    <Stack direction="row" spacing={0.8} useFlexGap flexWrap="wrap">
                      <Chip size="small" label="TLS 1.3" sx={{ height: 19, fontSize: '0.54rem', bgcolor: 'rgba(255,255,255,.035)' }} />
                      <Chip size="small" label="beacon 60s" sx={{ height: 19, fontSize: '0.54rem', bgcolor: 'rgba(255,255,255,.035)' }} />
                      <Chip size="small" label="EDR simulated" sx={{ height: 19, fontSize: '0.54rem', bgcolor: 'rgba(255,255,255,.035)' }} />
                    </Stack>
                    <Typography sx={{ fontSize: '0.58rem', color: 'text.disabled', lineHeight: 1.7, mt: 1.2 }}>
                      أسماء الموظفين والأجهزة وهمية. لا تتصل هذه الصفحة بأي وكيل أو شبكة.
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} lg={8}>
                <Card sx={{ border: '1px solid rgba(0,240,255,.16)', overflow: 'hidden' }}>
                  <Box
                    sx={{
                      px: 1.5,
                      py: 1.1,
                      bgcolor: 'rgba(4,8,15,.92)',
                      borderBottom: '1px solid rgba(255,255,255,.08)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1,
                      flexWrap: 'wrap',
                    }}
                  >
                    <Stack direction="row" spacing={0.6} alignItems="center">
                      <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#FF5F57' }} />
                      <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#FEBC2E' }} />
                      <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: '#28C840' }} />
                    </Stack>
                    <Terminal size={14} color="#00F0FF" />
                    <Typography dir="ltr" sx={{ fontFamily: 'monospace', fontSize: '0.66rem', color: '#A9C7E8' }}>
                      root@soc-console:~#
                    </Typography>
                    <Chip
                      size="small"
                      label={`${selected.hostname} · ${selected.status === 'online' ? 'online' : 'idle'}`}
                      sx={{ height: 19, bgcolor: 'rgba(0,240,255,.07)', color: '#8BE9FD', fontSize: '0.54rem' }}
                    />
                    <Box sx={{ flex: 1 }} />
                    <Tooltip title="تحميل نص الجلسة">
                      <IconButton size="small" onClick={downloadTranscript} aria-label="تحميل نص الجلسة">
                        <Download size={15} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="مسح الطرفية">
                      <IconButton size="small" onClick={() => setLines([])} aria-label="مسح الطرفية">
                        <Trash2 size={15} />
                      </IconButton>
                    </Tooltip>
                  </Box>

                  {locked ? (
                    <Box
                      sx={{
                        px: 1.5,
                        py: 1,
                        bgcolor: 'rgba(255,23,68,.12)',
                        borderBottom: '1px solid rgba(255,23,68,.28)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 1,
                        flexWrap: 'wrap',
                      }}
                    >
                      <Lock size={15} color="#FF6B81" />
                      <Typography sx={{ fontSize: '0.7rem', color: '#FF8A9A', fontWeight: 800 }}>
                        ENDPOINT LOCKED — تم قفل الجهاز (محاكاة)
                      </Typography>
                      <Box sx={{ flex: 1 }} />
                      <Button size="small" color="error" variant="contained" startIcon={<Unlock size={13} />} onClick={unlockEndpoint}>
                        Restore
                      </Button>
                    </Box>
                  ) : null}

                  <Box
                    ref={terminalRef}
                    dir="ltr"
                    sx={{
                      height: { xs: 330, sm: 390 },
                      overflowY: 'auto',
                      bgcolor: '#03070d',
                      p: 1.5,
                      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                      fontSize: { xs: '0.66rem', sm: '0.72rem' },
                      lineHeight: 1.85,
                      backgroundImage:
                        'repeating-linear-gradient(0deg, rgba(0,240,255,.018) 0px, rgba(0,240,255,.018) 1px, transparent 1px, transparent 3px)',
                    }}
                  >
                    {lines.length === 0 ? (
                      <Typography sx={{ color: '#5F7188', fontSize: '0.68rem' }}>
                        terminal cleared — type &quot;help&quot; to reconnect the simulation.
                      </Typography>
                    ) : (
                      lines.map((line) => (
                        <Box key={line.id} sx={{ display: 'flex', gap: 0.9, alignItems: 'flex-start' }}>
                          <Box component="span" sx={{ color: '#3D5068', flex: '0 0 auto' }}>
                            {line.time}
                          </Box>
                          <Box
                            component="span"
                            sx={{
                              color: LINE_COLORS[line.kind],
                              fontWeight: line.kind === 'command' ? 800 : 500,
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                            }}
                          >
                            {line.kind === 'command' ? '❯ ' : ''}
                            {line.text}
                          </Box>
                        </Box>
                      ))
                    )}
                    {busy ? (
                      <Box sx={{ display: 'flex', gap: 0.8, alignItems: 'center', color: '#00F0FF', mt: 0.4 }}>
                        <CircularProgress size={10} color="inherit" />
                        <span>executing simulated command…</span>
                      </Box>
                    ) : null}
                    <Box sx={{ display: 'flex', gap: 0.7, alignItems: 'center', mt: 0.6, color: '#00E676' }}>
                      <span>{sessionClosed ? 'session closed' : 'ready'}</span>
                      <Box component="span" sx={{ animation: 'mc-blink 1s steps(1) infinite' }}>
                        ▌
                      </Box>
                    </Box>
                  </Box>

                  <Box sx={{ p: 1.2, borderTop: '1px solid rgba(255,255,255,.08)', bgcolor: 'rgba(4,8,15,.92)' }}>
                    <Box
                      component="form"
                      onSubmit={(event) => {
                        event.preventDefault();
                        runCommand(command);
                      }}
                      sx={{ display: 'flex', alignItems: 'center', gap: 0.8 }}
                    >
                      <Typography dir="ltr" sx={{ fontFamily: 'monospace', color: '#00F0FF', fontSize: '0.8rem' }}>
                        ❯
                      </Typography>
                      <TextField
                        fullWidth
                        size="small"
                        variant="standard"
                        value={command}
                        onChange={(event) => setCommand(event.target.value)}
                        onKeyDown={handleTerminalKeyDown}
                        disabled={busy || sessionClosed}
                        placeholder={sessionClosed ? 'session closed — press Reconnect' : 'type a command… (help)'}
                        InputProps={{ disableUnderline: true }}
                        inputProps={{
                          'aria-label': 'SOC simulation command',
                          style: {
                            fontFamily:
                              'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                            fontSize: '0.72rem',
                            color: '#E2E8F0',
                          },
                        }}
                      />
                      {sessionClosed ? (
                        <Button size="small" variant="outlined" startIcon={<Power size={13} />} onClick={reconnect}>
                          Reconnect
                        </Button>
                      ) : (
                        <IconButton type="submit" size="small" disabled={busy || !command.trim()} aria-label="تنفيذ الأمر">
                          <Play size={15} />
                        </IconButton>
                      )}
                    </Box>

                    <Stack direction="row" spacing={0.7} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                      {quickCommands.map((quick) => (
                        <Chip
                          key={quick}
                          size="small"
                          label={quick}
                          clickable
                          disabled={busy || sessionClosed}
                          onClick={() => runCommand(quick)}
                          sx={{
                            height: 21,
                            fontSize: '0.56rem',
                            fontFamily: 'monospace',
                            bgcolor: 'rgba(255,255,255,.035)',
                            border: '1px solid rgba(255,255,255,.07)',
                          }}
                        />
                      ))}
                    </Stack>
                    <Typography sx={{ fontSize: '0.56rem', color: 'text.disabled', mt: 1 }}>
                      استخدم ↑ / ↓ لاستعراض الأوامر. لا يُنفّذ أي أمر على نظامك.
                    </Typography>
                  </Box>
                </Card>

                <AnimatePresence>
                  {screenshotOpen ? (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: 8 }}
                      transition={{ duration: 0.24 }}
                    >
                      <SimulatedScreenshot
                        endpoint={selected}
                        locked={locked}
                        alertMessage={alertMessage}
                        onClose={() => setScreenshotOpen(false)}
                        onUnlock={unlockEndpoint}
                        onClearAlert={() => setAlertMessage(null)}
                      />
                    </motion.div>
                  ) : null}
                </AnimatePresence>

                <Stack direction="row" spacing={0.8} alignItems="center" sx={{ mt: 1.2, color: 'text.disabled' }}>
                  <Activity size={13} />
                  <Typography sx={{ fontSize: '0.6rem' }}>
                    Telemetry is generated locally. No WebSocket, EDR agent, or remote shell is used.
                  </Typography>
                </Stack>
              </Grid>
            </Grid>
          </Box>
        )}
      </Box>
    </Box>
  );
}
