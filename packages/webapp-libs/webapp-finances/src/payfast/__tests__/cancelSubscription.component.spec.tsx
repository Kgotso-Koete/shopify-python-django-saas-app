import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { payfastCancelSubscriptionMutation } from '../payfast.graphql';
import { PayfastCancelSubscription } from '../routes/cancelSubscription.component';
import { fillPayfastSubscriptionQuery, monthlySubscription } from '../tests/fixtures';

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

describe('PayFast cancel subscription', () => {
  it('cancels at the end of the period after confirmation', async () => {
    const cancelMock = composeMockedQueryResult(payfastCancelSubscriptionMutation, {
      variables: { input: { tenantId } },
      data: {
        payfastCancelSubscription: {
          activeSubscription: { ...monthlySubscription, cancelAtPeriodEnd: true, __typename: 'PayFastSubscriptionType' },
          __typename: 'PayFastCancelSubscriptionMutationPayload',
        },
      },
    });
    render(<PayfastCancelSubscription />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.currentSubscription.cancel, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastSubscriptionQuery(monthlySubscription, tenantId), cancelMock],
    });

    // The same details as the Stripe cancel page: plan, price and next renewal / expiry.
    expect(await screen.findByText('Monthly')).toBeInTheDocument();
    expect(screen.getByText(/current plan info/i)).toBeInTheDocument();
    expect(screen.getByText(/199\.00/)).toBeInTheDocument();
    expect(screen.getByText(/next renewal \/ expiry:/i)).toBeInTheDocument();
    expect(screen.getByText(/January 31, 2099/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /cancel subscription/i }));
    await userEvent.click(await screen.findByRole('button', { name: /continue/i }));

    const toast = await screen.findByTestId('toast-1');
    // The same message as the Stripe cancel page.
    expect(toast).toHaveTextContent('You will be moved to free plan with the next billing period');
    expect(cancelMock.result).toHaveBeenCalled();
  });

  it('explains there is nothing to cancel on the free plan', async () => {
    render(<PayfastCancelSubscription />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.currentSubscription.cancel, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastSubscriptionQuery({}, tenantId)],
    });

    expect(await screen.findByText(/don't have an active paid subscription/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /choose a subscription plan/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /cancel subscription/i })).not.toBeInTheDocument();
  });
});
