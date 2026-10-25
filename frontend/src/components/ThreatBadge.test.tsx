/** Rendering tests for the Elo-derived threat badge. */
import { render, screen } from '@testing-library/react';

import { ThreatBadge } from '@/components/ThreatBadge';

describe('ThreatBadge', () => {
  it.each([
    ['low', 'Low'],
    ['medium', 'Medium'],
    ['high', 'High'],
    ['critical', 'Critical'],
  ] as const)('renders the %s threat level', (level, label) => {
    render(<ThreatBadge level={level} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it('renders an em dash when the level is unknown', () => {
    render(<ThreatBadge level={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
