import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen, waitFor, within } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { payfastCreateCheckoutMutation } from '../payfast.graphql';
import { PayfastEditSubscription } from '../routes/editSubscription.component';
import { submitPayfastCheckout } from '../submitPayfastCheckout';
import {
  checkoutResponse,
  fillPayfastPlansQuery,
  fillPayfastSubscriptionQuery,
  monthlySubscription,
} from '../tests/fixtures';

jest.mock('../submitPayfastCheckout');

afterEach(() => {
  jest.clearAllMocks();
});

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

// Each plan card is marked with data-plan="<plan name>".
const planCard = async (planName: string) => {
  await waitFor(() => expect(document.querySelector(`[data-plan="${planName}"]`)).not.toBeNull());
  return document.querySelector(`[data-plan="${planName}"]`) as HTMLElement;
};

describe('PayFast edit subscription', () => {
  it('shows all three plans, like the Stripe page, with prices in ZAR', async () => {
    render(<PayfastEditSubscription />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.currentSubscription.edit, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastSubscriptionQuery({}, tenantId), fillPayfastPlansQuery()],
    });

    expect(within(await planCard('free_plan')).getByText('Free', { selector: '[class*="text-xl"]' })).toBeInTheDocument();
    expect(within(await planCard('monthly_plan')).getByText(/199\.00/)).toBeInTheDocument();
    expect(within(await planCard('yearly_plan')).getByText(/1,990\.00/)).toBeInTheDocument();
    // R199 monthly vs R1 990 yearly: 1 - 1990 / (12 * 199) = 16.7%, shown as 17%.
    expect(screen.getByText(/save 17% vs monthly/i)).toBeInTheDocument();
  });

  it('sends a free organisation to PayFast to start the chosen plan (with its free trial)', async () => {
    const checkoutMock = composeMockedQueryResult(payfastCreateCheckoutMutation, {
      variables: {
        input: {
          tenantId,
          plan: 'monthly_plan',
          returnPath: `/en/${tenantId}/finances/payfast-return?kind=subscription`,
          cancelPath: `/en/${tenantId}/subscriptions/current-subscription/edit`,
        },
      },
      data: {
        payfastCreateCheckout: { checkout: checkoutResponse, __typename: 'PayFastCreateCheckoutMutationPayload' },
      },
    });
    render(<PayfastEditSubscription />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.currentSubscription.edit, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastSubscriptionQuery({}, tenantId), fillPayfastPlansQuery(), checkoutMock],
    });

    // The cards come from the plans query; which one is current comes from the subscription query,
    // which can arrive later. findByRole waits for it; getByRole failed on CI's slower Node 22 runner.
    expect(await within(await planCard('free_plan')).findByRole('button', { name: /current plan/i })).toBeDisabled();
    const monthly = await planCard('monthly_plan');
    expect(within(monthly).getByText(/start with a free trial/i)).toBeInTheDocument();
    await userEvent.click(within(monthly).getByRole('button', { name: /select plan/i }));

    await waitFor(() => expect(checkoutMock.result).toHaveBeenCalled());
    await waitFor(() => expect(submitPayfastCheckout).toHaveBeenCalled());
    expect(submitPayfastCheckout).toHaveBeenCalledWith(
      expect.objectContaining({ actionUrl: checkoutResponse.actionUrl, fields: checkoutResponse.fields })
    );
  });

  const checkoutMockFor = (plan: string, errors?: GraphQLError[]) =>
    composeMockedQueryResult(payfastCreateCheckoutMutation, {
      variables: {
        input: {
          tenantId,
          plan,
          returnPath: `/en/${tenantId}/finances/payfast-return?kind=subscription`,
          cancelPath: `/en/${tenantId}/subscriptions/current-subscription/edit`,
        },
      },
      data: errors
        ? { payfastCreateCheckout: null }
        : { payfastCreateCheckout: { checkout: checkoutResponse, __typename: 'PayFastCreateCheckoutMutationPayload' } },
      errors,
    });

  it('switches a paying organisation with a new PayFast checkout that bills from the next renewal', async () => {
    // A plan change is a new PayFast subscription (R0 now, the new price from the end of the paid
    // period); PayFast's update API isn't used.
    const checkoutMock = checkoutMockFor('yearly_plan');
    render(<PayfastEditSubscription />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.currentSubscription.edit, { tenantId }),
      apolloMocks: [
        tenantMock(),
        fillPayfastSubscriptionQuery(monthlySubscription, tenantId),
        fillPayfastPlansQuery(),
        checkoutMock,
      ],
    });

    expect(await within(await planCard('monthly_plan')).findByRole('button', { name: /current plan/i })).toBeDisabled();
    // As on Stripe, a paying organisation moves to Free by cancelling, not from this page.
    expect(await within(await planCard('free_plan')).findByRole('button', { name: /free plan/i })).toBeDisabled();
    await userEvent.click(within(await planCard('yearly_plan')).getByRole('button', { name: /select plan/i }));

    await waitFor(() => expect(checkoutMock.result).toHaveBeenCalled());
    await waitFor(() => expect(submitPayfastCheckout).toHaveBeenCalled());
  });

  it("shows the server's reason when the switch is refused", async () => {
    const reason = 'This subscription is cancelled; choose a new plan once it has ended.';
    const failingMock = checkoutMockFor('yearly_plan', [
      new GraphQLError('GraphQlValidationError', {
        extensions: { non_field_errors: [{ message: reason, code: 'invalid' }] },
      }),
    ]);
    render(<PayfastEditSubscription />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.currentSubscription.edit, { tenantId }),
      apolloMocks: [
        tenantMock(),
        fillPayfastSubscriptionQuery(monthlySubscription, tenantId),
        fillPayfastPlansQuery(),
        failingMock,
      ],
    });

    await userEvent.click(within(await planCard('yearly_plan')).getByRole('button', { name: /select plan/i }));

    // Not the bare error class name "GraphQlValidationError".
    expect(await screen.findByTestId('toast-1')).toHaveTextContent(reason);
    expect(submitPayfastCheckout).not.toHaveBeenCalled();
  });
});
