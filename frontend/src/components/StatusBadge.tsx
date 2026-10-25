/** Glowing pill badges for campaign and engagement status. */
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import { alpha } from '@mui/material/styles';
import type { CampaignStatus, EngagementStatus } from '@/types';

const CAMPAIGN_COLORS: Record<CampaignStatus, 'default' | 'info' | 'success' | 'error'> = {
  draft: 'default',
  active: 'info',
  completed: 'success',
  aborted: 'error',
};

const CAMPAIGN_ACCENT: Record<CampaignStatus, string> = {
  draft: '#8B9BB4',
  active: '#00F0FF',
  completed: '#00E676',
  aborted: '#FF1744',
};

const ENGAGEMENT_COLORS: Record<
  EngagementStatus,
  'default' | 'info' | 'warning' | 'success' | 'error'
> = {
  pending: 'default',
  sent: 'default',
  opened: 'info',
  clicked: 'warning',
  submitted: 'error',
  completed: 'success',
  reported_safe: 'success',
  failed: 'error',
};

const ENGAGEMENT_ACCENT: Record<EngagementStatus, string> = {
  pending: '#8B9BB4',
  sent: '#38BDF8',
  opened: '#38BDF8',
  clicked: '#FFB020',
  submitted: '#FF1744',
  completed: '#00E676',
  reported_safe: '#FFD54F',
  failed: '#FF1744',
};

function Dot({ color }: { color: string }) {
  return (
    <Box
      component="span"
      sx={{
        width: 6,
        height: 6,
        borderRadius: '50%',
        bgcolor: color,
        boxShadow: `0 0 8px ${color}`,
        ml: 0.75,
      }}
    />
  );
}

export function CampaignStatusBadge({ status }: { status: CampaignStatus }) {
  const accent = CAMPAIGN_ACCENT[status];
  return (
    <Chip
      size="small"
      icon={<Dot color={accent} />}
      label={status.toUpperCase()}
      color={CAMPAIGN_COLORS[status]}
      sx={{
        fontWeight: 800,
        letterSpacing: '.04em',
        fontSize: '0.64rem',
        boxShadow: `0 0 16px ${alpha(accent, 0.14)}`,
      }}
    />
  );
}

export function EngagementStatusBadge({ status }: { status: EngagementStatus }) {
  const accent = ENGAGEMENT_ACCENT[status];
  return (
    <Chip
      size="small"
      variant="outlined"
      icon={<Dot color={accent} />}
      label={status === 'reported_safe' ? 'REPORTED SAFE' : status}
      color={ENGAGEMENT_COLORS[status]}
      sx={{
        fontWeight: 700,
        textTransform: 'capitalize',
        ...(status === 'reported_safe'
          ? {
              color: '#FFD54F',
              borderColor: 'rgba(255,213,79,.45)',
              bgcolor: 'rgba(255,213,79,.06)',
            }
          : {}),
        boxShadow: `0 0 14px ${alpha(accent, 0.10)}`,
      }}
    />
  );
}
