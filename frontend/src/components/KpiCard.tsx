/** Floating KPI tile with a real 7-day sparkline and an optional live pulse. */
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { alpha, useTheme } from '@mui/material/styles';
import { motion } from 'framer-motion';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import type { ReactNode } from 'react';

export type KpiTone = 'cyan' | 'violet' | 'green' | 'red' | 'amber' | 'blue';

const TONE: Record<KpiTone, string> = {
  cyan: '#00F0FF',
  violet: '#B388FF',
  green: '#00E676',
  red: '#FF1744',
  amber: '#FFB020',
  blue: '#38BDF8',
};

interface KpiCardProps {
  label: string;
  value: string | number;
  helper?: string;
  icon: ReactNode;
  data: number[];
  tone?: KpiTone;
  pulse?: boolean;
  suffix?: string;
}

export function KpiCard({
  label,
  value,
  helper,
  icon,
  data,
  tone = 'cyan',
  pulse = false,
  suffix,
}: KpiCardProps) {
  const theme = useTheme();
  const color = TONE[tone];
  // Recharts renders left-to-right by default; feed it the series in reverse so
  // the newest point sits on the left, matching the RTL reading direction.
  const series = (data.length >= 2 ? [...data].reverse() : [0, 0]).map((item, index) => ({
    index,
    value: item,
  }));
  const gradientId = `kpi-${tone}-${label.replace(/\s+/g, '-')}`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -4 }}
      style={{ height: '100%' }}
    >
      <Card
        className={pulse ? 'mc-pulse-ring' : undefined}
        sx={{
          height: '100%',
          borderColor: alpha(color, 0.20),
          '&:hover': {
            borderColor: alpha(color, 0.52),
            boxShadow: `0 28px 70px rgba(0,0,0,.48), 0 0 38px ${alpha(color, 0.18)}`,
          },
        }}
      >
        <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
          <Stack direction="row" alignItems="flex-start" justifyContent="space-between">
            <Box>
              <Typography
                variant="overline"
                sx={{ color: 'text.secondary', display: 'block', mb: 0.5 }}
              >
                {label}
              </Typography>
              <Stack direction="row" alignItems="baseline" spacing={0.5}>
                <Typography
                  variant="h4"
                  sx={{
                    color,
                    textShadow: `0 0 26px ${alpha(color, 0.35)}`,
                    lineHeight: 1.1,
                  }}
                >
                  {value}
                </Typography>
                {suffix ? (
                  <Typography variant="body2" sx={{ color: alpha(color, 0.8), fontWeight: 700 }}>
                    {suffix}
                  </Typography>
                ) : null}
              </Stack>
            </Box>
            <Box
              sx={{
                width: 42,
                height: 42,
                borderRadius: 2.5,
                display: 'grid',
                placeItems: 'center',
                color,
                bgcolor: alpha(color, 0.10),
                border: `1px solid ${alpha(color, 0.25)}`,
                boxShadow: `0 0 24px ${alpha(color, 0.12)}`,
                '& svg': { width: 20, height: 20 },
              }}
            >
              {icon}
            </Box>
          </Stack>

          <Box className="mc-sparkline" sx={{ height: 52, mt: 1.25, mx: -0.5 }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={series} margin={{ top: 4, right: 2, bottom: 0, left: 2 }}>
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke={color}
                  strokeWidth={2}
                  fill={`url(#${gradientId})`}
                  isAnimationActive
                  animationDuration={900}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </Box>

          {helper ? (
            <Typography
              variant="caption"
              sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}
            >
              {helper}
            </Typography>
          ) : (
            <Box sx={{ height: 18 }} />
          )}
        </CardContent>
        <Box
          sx={{
            position: 'absolute',
            insetInline: 0,
            bottom: 0,
            height: 2,
            background: `linear-gradient(90deg, transparent, ${color}, transparent)`,
            opacity: 0.55,
          }}
        />
        {pulse && theme.palette.mode === 'dark' ? (
          <Box
            className="mc-live-dot mc-danger-dot"
            sx={{ position: 'absolute', top: 14, insetInlineStart: 14 }}
          />
        ) : null}
      </Card>
    </motion.div>
  );
}
