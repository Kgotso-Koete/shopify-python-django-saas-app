import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen } from '@testing-library/react';

import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { RoutesConfig } from '../../config/routes';
import { PayfastCurrentSubscriptionContent } from '../routes/currentSubscription.content';
import { fillPayfastSubscriptionQuery, monthlySubscription } from '../tests/fixtures';

jest.mock('@sb/webapp-tenants/hooks', () => ({
  ...jest.requireActual('@sb/webapp-tenants/hooks'),
  usePermissionCheck: () => ({ hasPermission: true, loading: false }),
}));

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

const renderContent = (subscription: Parameters<typeof fillPayfastSubscriptionQuery>[0]) =>
  render(<PayfastCurrentSubscriptionContent />, {
    routerProps: createMockRouterProps(RoutesConfig.subscriptions.index, { tenantId }),
    apolloMocks: [tenantMock(), fillPayfastSubscriptionQuery(subscription, tenantId)],
  });

describe('PayFast current subscription', () => {
  it('shows the free plan and an invitation to subscribe', async () => {
    renderContent({});

    expect(await screen.findByText('Free')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /edit subscription/i })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /cancel subscription/i })).not.toBeInTheDocument();
  });

  it('shows the paid plan, its ZAR price and the next renewal', async () => {
    renderContent(monthlySubscription);

    expect(await screen.findByText('Monthly')).toBeInTheDocument();
    expect(screen.getByText(/199\.00/)).toBeInTheDocument();
    expect(screen.getByText(/next renewal/i)).toBeInTheDocument();
    expect(screen.getByText(/January 31, 2099/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /cancel subscription/i })).toBeInTheDocument();
  });

  it('shows the trial end while trialing', async () => {
    renderContent({ ...monthlySubscription, status: 'trialing', trialEnd: '2099-01-31T10:00:00+00:00' });

    expect(await screen.findByText(/free trial expiry date/i)).toBeInTheDocument();
  });

  it('shows a pending plan change', async () => {
    renderContent({ ...monthlySubscription, pendingPlan: 'yearly_plan' });

    expect(await screen.findByText(/next billing plan/i)).toBeInTheDocument();
    expect(screen.getByText('Yearly')).toBeInTheDocument();
  });

  it('shows the expiry date instead of a renewal once cancelled', async () => {
    renderContent({ ...monthlySubscription, cancelAtPeriodEnd: true });

    expect(await screen.findByText(/expiry date/i)).toBeInTheDocument();
    expect(screen.queryByText(/next renewal/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /cancel subscription/i })).not.toBeInTheDocument();
  });
});
