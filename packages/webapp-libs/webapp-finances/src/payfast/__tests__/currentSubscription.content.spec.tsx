// Kind of test: integration (agents.md section 2.5). Why: the page renders with the real Apollo hooks, router and
// translations; the backend is Apollo's MockedProvider, and every permission check is mocked as granted.
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen } from '@testing-library/react';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { payfastTenantBillingEmailQuery } from '../payfast.graphql';
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
    renderContent({ ...monthlySubscription, status: 'TRIALING', trialEnd: '2099-01-31T10:00:00+00:00' });

    expect(await screen.findByText(/free trial expiry date/i)).toBeInTheDocument();
  });

  it('shows a pending plan change', async () => {
    renderContent({ ...monthlySubscription, pendingPlan: 'yearly_plan' });

    expect(await screen.findByText(/next billing plan/i)).toBeInTheDocument();
    expect(screen.getByText('Yearly')).toBeInTheDocument();
  });

  // Plan section 12, issue 5: during a trial nothing is charged yet, so the page says what the first
  // charge will be. After a switch during a trial, that is the new plan's price, not the old one's.
  it('shows the first charge after the trial instead of the current price', async () => {
    renderContent({ ...monthlySubscription, status: 'TRIALING', trialEnd: '2099-01-31T10:00:00+00:00' });

    const price = await screen.findByText(/free trial, then/i);
    expect(price).toHaveTextContent(/199\.00 \/ month/);
  });

  it('shows the switched plan and its price as the first charge after a trial', async () => {
    renderContent({
      ...monthlySubscription,
      status: 'TRIALING',
      trialEnd: '2099-01-31T10:00:00+00:00',
      pendingPlan: 'yearly_plan',
      pendingAmount: '10.00',
    });

    const price = await screen.findByText(/free trial, then/i);
    expect(price).toHaveTextContent(/Yearly/);
    expect(price).toHaveTextContent(/10\.00 \/ year/);
    expect(screen.queryByText(/199\.00/)).not.toBeInTheDocument();
  });

  it('says a cancelled trial will not be charged', async () => {
    renderContent({
      ...monthlySubscription,
      status: 'TRIALING',
      trialEnd: '2099-01-31T10:00:00+00:00',
      cancelAtPeriodEnd: true,
    });

    expect(await screen.findByText(/cancelled, so you won't be charged/i)).toBeInTheDocument();
    expect(screen.queryByText(/free trial, then/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/199\.00/)).not.toBeInTheDocument();
    expect(screen.getByText(/^expiry date:/i)).toBeInTheDocument();
  });

  it('shows what the next billing plan will charge', async () => {
    renderContent({ ...monthlySubscription, pendingPlan: 'yearly_plan', pendingAmount: '10.00' });

    expect(await screen.findByText(/next billing plan/i)).toBeInTheDocument();
    expect(screen.getByText(/Yearly, .*10\.00 \/ year/)).toBeInTheDocument();
    // The current, already paid period still shows its own price.
    expect(screen.getByText(/199\.00 \/ month/)).toBeInTheDocument();
  });

  // WhatsApp plan, user story WA.D6.OM.J1.A1: the billing email PayFast bills sits with the plan it pays for.
  it('WA.D6.OM.J1.A1 shows the organization billing email card', async () => {
    render(<PayfastCurrentSubscriptionContent />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.index, { tenantId }),
      apolloMocks: [
        tenantMock(),
        fillPayfastSubscriptionQuery(monthlySubscription, tenantId),
        composeMockedQueryResult(payfastTenantBillingEmailQuery, {
          variables: { id: tenantId },
          data: { tenant: { id: tenantId, billingEmail: 'accounts@acme.example', __typename: 'TenantType' } },
        }),
      ],
    });

    expect(await screen.findByText('Billing email')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('accounts@acme.example')).toBeInTheDocument();
  });

  it('shows the expiry date instead of a renewal once cancelled', async () => {
    renderContent({ ...monthlySubscription, cancelAtPeriodEnd: true });

    expect(await screen.findByText(/expiry date/i)).toBeInTheDocument();
    expect(screen.queryByText(/next renewal/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /cancel subscription/i })).not.toBeInTheDocument();
  });
});
