/** Compact glass KPI card used on campaign detail pages. */
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import { motion } from 'framer-motion';

interface StatCardProps {
  label: string;
  value: string | number;
  helper?: string;
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'error';
}

const TONE_COLORS: Record<NonNullable<StatCardProps['tone']>, string> = {
  default: '#E2E8F0',
  primary: '#00F0FF',
  success: '#00E676',
  warning: '#FFB020',
  error: '#FF1744',
};

export function StatCard({ label, value, helper, tone = 'default' }: StatCardProps) {
  const color = TONE_COLORS[tone];
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      style={{ height: '100%' }}
    >
      <Card
        sx={{
          height: '100%',
          borderColor: alpha(color, 0.16),
          '&:hover': {
            borderColor: alpha(color, 0.38),
            boxShadow: `0 24px 60px rgba(0,0,0,.4), 0 0 28px ${alpha(color, 0.12)}`,
          },
        }}
      >
        <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
          <Stack spacing={0.55}>
            <Typography variant="overline" sx={{ color: 'text.secondary', fontSize: '0.62rem' }}>
              {label}
            </Typography>
            <Typography
              variant="h4"
              sx={{ color, fontWeight: 800, fontSize: '1.7rem', textShadow: `0 0 24px ${alpha(color, 0.28)}` }}
            >
              {value}
            </Typography>
            {helper ? (
              <Typography variant="caption" color="text.secondary">
                {helper}
              </Typography>
            ) : null}
          </Stack>
        </CardContent>
        <Box
          sx={{
            position: 'absolute',
            insetInline: 0,
            bottom: 0,
            height: 2,
            background: `linear-gradient(90deg, transparent, ${color}, transparent)`,
            opacity: 0.45,
          }}
        />
      </Card>
    </motion.div>
  );
}
