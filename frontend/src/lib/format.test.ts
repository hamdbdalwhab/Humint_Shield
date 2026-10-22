/** Unit tests for the pure formatting helpers. */
import { formatDate, formatDateTime, formatPercent, fullName, formatRelative } from '@/lib/format';

describe('formatPercent', () => {
  it('renders one decimal place with a percent sign', () => {
    expect(formatPercent(12.345)).toBe('12.3%');
    expect(formatPercent(0)).toBe('0.0%');
    expect(formatPercent(100)).toBe('100.0%');
  });
});

describe('fullName', () => {
  it('joins first and last name', () => {
    expect(fullName('Jane', 'Doe')).toBe('Jane Doe');
  });

  it('trims a missing last name', () => {
    expect(fullName('Jane', '')).toBe('Jane');
  });
});

describe('formatDate', () => {
  it('renders an em dash for empty input', () => {
    expect(formatDate(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
  });

  it('renders an em dash for unparseable input', () => {
    expect(formatDate('not-a-date')).toBe('—');
  });

  it('formats an ISO local timestamp as yyyy-MM-dd', () => {
    // A local (no timezone suffix) timestamp is stable across timezones.
    expect(formatDate('2024-01-15T12:00:00')).toBe('2024-01-15');
  });
});

describe('formatDateTime', () => {
  it('includes the time component', () => {
    expect(formatDateTime('2024-01-15T09:05:00')).toBe('2024-01-15 09:05:00');
  });

  it('renders an em dash for null', () => {
    expect(formatDateTime(null)).toBe('—');
  });
});

describe('formatRelative', () => {
  it('renders an em dash for null', () => {
    expect(formatRelative(null)).toBe('—');
  });
});
