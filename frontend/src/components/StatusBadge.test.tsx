/** Rendering tests for the campaign and engagement status badges. */
import { render, screen } from '@testing-library/react';

import { CampaignStatusBadge, EngagementStatusBadge } from '@/components/StatusBadge';

describe('CampaignStatusBadge', () => {
  it('renders the campaign status in upper case', () => {
    render(<CampaignStatusBadge status="active" />);
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
  });

  it('renders a completed campaign', () => {
    render(<CampaignStatusBadge status="completed" />);
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
  });
});

describe('EngagementStatusBadge', () => {
  it('renders the per-recipient engagement status', () => {
    render(<EngagementStatusBadge status="clicked" />);
    expect(screen.getByText('clicked')).toBeInTheDocument();
  });
});
