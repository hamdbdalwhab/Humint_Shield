/**
 * Immediate micro-learning page.
 *
 * This is the educational landing page every simulated email link resolves to.
 * It is intentionally public (no admin chrome, no authentication) so that a
 * recipient who clicks a tracking link always sees the disclosure, the red
 * flags they missed, protective best practices and a 60-second countdown
 * before the completion action unlocks.
 *
 * The page is also reachable as an SPA route (`/training/:trackingUuid`) for
 * single-origin deployments; the backend additionally serves a standalone
 * HTML version at the same path for email clients and hardened environments.
 */
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Container from '@mui/material/Container';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ShieldIcon from '@mui/icons-material/Shield';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';

import { API_BASE_URL } from '@/api/client';
import type { TrackingCompleteResponse } from '@/types';

/** Seconds the recipient must spend reading before completion unlocks. */
const COUNTDOWN_SECONDS = 60;

interface RedFlag {
  title: string;
  detail: string;
}

const RED_FLAGS: RedFlag[] = [
  {
    title: "The sender's domain did not match the organization",
    detail:
      "Legitimate IT, HR and Finance mail comes from your organization's real domain. " +
      'Attackers register look-alike domains (for example acme-corp.net instead of acme.com).',
  },
  {
    title: 'The link destination did not match the link text',
    detail:
      'Hovering over a link reveals its true destination. In this email the anchor text ' +
      'described a document or form, but the target address pointed somewhere else.',
  },
  {
    title: 'The message used urgency and threats',
    detail:
      "Phrases such as 'within 24 hours', 'immediate action' or 'your account will be " +
      "locked' are engineered to stop you from thinking critically.",
  },
  {
    title: 'It asked for sensitive information or action',
    detail:
      'No legitimate service asks you to re-enter credentials, confirm bank details or ' +
      'approve payments through an emailed link.',
  },
];

const BEST_PRACTICES: string[] = [
  "Stop and read the sender's full email address, not just the display name.",
  'Hover over every link and confirm the destination domain before clicking.',
  'Treat unexpected urgency as a warning sign, not a reason to hurry.',
  'Never enter credentials from a link in an email — navigate to the site directly.',
  'Verify unusual requests through a second, known-good channel (a phone call).',
  "Report suspicious messages using your organization's report button.",
];

/** Build an absolute URL for a tracking endpoint from the configured API base. */
function apiUrl(path: string): string {
  const base = API_BASE_URL === '/' ? '' : API_BASE_URL.replace(/\/$/, '');
  return `${base}${path}`;
}

export function TrainingPage() {
  const { trackingUuid } = useParams<{ trackingUuid: string }>();
  const [remaining, setRemaining] = useState(COUNTDOWN_SECONDS);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<TrackingCompleteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ready = remaining <= 0;
  const progress = useMemo(
    () => ((COUNTDOWN_SECONDS - remaining) / COUNTDOWN_SECONDS) * 100,
    [remaining],
  );

  // Countdown ticker. The interval is cleared as soon as it reaches zero.
  useEffect(() => {
    if (remaining <= 0) return undefined;
    const handle = window.setInterval(() => {
      setRemaining((value) => (value <= 1 ? 0 : value - 1));
    }, 1000);
    return () => window.clearInterval(handle);
  }, [remaining]);

  const complete = useCallback(async () => {
    if (!trackingUuid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/track/complete/${trackingUuid}`), {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`The server responded with ${response.status}.`);
      }
      const data = (await response.json()) as TrackingCompleteResponse;
      setResult(data);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to record completion.');
    } finally {
      setSubmitting(false);
    }
  }, [submitting, trackingUuid]);

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <Box sx={{ bgcolor: 'success.main', color: '#fff', py: 3, px: 2 }}>
        <Container maxWidth="md">
          <Stack direction="row" spacing={1.5} alignItems="center">
            <CheckCircleIcon aria-hidden />
            <Typography variant="h2" sx={{ color: '#fff', fontSize: '1.3rem' }}>
              This was a training exercise
            </Typography>
          </Stack>
          <Typography variant="body2" sx={{ mt: 0.5, opacity: 0.95 }}>
            No data was compromised. This message was an authorized simulation run by your
            organization to help you recognise phishing.
          </Typography>
        </Container>
      </Box>

      <Container maxWidth="md" sx={{ py: 4 }}>
        <Stack spacing={3}>
          <Card>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                <ShieldIcon color="primary" />
                <Typography variant="h3" sx={{ fontSize: '1.1rem' }}>
                  You just took part in a simulation
                </Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary">
                This is measured training: the goal is to build the instinct to pause, inspect
                and verify every unexpected message before you act on it.
              </Typography>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                Red flags you may have missed
              </Typography>
              <Stack spacing={2}>
                {RED_FLAGS.map((flag) => (
                  <Box key={flag.title}>
                    <Typography variant="subtitle2">{flag.title}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {flag.detail}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 2 }}>
                How to protect yourself
              </Typography>
              <Stack component="ul" spacing={1} sx={{ pl: 2, m: 0 }}>
                {BEST_PRACTICES.map((tip) => (
                  <Typography component="li" variant="body2" key={tip}>
                    {tip}
                  </Typography>
                ))}
              </Stack>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="h3" sx={{ fontSize: '1.05rem', mb: 1 }}>
                Complete this micro-training
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                The material is short. Your completion is recorded automatically and adds
                awareness points to your security profile.
              </Typography>

              {result ? (
                <Alert
                  severity={result.success ? 'success' : 'warning'}
                  sx={{ mt: 2 }}
                  role="status"
                >
                  {result.message || 'Thank you — your completion has been recorded.'}
                </Alert>
              ) : (
                <>
                  <Stack direction="row" spacing={2} alignItems="center" sx={{ my: 2 }}>
                    <Chip
                      color={ready ? 'success' : 'default'}
                      label={ready ? 'Ready' : `${remaining}s`}
                      sx={{ minWidth: 72, fontWeight: 700 }}
                    />
                    <Box sx={{ flexGrow: 1 }}>
                      <LinearProgress
                        variant="determinate"
                        value={progress}
                        sx={{ height: 8, borderRadius: 99 }}
                      />
                    </Box>
                  </Stack>

                  {error ? (
                    <Alert severity="error" sx={{ mb: 2 }}>
                      {error}
                    </Alert>
                  ) : null}

                  <Button
                    variant="contained"
                    color="success"
                    size="large"
                    disabled={!ready || submitting || !trackingUuid}
                    onClick={() => void complete()}
                  >
                    {submitting ? 'Recording…' : ready ? 'Mark as complete' : `Please wait ${remaining}s`}
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </Stack>
      </Container>
    </Box>
  );
}
