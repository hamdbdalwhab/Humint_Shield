/**
 * One captured credential-form submission, verbatim.
 *
 * Every value the employee typed is shown in plain text by default so an
 * administrator can compare it with the employee's real password and settle a
 * dispute about whether the interaction was deliberate. Secret-looking fields
 * can still be hidden with the eye toggle, and the comparison field is
 * client-side only: the real password is never sent to the server or stored.
 */
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableRow from '@mui/material/TableRow';
import TextField from '@mui/material/TextField';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import VisibilityIcon from '@mui/icons-material/Visibility';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import { useState } from 'react';
import toast from 'react-hot-toast';

import { formatDateTime } from '@/lib/format';
import { describeUserAgent, isSecretField, orderedSubmissionFields } from '@/lib/interactions';
import type { Submission } from '@/types';

interface SubmissionCardProps {
  submission: Submission;
  index: number;
}

export function SubmissionCard({ submission, index }: SubmissionCardProps) {
  const fields = orderedSubmissionFields(submission.values ?? {});
  const client = submission.client ?? {};
  // Hidden is the exception: values are visible by default for evidentiary
  // review. The eye toggle lets the administrator re-mask a field instantly.
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [realPassword, setRealPassword] = useState('');
  const passwordEntry = fields.find(([key]) => {
    const normalized = key.toLowerCase().replaceAll(/[\s_-]/g, '');
    return normalized.includes('password') || normalized.includes('passwd') || normalized === 'pwd';
  });
  const passwordMatches =
    Boolean(passwordEntry) && realPassword.length > 0 && realPassword === passwordEntry?.[1];

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(submission.values, null, 2));
      toast.success('Submitted values copied');
    } catch {
      toast.error('Clipboard is not available in this browser');
    }
  }

  return (
    <Card variant="outlined">
      <CardContent sx={{ pb: 1.5 }}>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'center' }}
          spacing={1}
          sx={{ mb: 1 }}
        >
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
            <Chip size="small" color="error" label={`Submission ${index + 1}`} />
            <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
              {formatDateTime(submission.occurred_at)}
            </Typography>
          </Stack>
          <Button size="small" startIcon={<ContentCopyIcon />} onClick={handleCopy}>
            Copy JSON
          </Button>
        </Stack>

        {fields.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            The form was submitted without any captured fields.
          </Typography>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableBody>
                {fields.map(([key, value]) => {
                  const secret = isSecretField(key);
                  const visible = !secret || !hidden[key];
                  return (
                    <TableRow key={key}>
                      <TableCell sx={{ width: '34%', verticalAlign: 'top', color: 'text.secondary' }}>
                        {key}
                        {secret ? (
                          <Chip size="small" variant="outlined" label="secret" sx={{ ml: 1, height: 18 }} />
                        ) : null}
                      </TableCell>
                      <TableCell sx={{ verticalAlign: 'top' }}>
                        <Stack direction="row" spacing={0.5} alignItems="center">
                          <Typography
                            variant="body2"
                            sx={{
                              fontFamily: 'monospace',
                              wordBreak: 'break-all',
                              color: secret ? 'error.main' : 'text.primary',
                              userSelect: 'all',
                            }}
                          >
                            {visible ? value : '•'.repeat(Math.min(value.length, 24) || 4)}
                          </Typography>
                          {secret ? (
                            <Tooltip title={hidden[key] ? 'Reveal value' : 'Hide value'}>
                              <IconButton
                                size="small"
                                onClick={() =>
                                  setHidden((current) => ({ ...current, [key]: !current[key] }))
                                }
                                aria-label={hidden[key] ? 'Reveal value' : 'Hide value'}
                              >
                                {hidden[key] ? (
                                  <VisibilityIcon fontSize="small" />
                                ) : (
                                  <VisibilityOffIcon fontSize="small" />
                                )}
                              </IconButton>
                            </Tooltip>
                          ) : null}
                        </Stack>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {passwordEntry ? (
          <Box
            sx={{
              mt: 2,
              p: 1.5,
              border: 1,
              borderColor: 'divider',
              borderRadius: 1,
              bgcolor: 'action.hover',
            }}
          >
            <Typography variant="subtitle2" gutterBottom>
              Compare with the employee&apos;s real password
            </Typography>
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
              Type the real password to compare locally. It is never sent to the server and never
              stored.
            </Typography>
            <Stack
              direction={{ xs: 'column', sm: 'row' }}
              spacing={1}
              alignItems={{ xs: 'stretch', sm: 'center' }}
            >
              <TextField
                size="small"
                type="password"
                label="Real password (local only)"
                value={realPassword}
                onChange={(event) => setRealPassword(event.target.value)}
                autoComplete="off"
                sx={{ minWidth: { sm: 280 } }}
              />
              {realPassword ? (
                <Chip
                  color={passwordMatches ? 'error' : 'success'}
                  label={
                    passwordMatches
                      ? 'MATCH — real password entered'
                      : 'NO MATCH — not the real password'
                  }
                />
              ) : null}
              {realPassword ? (
                <Button size="small" onClick={() => setRealPassword('')}>
                  Clear
                </Button>
              ) : null}
            </Stack>
            {passwordMatches ? (
              <Typography variant="caption" color="error.main" display="block" sx={{ mt: 1 }}>
                The employee submitted the same password used for their real account. This is
                evidence of credential disclosure, not a deliberate test entry.
              </Typography>
            ) : realPassword ? (
              <Typography variant="caption" color="success.main" display="block" sx={{ mt: 1 }}>
                The submitted value differs from the real password. The employee may have recognised
                the simulation or deliberately entered a decoy.
              </Typography>
            ) : null}
          </Box>
        ) : null}

        <Stack
          direction="row"
          spacing={2}
          flexWrap="wrap"
          useFlexGap
          sx={{ mt: 1.5, color: 'text.secondary' }}
        >
          <Typography variant="caption">
            IP address: {submission.ip_address ?? 'unknown'}
          </Typography>
          <Typography variant="caption">
            Device: {describeUserAgent(submission.user_agent)}
          </Typography>
          {submission.password_length !== null ? (
            <Typography variant="caption">
              Password length: {submission.password_length} characters
            </Typography>
          ) : null}
          {typeof client.seconds_on_form === 'number' ? (
            <Typography variant="caption">Time on form: {client.seconds_on_form}s</Typography>
          ) : null}
          {typeof client.timezone === 'string' ? (
            <Typography variant="caption">Timezone: {client.timezone}</Typography>
          ) : null}
          {typeof client.language === 'string' ? (
            <Typography variant="caption">Language: {client.language}</Typography>
          ) : null}
          {typeof client.viewport === 'string' ? (
            <Typography variant="caption">Viewport: {client.viewport}</Typography>
          ) : null}
        </Stack>

        <Box sx={{ mt: 0.5 }}>
          <Typography variant="caption" color="text.secondary">
            Stored encrypted (AES-256-GCM). Shown in plain text only to authenticated
            administrators. The real-password comparison never leaves this browser.
          </Typography>
        </Box>
      </CardContent>
    </Card>
  );
}
