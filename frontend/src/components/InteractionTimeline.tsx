/**
 * Vertical interaction timeline with second-level timestamps.
 *
 * Every entry comes from the append-only ledger, so repeated actions (a second
 * open, a third submission) each get their own row instead of being collapsed
 * into a counter.
 *
 * Presentation: events are grouped by day, each row gets a tone-coloured icon
 * badge on a gradient rail, and the body is a hover card so long histories stay
 * scannable.
 */
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { alpha } from '@mui/material/styles';
import { format, parseISO } from 'date-fns';
import type { ReactNode } from 'react';
import {
  Eye,
  GraduationCap,
  KeyRound,
  Mail,
  MailCheck,
  MailOpen,
  MessageCircle,
  MousePointerClick,
  Radio,
  ShieldCheck,
  UserPlus,
} from 'lucide-react';

import { formatDateTime, formatTime, relativeArabic } from '@/lib/format';
import {
  describeUserAgent,
  eventMeta,
  isSubmissionEvent,
  type EventTone,
} from '@/lib/interactions';
import type { InteractionEvent } from '@/types';

const TONE_COLOR: Record<EventTone, string> = {
  default: '#7c8b9e',
  info: '#00f0ff',
  warning: '#ffb020',
  error: '#ff1744',
  success: '#22c55e',
};

/** A small glyph per event family, so the rail reads at a glance. */
function iconFor(eventType: string): ReactNode {
  switch (eventType) {
    case 'campaign_assigned':
      return <UserPlus size={13} />;
    case 'email_sent':
      return <Mail size={13} />;
    case 'email_delivered':
      return <MailCheck size={13} />;
    case 'email_open':
    case 'email_opened':
      return <MailOpen size={13} />;
    case 'message_sent':
    case 'message_delivered':
    case 'message_read':
      return <MessageCircle size={13} />;
    case 'link_click':
    case 'link_clicked':
      return <MousePointerClick size={13} />;
    case 'form_viewed':
    case 'training_form_viewed':
      return <Eye size={13} />;
    case 'form_submitted':
    case 'credentials_submitted':
      return <KeyRound size={13} />;
    case 'phishing_reported':
      return <ShieldCheck size={13} />;
    case 'training_completed':
      return <GraduationCap size={13} />;
    default:
      return <Radio size={13} />;
  }
}

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

/** Stable day bucket key (`yyyy-MM-dd`) for grouping. */
function dayKey(value: string): string {
  try {
    return format(parseISO(value), 'yyyy-MM-dd');
  } catch {
    return value;
  }
}

