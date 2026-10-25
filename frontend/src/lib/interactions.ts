/**
 * Presentation helpers for the interaction ledger.
 *
 * The backend stores raw event types (`email_open`, `form_submitted`, …), IP
 * addresses and User-Agent strings. This module turns them into consistent,
 * human-readable labels, colours and device summaries so every screen shows the
 * same vocabulary.
 */
import type { InteractionEvent } from '@/types';

export type EventTone = 'default' | 'info' | 'warning' | 'error' | 'success';

export interface EventMeta {
  label: string;
  tone: EventTone;
  /** Short explanation shown under the label in timelines. */
  description?: string;
}

const META: Record<string, EventMeta> = {
  campaign_assigned: { label: 'Campaign assigned', tone: 'default' },
  email_sent: {
    label: 'Email accepted by the mail server',
    tone: 'default',
    description: 'Handed to Brevo for delivery.',
  },
  email_delivered: { label: 'Email delivered', tone: 'default' },
  message_sent: {
    label: 'SMS/WhatsApp accepted by the provider',
    tone: 'default',
    description: 'Handed to Vonage for delivery.',
  },
  message_delivered: { label: 'SMS/WhatsApp delivered', tone: 'success' },
  message_read: { label: 'SMS/WhatsApp read', tone: 'success' },
  email_open: { label: 'Email opened', tone: 'info' },
  email_opened: { label: 'Email opened', tone: 'info' },
  link_click: { label: 'Link clicked', tone: 'warning' },
  link_clicked: { label: 'Link clicked', tone: 'warning' },
  form_viewed: {
    label: 'Training form displayed',
    tone: 'info',
    description: 'The simulated sign-in page was rendered.',
  },
  training_form_viewed: { label: 'Training form displayed', tone: 'info' },
  form_submitted: {
    label: 'Credentials entered',
    tone: 'error',
    description: 'The employee submitted the simulated sign-in form.',
  },
  credentials_submitted: {
    label: 'Credentials entered',
    tone: 'error',
    description: 'The employee submitted the simulated sign-in form.',
  },
  phishing_reported: {
    label: 'Reported as phishing',
    tone: 'success',
    description: 'The employee spotted the simulation — a positive outcome.',
  },
  training_completed: {
    label: 'Micro-training completed',
    tone: 'success',
  },
};

export function eventMeta(eventType: string): EventMeta {
  return META[eventType] ?? { label: eventType.replaceAll('_', ' '), tone: 'default' };
}

/** True when the event carries captured form values. */
export function isSubmissionEvent(event: InteractionEvent): boolean {
  return event.event_type === 'form_submitted' || event.event_type === 'credentials_submitted';
}

/**
 * Produce a compact "Chrome 141 · Android" style summary from a User-Agent.
 *
 * This is a best-effort, dependency-free heuristic used only for display.
 */
export function describeUserAgent(userAgent: string | null | undefined): string {
  if (!userAgent) return 'Unknown device';
  const ua = userAgent;
  let browser = 'Browser';
  if (/Edg\//.test(ua)) browser = 'Edge';
  else if (/OPR\/|Opera/.test(ua)) browser = 'Opera';
  else if (/Firefox\//.test(ua)) browser = 'Firefox';
  else if (/Chrome\//.test(ua)) browser = 'Chrome';
  else if (/Safari\//.test(ua)) browser = 'Safari';
  else if (/curl\//.test(ua)) browser = 'curl';
  else if (/python-requests|httpx|aiohttp/i.test(ua)) browser = 'HTTP client';

  let platform = '';
  if (/Android/.test(ua)) platform = 'Android';
  else if (/iPhone|iPad|iPod/.test(ua)) platform = 'iOS';
  else if (/Windows/.test(ua)) platform = 'Windows';
  else if (/Mac OS X|Macintosh/.test(ua)) platform = 'macOS';
  else if (/Linux/.test(ua)) platform = 'Linux';

  return platform ? `${browser} · ${platform}` : browser;
}

/** Format a duration in seconds as `m:ss` / `h:mm:ss`. */
export function formatDurationSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const mm = String(minutes).padStart(2, '0');
  const ss = String(secs).padStart(2, '0');
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${minutes}:${ss}`;
}

/**
 * Return the fields of a submission in a display-friendly order.
 *
 * `identifier` and `password` are shown first, then the remaining fields
 * alphabetically so the table is stable between renders.
 */
export function orderedSubmissionFields(values: Record<string, string>): Array<[string, string]> {
  const priority = ['identifier', 'email', 'username', 'password'];
  const entries = Object.entries(values);
  const seen = new Set<string>();
  const ordered: Array<[string, string]> = [];
  for (const key of priority) {
    const match = entries.find(([entryKey]) => entryKey.toLowerCase() === key);
    if (match) {
      ordered.push(match);
      seen.add(match[0]);
    }
  }
  entries
    .filter(([key]) => !seen.has(key))
    .sort(([a], [b]) => a.localeCompare(b))
    .forEach((entry) => ordered.push(entry));
  return ordered;
}

/** True when a field name looks like a secret (used for masking). */
export function isSecretField(key: string): boolean {
  const normalized = key.toLowerCase().replaceAll(/[\s_-]/g, '');
  return (
    normalized.includes('password') ||
    normalized.includes('passwd') ||
    normalized.includes('passphrase') ||
    normalized === 'pwd' ||
    normalized.includes('secret') ||
    normalized.includes('token') ||
    normalized.includes('otp') ||
    normalized.includes('pin')
  );
}
