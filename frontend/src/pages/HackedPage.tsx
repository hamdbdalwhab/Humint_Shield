/**
 * Post-submission attack-chain reveal.
 *
 * The recipient has just typed credentials into the simulated form. This page
 * makes the consequence tangible: a terminal types out the steps an attacker
 * would run, then a hard stop after five seconds explains that nothing was
 * really compromised and routes the recipient into the training experience.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { motion } from 'framer-motion';
import { ArrowLeft, ShieldAlert, Terminal, TriangleAlert } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { trackingApi } from '@/api/endpoints';

const TERMINAL_LINES = [
  '$ ./simulate_attack --target employee',
  'Bypassing firewall...',
  'Extracting credentials...',
  'Accessing HR database...',
  'Downloading 5GB of files...',
];

const FULL_SCRIPT = TERMINAL_LINES.join('\n');

/** Deterministic-enough glyph columns; they are decorative only. */
const GLYPHS = '01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホ';

function MatrixRain() {
  const columns = useMemo(
    () =>
      Array.from({ length: 26 }, (_, index) => ({
        left: `${(index / 26) * 100}%`,
        delay: `${(index % 9) * 0.42}s`,
        duration: `${4.5 + (index % 5) * 0.8}s`,
        text: Array.from({ length: 28 }, (_, glyphIndex) =>
          GLYPHS[(index * 7 + glyphIndex * 3) % GLYPHS.length],
        ).join('\n'),
      })),
    [],
  );

  return (
    <Box
      aria-hidden
      sx={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        pointerEvents: 'none',
        opacity: 0.22,
        '&::after': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(circle at 50% 30%, transparent 0%, rgba(1,5,10,.55) 70%, rgba(1,5,10,.94) 100%)',
        },
      }}
    >
      <Box
        component="style"
        dangerouslySetInnerHTML={{
          __html:
            '@keyframes hacked-matrix-fall { from { transform: translateY(-110%); } to { transform: translateY(110vh); } }' +
            '@keyframes hacked-pulse { 0%,100% { opacity: 1; } 50% { opacity: .28; } }',
        }}
      />
      {columns.map((column) => (
        <Box
          key={column.left}
          component="pre"
          sx={{
            position: 'absolute',
            top: 0,
            left: column.left,
            m: 0,
            color: '#35FF9A',
            fontFamily: 'Consolas, "Courier New", monospace',
            fontSize: 13,
            lineHeight: 1.15,
            textShadow: '0 0 12px rgba(53,255,154,.55)',
            animation: `hacked-matrix-fall ${column.duration} linear ${column.delay} infinite`,
          }}
        >
          {column.text}
        </Box>
      ))}
    </Box>
  );
}