/** Arabic day heading: اليوم / أمس / full date. */
function dayLabel(value: string): string {
  try {
    const date = parseISO(value);
    const key = format(date, 'yyyy-MM-dd');
    if (key === format(new Date(), 'yyyy-MM-dd')) return 'اليوم';
    if (key === format(new Date(Date.now() - 86_400_000), 'yyyy-MM-dd')) return 'أمس';
    return date.toLocaleDateString('ar-JO', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  } catch {
    return value;
  }
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
      <Box
        sx={{
          px: 2,
          py: 3,
          textAlign: 'center',
          borderRadius: 3,
          border: '1px dashed rgba(255,255,255,.12)',
          bgcolor: 'rgba(255,255,255,.02)',
        }}
      >
        <Typography variant="body2" color="text.secondary">
          No events recorded yet.
        </Typography>
      </Box>
    );
  }

  const groups: Array<{ key: string; label: string; events: InteractionEvent[] }> = [];
  for (const event of events) {
    const key = dayKey(event.occurred_at);
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.events.push(event);
    } else {
      groups.push({ key, label: dayLabel(event.occurred_at), events: [event] });
    }
  }

  return (
    <Box>
      {groups.map((group) => (
        <Box key={group.key} sx={{ mb: 2.5, '&:last-of-type': { mb: 0 } }}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
            <Box
              sx={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                bgcolor: 'primary.main',
                boxShadow: '0 0 10px rgba(0,240,255,.85)',
                flex: '0 0 auto',
              }}
            />
            <Typography
              sx={{
                fontSize: '0.72rem',
                fontWeight: 800,
                letterSpacing: '.05em',
                color: 'text.secondary',
                whiteSpace: 'nowrap',
              }}
            >
              {group.label}
            </Typography>
            <Box
              sx={{
                flex: 1,
                height: '1px',
                background: 'linear-gradient(90deg, rgba(255,255,255,.18), transparent)',
              }}
            />
            <Chip
              size="small"
              variant="outlined"
              label={`${group.events.length} حدث`}
              sx={{ height: 20, fontSize: '0.6rem', borderColor: 'rgba(255,255,255,.12)' }}
            />
          </Stack>

          {group.events.map((event, index) => {
            const meta = eventMeta(event.event_type);
            const color = TONE_COLOR[meta.tone];
            const chips = detailChips(event);
            const isLast = index === group.events.length - 1;
            return (
              <Box key={event.id} sx={{ display: 'flex', gap: 1.4 }}>
                {/* rail */}
                <Box
                  sx={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    pt: 0.35,
                    width: 26,
                    flex: '0 0 auto',
                  }}
                >
                  <Box
                    sx={{
                      position: 'relative',
                      zIndex: 1,
                      width: 26,
                      height: 26,
                      borderRadius: '50%',
                      display: 'grid',
                      placeItems: 'center',
                      color,
                      bgcolor: alpha(color, 0.14),
                      border: `1px solid ${alpha(color, 0.45)}`,
                      boxShadow: `0 0 0 4px ${alpha(color, 0.05)}, 0 0 14px ${alpha(color, 0.35)}`,
                      transition: 'transform .2s ease, box-shadow .2s ease',
                      '&:hover': {
                        transform: 'scale(1.08)',
                        boxShadow: `0 0 0 5px ${alpha(color, 0.1)}, 0 0 20px ${alpha(color, 0.5)}`,
                      },
                    }}
                  >
                    {iconFor(event.event_type)}
                  </Box>
                  {!isLast ? (
                    <Box
                      sx={{
                        width: 2,
                        flex: 1,
                        minHeight: 16,
                        my: 0.4,
                        borderRadius: 1,
                        background: `linear-gradient(180deg, ${alpha(color, 0.5)}, rgba(255,255,255,.06))`,
                      }}
                    />
                  ) : null}
                </Box>

                {/* card */}
                <Box
                  sx={{
                    flex: 1,
                    minWidth: 0,
                    mb: isLast ? 0 : 1,
                    px: 1.5,
                    py: 1.1,
                    borderRadius: 2.5,
                    border: '1px solid rgba(255,255,255,.06)',
                    background:
                      'linear-gradient(135deg, rgba(255,255,255,.035), rgba(255,255,255,.008))',
                    transition: 'border-color .22s ease, background .22s ease, transform .22s ease',
                    '&:hover': {
                      borderColor: alpha(color, 0.42),
                      background: `linear-gradient(135deg, ${alpha(color, 0.09)}, rgba(255,255,255,.012))`,
                      transform: 'translateX(-2px)',
                    },
                  }}
                >
                  <Stack
                    direction={{ xs: 'column', sm: 'row' }}
                    justifyContent="space-between"
                    alignItems={{ xs: 'flex-start', sm: 'center' }}
                    spacing={{ xs: 0.5, sm: 1.5 }}
                  >
                    <Typography
                      variant="body2"
                      sx={{ fontWeight: 700, lineHeight: 1.5, minWidth: 0 }}
                    >
                      {showEmployee && event.employee_name ? (
                        <Box component="span" sx={{ color: 'primary.main', mr: 0.75 }}>
                          {event.employee_name}
                        </Box>
                      ) : null}
                      {meta.label}
                    </Typography>

                    <Tooltip
                      title={`${formatDateTime(event.occurred_at)} · ${relativeArabic(event.occurred_at)}`}
                      placement="left"
                    >
                      <Box
                        sx={{
                          px: 0.9,
                          py: 0.2,
                          borderRadius: 99,
                          bgcolor: 'rgba(255,255,255,.045)',
                          border: '1px solid rgba(255,255,255,.08)',
                          fontFamily: 'monospace',
                          fontSize: '0.68rem',
                          whiteSpace: 'nowrap',
                          color: 'text.secondary',
                          flex: '0 0 auto',
                        }}
                      >
                        {formatTime(event.occurred_at)}
                      </Box>
                    </Tooltip>
                  </Stack>

                  {showCampaign && event.campaign_name ? (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      display="block"
                      sx={{ fontStyle: 'italic', mt: 0.15 }}
                    >
                      {event.campaign_name}
                    </Typography>
                  ) : null}

                  {meta.description ? (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      display="block"
                      sx={{ mt: 0.15 }}
                    >
                      {meta.description}
                    </Typography>
                  ) : null}

                  <Stack
                    direction="row"
                    spacing={1}
                    flexWrap="wrap"
                    useFlexGap
                    sx={{ mt: 0.6, alignItems: 'center', rowGap: 0.5 }}
                  >
                    {event.ip_address ? (
                      <Typography
                        variant="caption"
                        sx={{ fontFamily: 'monospace', color: 'text.secondary', fontSize: '0.68rem' }}
                      >
                        IP {event.ip_address}
                      </Typography>
                    ) : null}
                    {event.user_agent ? (
                      <Tooltip title={event.user_agent}>
                        <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.68rem' }}>
                          {describeUserAgent(event.user_agent)}
                        </Typography>
                      </Tooltip>
                    ) : null}
                    {chips.map((chip) => (
                      <Chip
                        key={chip}
                        size="small"
                        variant="outlined"
                        label={chip}
                        sx={{ height: 20, fontSize: '0.62rem', borderColor: 'rgba(255,255,255,.14)' }}
                      />
                    ))}
                    {isSubmissionEvent(event) && event.values ? (
                      <Chip
                        size="small"
                        variant="outlined"
                        label={`${Object.keys(event.values).length} field(s) captured`}
                        sx={{
                          height: 20,
                          fontSize: '0.62rem',
                          color: TONE_COLOR.error,
                          borderColor: alpha(TONE_COLOR.error, 0.5),
                          bgcolor: alpha(TONE_COLOR.error, 0.08),
                        }}
                      />
                    ) : null}
                  </Stack>
                </Box>
              </Box>
            );
          })}
        </Box>
      ))}
    </Box>
  );
}
