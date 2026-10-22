/** 404 page shown for unmatched routes. */
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { Link as RouterLink } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <Stack spacing={2} alignItems="center" sx={{ py: 10 }}>
      <Typography variant="h1">404</Typography>
      <Typography variant="h3" sx={{ fontSize: '1.1rem' }}>
        Page not found
      </Typography>
      <Typography color="text.secondary" variant="body2" textAlign="center">
        The page you requested does not exist or has moved.
      </Typography>
      <Button variant="contained" component={RouterLink} to="/">
        Back to dashboard
      </Button>
    </Stack>
  );
}
