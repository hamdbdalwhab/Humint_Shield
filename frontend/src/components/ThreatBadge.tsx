/**
 * Threat badge derived from the employee's independent Elo rating.
 *
 * The backend is the source of truth (`threat_level` is a computed field); this
 * component only maps the four stable values to a consistent colour and label.
 */
import Chip from '@mui/material/Chip';
import type { ChipProps } from '@mui/material/Chip';

import type { ThreatLevel } from '@/types';

export const THREAT_LABELS: Record<ThreatLevel, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};

const THREAT_COLORS: Record<ThreatLevel, ChipProps['color']> = {
  low: 'success',
  medium: 'info',
  high: 'warning',
  critical: 'error',
};

const THREAT_BACKGROUNDS: Record<ThreatLevel, string> = {
  low: 'rgba(5,150,105,.12)',
  medium: 'rgba(37,99,235,.12)',
  high: 'rgba(217,119,6,.14)',
  critical: 'rgba(220,38,38,.14)',
};

export function ThreatBadge({
  level,
  size = 'small',
}: {
  level: ThreatLevel | null | undefined;
  size?: 'small' | 'medium';
}) {
  if (!level) return <Chip size={size} label="—" variant="outlined" />;
  return (
    <Chip
      size={size}
      color={THREAT_COLORS[level]}
      label={THREAT_LABELS[level]}
      sx={{
        fontWeight: 800,
        letterSpacing: '.02em',
        bgcolor: THREAT_BACKGROUNDS[level],
        border: '1px solid currentColor',
      }}
    />
  );
}