export function HackedPage() {
  const { trackingUuid } = useParams<{ trackingUuid: string }>();
  const navigate = useNavigate();
  const [visibleChars, setVisibleChars] = useState(0);
  const [interrupted, setInterrupted] = useState(false);

  const contextQuery = useQuery({
    queryKey: ['tracking-context', trackingUuid],
    queryFn: () => trackingApi.context(trackingUuid as string),
    enabled: Boolean(trackingUuid),
    staleTime: 30_000,
    retry: 1,
  });

  useEffect(() => {
    if (!trackingUuid || contextQuery.isLoading || contextQuery.isError) return undefined;
    const typing = window.setInterval(() => {
      setVisibleChars((current) => {
        if (current >= FULL_SCRIPT.length) {
          window.clearInterval(typing);
          return current;
        }
        return current + 1;
      });
    }, 22);
    const stop = window.setTimeout(() => setInterrupted(true), 5_000);
    return () => {
      window.clearInterval(typing);
      window.clearTimeout(stop);
    };
  }, [trackingUuid, contextQuery.isError, contextQuery.isLoading]);

  const visible = FULL_SCRIPT.slice(0, visibleChars);
  const finishedTyping = visibleChars >= FULL_SCRIPT.length;

  if (contextQuery.isLoading) {
    return (
      <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: '#02070d' }}>
        <Stack alignItems="center" spacing={2}>
          <CircularProgress sx={{ color: '#35FF9A' }} />
          <Typography sx={{ color: '#8AA39B', fontFamily: 'Consolas, monospace', fontSize: 13 }}>
            Establishing simulated session…
          </Typography>
        </Stack>
      </Box>
    );
  }

  if (contextQuery.isError || !trackingUuid) {
    return (
      <Box
        sx={{
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          p: 2,
          bgcolor: '#02070d',
        }}
      >
        <Box
          sx={{
            maxWidth: 460,
            p: 4,
            borderRadius: 3,
            textAlign: 'center',
            bgcolor: 'rgba(15,23,42,.9)',
            border: '1px solid rgba(255,23,68,.3)',
          }}
        >
          <ShieldAlert size={42} color="#FF1744" />
          <Typography sx={{ color: '#F8FAFC', fontWeight: 800, mt: 2, mb: 1 }}>
            رابط المحاكاة غير معروف
          </Typography>
          <Typography sx={{ color: '#94A3B8', fontSize: 14 }}>
            هذا الرابط غير صالح أو انتهت صلاحيته. تواصل مع فريق الأمن السيبراني في مؤسستك.
          </Typography>
        </Box>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        position: 'relative',
        minHeight: '100vh',
        overflow: 'hidden',
        bgcolor: '#02070d',
        color: '#D7FFE7',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        p: { xs: 2, sm: 3 },
      }}
    >
      <MatrixRain />
      <Box
        sx={{
          position: 'absolute',
          width: 680,
          height: 680,
          borderRadius: '50%',
          top: -360,
          left: -220,
          background: 'radial-gradient(circle, rgba(0,255,140,.12), transparent 66%)',
          pointerEvents: 'none',
        }}
      />

      <Stack spacing={2.2} sx={{ position: 'relative', zIndex: 1, width: '100%', maxWidth: 860 }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2}>
          <Stack direction="row" alignItems="center" spacing={1}>
            <Box
              sx={{
                width: 38,
                height: 38,
                borderRadius: 2,
                display: 'grid',
                placeItems: 'center',
                bgcolor: 'rgba(53,255,154,.1)',
                border: '1px solid rgba(53,255,154,.28)',
                color: '#35FF9A',
              }}
            >
              <Terminal size={20} />
            </Box>
            <Box>
              <Typography sx={{ fontWeight: 900, letterSpacing: '.08em', fontSize: 13, color: '#35FF9A' }}>
                HUMINT // ATTACK CHAIN
              </Typography>
              <Typography sx={{ fontSize: 11, color: '#64748B', fontFamily: 'Consolas, monospace' }}>
                authorized simulation · {trackingUuid.slice(0, 8)}
              </Typography>
            </Box>
          </Stack>
          <Chip
            size="small"
            label={interrupted ? 'TERMINATED' : 'LIVE'}
            sx={{
              fontFamily: 'Consolas, monospace',
              fontWeight: 900,
              letterSpacing: '.08em',
              color: interrupted ? '#FCA5A5' : '#35FF9A',
              bgcolor: interrupted ? 'rgba(239,68,68,.12)' : 'rgba(53,255,154,.1)',
              border: `1px solid ${interrupted ? 'rgba(239,68,68,.4)' : 'rgba(53,255,154,.3)'}`,
            }}
          />
        </Stack>

        <Box
          sx={{
            borderRadius: 3,
            overflow: 'hidden',
            border: '1px solid rgba(53,255,154,.22)',
            background: 'linear-gradient(180deg, rgba(4,15,17,.97), rgba(2,8,12,.98))',
            boxShadow: '0 35px 110px rgba(0,0,0,.7), 0 0 55px rgba(53,255,154,.06)',
          }}
        >
          <Stack
            direction="row"
            alignItems="center"
            spacing={0.7}
            sx={{ px: 2, py: 1.15, borderBottom: '1px solid rgba(53,255,154,.13)' }}
          >
            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#EF4444' }} />
            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#F59E0B' }} />
            <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: '#22C55E' }} />
            <Typography
              sx={{
                ml: 1,
                fontSize: 11,
                color: '#64748B',
                fontFamily: 'Consolas, monospace',
                letterSpacing: '.04em',
              }}
            >
              root@hument-sim: ~/attack
            </Typography>
          </Stack>
          <Box
            sx={{
              p: { xs: 2.2, sm: 3.2 },
              minHeight: { xs: 330, sm: 360 },
              direction: 'ltr',
              textAlign: 'left',
            }}
          >
            <Typography
              component="pre"
              dir="ltr"
              style={{ direction: 'ltr', textAlign: 'left', unicodeBidi: 'plaintext' }}
              sx={{
                m: 0,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                fontFamily: 'Consolas, "Courier New", monospace',
                fontSize: { xs: 12, sm: 14 },
                lineHeight: 1.85,
                color: '#8CFFC0',
                textShadow: '0 0 14px rgba(53,255,154,.18)',
              }}
            >
              {visible}
              {!finishedTyping ? (
                <Box component="span" sx={{ color: '#35FF9A' }}>
                  ▌
                </Box>
              ) : null}
            </Typography>
          </Box>
        </Box>

        {interrupted ? (
          <motion.div
            initial={{ opacity: 0, y: 18, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.35 }}
          >
            <Alert
              severity="error"
              icon={<TriangleAlert size={26} />}
              sx={{
                alignItems: 'flex-start',
                borderRadius: 3,
                border: '1px solid rgba(248,113,113,.45)',
                bgcolor: 'rgba(127,29,29,.36)',
                color: '#FEE2E2',
                '& .MuiAlert-message': { width: '100%' },
                '& .MuiAlert-icon': { color: '#F87171' },
              }}
            >
              <Typography
                dir="ltr"
                style={{ direction: 'ltr', textAlign: 'left' }}
                sx={{
                  fontWeight: 900,
                  fontSize: { xs: 16, sm: 19 },
                  lineHeight: 1.5,
                }}
              >
                STOP! This was a simulation. In a real attack, your credentials would have caused this damage.
              </Typography>
              <Typography sx={{ mt: 0.8, fontSize: 13, color: '#FECACA' }}>
                توقفت المحاكاة. في هجوم حقيقي، كانت بياناتك ستُستخدم للوصول إلى أنظمة المؤسسة وبيانات
                الموظفين. لم يتم حفظ كلمة المرور كنص واضح، وستتعرّف الآن على ما كان يمكن أن يحدث.
              </Typography>
              <Button
                variant="contained"
                color="error"
                endIcon={<ArrowLeft size={17} />}
                onClick={() =>
                  navigate(`/training-experience/${trackingUuid}`, { replace: true })
                }
                sx={{ mt: 1.6, fontWeight: 900, borderRadius: 2 }}
              >
                متابعة إلى التدريب
              </Button>
            </Alert>
          </motion.div>
        ) : (
          <Stack direction="row" alignItems="center" spacing={1}>
            <Box
              sx={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                bgcolor: '#35FF9A',
                boxShadow: '0 0 12px #35FF9A',
                animation: 'hacked-pulse 1s ease-in-out infinite',
              }}
            />
            <Typography sx={{ fontSize: 12, color: '#64748B', fontFamily: 'Consolas, monospace' }}>
              Simulated attack in progress. No real systems are being accessed.
            </Typography>
          </Stack>
        )}
      </Stack>
    </Box>
  );
}
