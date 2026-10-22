/**
 * Vertical interaction timeline with second-level timestamps.
 *
 * Every entry comes from the append-only ledger, so repeated actions (a second
 * open, a third submission) each get their own row instead of being collapsed
 * into a counter.
 */
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

import { formatDateTime } from '@/lib/format';
import {
  describeUserAgent,
  eventMeta,
  isSubmissionEvent,
  type EventTone,
} from '@/lib/interactions';
import type { InteractionEvent } from '@/types';

const TONE_COLOR: Record<EventTone, string> = {
  default: 'grey.500',
  info: 'info.main',
  warning: 'warning.main',
  error: 'error.main',
  success: 'success.main',
};

function detailChips(event: InteractionEvent): string[] {
  const chips: string[] = [];
  const details = (event.details ?? {}) as Record<string, unknown>;
  const openCount = details.open_count;
  const clickCount = details.click_count;
  const viewCount = details.view_count;
  const submissionCount = details.submission_count;
  if (typeof openCount === 'number' && openCount > 1) chips.push(`open #${openCount}`);
  if (typeof clickCount === 'number' && clickCount > 1) chips.push(`click #${clickCount}`);
  if (typeof viewCount === 'number' && viewCount > 1) chips.push(`view #${viewCount}`);
  if (typeof submissionCount === 'number' && submissionCount > 1) {
    chips.push(`submission #${submissionCount}`);
  }
  if (details.synthetic === true) chips.push('reconstructed from legacy record');
  const client = details.client;
  if (client && typeof client === 'object' && 'seconds_on_form' in client) {
    const seconds = (client as Record<string, unknown>).seconds_on_form;
    if (typeof seconds === 'number') chips.push(`${seconds}s on form`);
  }
  return chips;
}

export function InteractionTimeline({
  events,
  showEmployee = false,
  showCampaign = false,
}: {
  events: InteractionEvent[];
  showEmployee?: boolean;
  showCampaign?: boolean;
}) {
  if (events.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No events recorded yet.
      </Typography>
    );
  }

  return (
    <Box>
      {events.map((event, index) => {
        const meta = eventMeta(event.event_type);
        const chips = detailChips(event);
        return (
          <Box key={event.id} sx={{ display: 'flex', gap: 1.5 }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', pt: 0.75 }}>
              <Box
                sx={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  bgcolor: TONE_COLOR[meta.tone],
                  flex: '0 0 auto',
                }}
              />
              {index < events.length - 1 ? (
                <Box sx={{ width: 2, flex: 1, bgcolor: 'divider', my: 0.5 }} />
              ) : null}
            </Box>

            <Box sx={{ flex: 1, pb: index < events.length - 1 ? 2.5 : 0 }}>
              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                justifyContent="space-between"
                alignItems={{ xs: 'flex-start', sm: 'baseline' }}
                spacing={{ xs: 0, sm: 2 }}
              >
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {showEmployee && event.employee_name ? (
                    <Box component="span" sx={{ color: 'primary.main', mr: 0.75 }}>
                      {event.employee_name}:
                    </Box>
                  ) : null}
                  {meta.label}
                </Typography>
                <Tooltip title={event.occurred_at} placement="left">
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}
                  >
                    {formatDateTime(event.occurred_at)}
                  </Typography>
                </Tooltip>
              </Stack>

              {showCampaign && event.campaign_name ? (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  display="block"
                  sx={{ fontStyle: 'italic' }}
                >
                  {event.campaign_name}
                </Typography>
              ) : null}

              {meta.description ? (
                <Typography variant="caption" color="text.secondary" display="block">
                  {meta.description}
                </Typography>
              ) : null}

              <Stack
                direction="row"
                spacing={1}
                flexWrap="wrap"
                useFlexGap
                sx={{ mt: 0.5, alignItems: 'center' }}
              >
                {event.ip_address ? (
                  <Typography variant="caption" color="text.secondary">
                    IP {event.ip_address}
                  </Typography>
                ) : null}
                {event.user_agent ? (
                  <Tooltip title={event.user_agent}>
                    <Typography variant="caption" color="text.secondary">
                      {describeUserAgent(event.user_agent)}
                    </Typography>
                  </Tooltip>
                ) : null}
                {chips.map((chip) => (
                  <Chip key={chip} size="small" variant="outlined" label={chip} />
                ))}
                {isSubmissionEvent(event) && event.values ? (
                  <Chip
                    size="small"
                    color="error"
                    variant="outlined"
                    label={`${Object.keys(event.values).length} field(s) captured`}
                  />
                ) : null}
              </Stack>
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
