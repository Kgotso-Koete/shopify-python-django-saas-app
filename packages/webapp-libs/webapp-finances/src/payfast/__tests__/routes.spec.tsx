import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen } from '@testing-library/react';

import { RoutesConfig } from '../../config/routes';
import { CurrentSubscriptionContent, PaymentConfirm, PayfastReturn, Subscriptions } from '../../routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { fillDonationAmountsQuery, fillPaymentConfigQuery, fillPayfastSubscriptionQuery } from '../tests/fixtures';

jest.mock('@sb/webapp-tenants/hooks', () => ({
  ...jest.requireActual('@sb/webapp-tenants/hooks'),
  usePermissionCheck: () => ({ hasPermission: true, loading: false }),
}));

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

// The app's routes (packages/webapp/src/app/app.component.tsx) import these names from
// @sb/webapp-finances/routes; with PAYMENT_BACKEND=payfast they must render the PayFast pages.
describe('finances routes with the PayFast backend', () => {
  it('the current subscription tab is the PayFast one', async () => {
    render(<CurrentSubscriptionContent />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.index, { tenantId }),
      apolloMocks: [tenantMock(), fillPaymentConfigQuery('payfast'), fillPayfastSubscriptionQuery({}, tenantId)],
    });

    expect(await screen.findByText('Free')).toBeInTheDocument();
  });

  it('the subscription page layout is the PayFast one', async () => {
    render(<Subscriptions />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.index, { tenantId }),
      apolloMocks: [tenantMock(), fillPaymentConfigQuery('payfast')],
    });

    expect(await screen.findByText(/powered by PayFast/i)).toBeInTheDocument();
  });

  it('the donation page is the PayFast one', async () => {
    render(<PaymentConfirm />, {
      routerProps: createMockRouterProps(RoutesConfig.finances.paymentConfirm, { tenantId }),
      apolloMocks: [tenantMock(), fillPaymentConfigQuery('payfast'), fillDonationAmountsQuery()],
    });

    expect(await screen.findByText(/single payment powered by PayFast/i)).toBeInTheDocument();
  });

  it('exports the PayFast return page', () => {
    expect(PayfastReturn).toBeDefined();
  });
});
