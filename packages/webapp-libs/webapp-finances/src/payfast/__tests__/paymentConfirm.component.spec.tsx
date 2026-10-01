import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen, waitFor } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { payfastCreateDonationCheckoutMutation } from '../payfast.graphql';
import { PayfastPaymentConfirm } from '../routes/paymentConfirm.component';
import { submitPayfastCheckout } from '../submitPayfastCheckout';
import { checkoutResponse, fillDonationAmountsQuery } from '../tests/fixtures';

jest.mock('../submitPayfastCheckout');

afterEach(() => {
  jest.clearAllMocks();
});

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

// The PayFast counterpart of the Stripe donation page (routes/paymentConfirm): same fixed amounts
// picker, but payment happens on PayFast's page instead of card fields on ours.
describe('PayFast donation page', () => {
  it('sends the chosen donation amount to PayFast', async () => {
    const donationMock = composeMockedQueryResult(payfastCreateDonationCheckoutMutation, {
      variables: {
        input: {
          tenantId,
          amount: '100.00',
          returnPath: `/en/${tenantId}/finances/payfast-return?kind=donation`,
          cancelPath: `/en/${tenantId}/finances/payment-confirm`,
        },
      },
      data: {
        payfastCreateDonationCheckout: {
          checkout: checkoutResponse,
          __typename: 'PayFastCreateDonationCheckoutMutationPayload',
        },
      },
    });
    render(<PayfastPaymentConfirm />, {
      routerProps: createMockRouterProps(RoutesConfig.finances.paymentConfirm, { tenantId }),
      apolloMocks: [tenantMock(), fillDonationAmountsQuery(), donationMock],
    });

    await userEvent.click(await screen.findByLabelText(/100\.00/));
    await userEvent.click(screen.getByRole('button', { name: /pay/i }));

    await waitFor(() => expect(donationMock.result).toHaveBeenCalled());
    await waitFor(() => expect(submitPayfastCheckout).toHaveBeenCalled());
    expect(submitPayfastCheckout).toHaveBeenCalledWith(expect.objectContaining({ actionUrl: checkoutResponse.actionUrl }));
  });

  it('has the same form as the Stripe donation page', async () => {
    render(<PayfastPaymentConfirm />, {
      routerProps: createMockRouterProps(RoutesConfig.finances.paymentConfirm, { tenantId }),
      apolloMocks: [tenantMock(), fillDonationAmountsQuery()],
    });

    expect(await screen.findByText(/choose the amount/i)).toBeInTheDocument();
    expect(screen.getByText(/select amount you would like to donate/i)).toBeInTheDocument();
    expect(screen.getByText(/complete your payment securely with PayFast/i)).toBeInTheDocument();
  });

  it('needs an amount before paying', async () => {
    render(<PayfastPaymentConfirm />, {
      routerProps: createMockRouterProps(RoutesConfig.finances.paymentConfirm, { tenantId }),
      apolloMocks: [tenantMock(), fillDonationAmountsQuery()],
    });

    expect(await screen.findByRole('button', { name: /pay/i })).toBeDisabled();
  });
});
