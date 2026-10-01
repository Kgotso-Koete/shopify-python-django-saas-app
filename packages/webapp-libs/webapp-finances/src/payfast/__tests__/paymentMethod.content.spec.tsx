import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen } from '@testing-library/react';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { PayfastPaymentMethodContent } from '../routes/paymentMethod.content';
import { fillPayfastCardUpdateUrlQuery } from '../tests/fixtures';

jest.mock('@sb/webapp-tenants/hooks', () => ({
  ...jest.requireActual('@sb/webapp-tenants/hooks'),
  usePermissionCheck: () => ({ hasPermission: true, loading: false }),
}));

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));
// After updating the card, PayFast sends the buyer back to this tab.
const returnPath = `/en/${tenantId}/subscriptions/payment-methods`;

// Mirrors the Stripe tab (routes/subscriptions/paymentMethod.content.tsx). PayFast keeps the card, so
// the edit button becomes a link to PayFast's card update page.
describe('PayFast payment method', () => {
  it('shows the current method, as the Stripe tab does, and links to PayFast to update it', async () => {
    const url = 'https://www.payfast.co.za/eng/recurring/update/tok?return=https%3A%2F%2Fapp';
    render(<PayfastPaymentMethodContent />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.paymentMethods.index, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastCardUpdateUrlQuery({ hasCard: true, cardUpdateUrl: url }, returnPath, tenantId)],
    });

    expect(await screen.findByText(/current method:/i)).toBeInTheDocument();
    expect(screen.getByText('Credit card')).toBeInTheDocument();
    expect(screen.getByText(/stored securely by PayFast/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /update card/i })).toHaveAttribute('href', url);
  });

  it('shows the Stripe empty state when there is no card', async () => {
    render(<PayfastPaymentMethodContent />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.paymentMethods.index, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastCardUpdateUrlQuery({ hasCard: false, cardUpdateUrl: null }, returnPath, tenantId)],
    });

    expect(await screen.findByText(/no payment methods/i)).toBeInTheDocument();
    expect(screen.getByText(/added when you subscribe to a paid plan/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /update card/i })).not.toBeInTheDocument();
  });
});
