/** Formatting helpers (dates, percentages, names). */
import { format, formatDistanceToNow, parseISO } from 'date-fns';

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return format(parseISO(value), 'yyyy-MM-dd HH:mm:ss');
  } catch {
    return '—';
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return format(parseISO(value), 'yyyy-MM-dd');
  } catch {
    return '—';
  }
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return formatDistanceToNow(parseISO(value), { addSuffix: true });
  } catch {
    return '—';
  }
}

/** Wall-clock time only (local timezone), to the second. */
export function formatTime(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    return format(parseISO(value), 'HH:mm:ss');
  } catch {
    return '—';
  }
}

/** Compact duration: ``9s``, ``2m 14s``, ``1h 03m``. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest > 0 ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`;
}

export function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

/** Arabic relative time ("منذ 12 ثانية", "منذ 3 دقائق", "الآن"). */
export function relativeArabic(value: string | null | undefined): string {
  if (!value) return '—';
  try {
    const date = parseISO(value);
    const seconds = Math.round((Date.now() - date.getTime()) / 1000);
    if (seconds < 10) return 'الآن';
    if (seconds < 60) return `منذ ${seconds} ثانية`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `منذ ${minutes} دقيقة`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `منذ ${hours} ساعة`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `منذ ${days} يوم`;
    return formatDate(value);
  } catch {
    return '—';
  }
}

/** Arabic greeting based on the current local hour. */
export function arabicGreeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return 'صباح الخير';
  if (hour < 17) return 'طاب يومك';
  return 'مساء الخير';
}

export function fullName(first: string, last: string): string {
  return `${first} ${last}`.trim();
}
