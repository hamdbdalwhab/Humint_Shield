/** Consistent page header with a neon section marker and action slot. */
import Box from '@mui/material/Box';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type { ReactNode } from 'react';

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  eyebrow?: string;
}

export function PageHeader({ title, subtitle, actions, eyebrow = 'HUMINT SHIELD · OPERATIONS' }: PageHeaderProps) {
  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      justifyContent="space-between"
      alignItems={{ xs: 'flex-start', sm: 'center' }}
      spacing={2}
      sx={{ mb: 2.75 }}
    >
      <Stack spacing={0.6}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Box
            sx={{
              width: 3,
              height: 16,
              borderRadius: 99,
              background: 'linear-gradient(180deg, #00F0FF, #7000FF)',
              boxShadow: '0 0 14px rgba(0,240,255,.55)',
            }}
          />
          <Typography
            variant="overline"
            sx={{ color: 'primary.main', fontSize: '0.62rem', letterSpacing: '.16em' }}
          >
            {eyebrow}
          </Typography>
        </Stack>
        <Typography
          variant="h2"
          component="h1"
          sx={{ fontSize: { xs: '1.5rem', md: '1.85rem' }, lineHeight: 1.25 }}
        >
          {title}
        </Typography>
        {subtitle ? (
          <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 820 }}>
            {subtitle}
          </Typography>
        ) : null}
      </Stack>
      {actions}
    </Stack>
  );
}
