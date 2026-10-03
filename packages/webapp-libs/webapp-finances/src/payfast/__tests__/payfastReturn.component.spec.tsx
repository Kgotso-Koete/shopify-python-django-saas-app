import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { act, screen } from '@testing-library/react';
import { generatePath } from 'react-router';
import { Route, Routes } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { render } from '../../tests/utils/rendering';
import { PayfastReturn } from '../routes/payfastReturn.component';
import { fillCheckoutStatusQuery } from '../tests/fixtures';

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

// PayFast sends the buyer back here after paying. The payment only counts once PayFast's ITN has
// reached our backend, which can be a moment later, so the page waits for the checkout to complete.
const renderReturnPage = (query: string, mocks: any[]) =>
  render(
    <Routes>
      <Route path={`/:lang/:tenantId/${RoutesConfig.finances.payfastReturn}`} element={<PayfastReturn />} />
      <Route path={`/:lang/:tenantId/${RoutesConfig.subscriptions.index}`} element={<span>subscriptions page</span>} />
      <Route path="/:lang/:tenantId" element={<span>home page</span>} />
    </Routes>,
    {
      routerProps: {
        initialEntries: [
          `${generatePath('/:lang/:tenantId', { lang: 'en', tenantId })}/${RoutesConfig.finances.payfastReturn}${query}`,
        ],
      },
      apolloMocks: [tenantMock(), ...mocks],
    }
  );

describe('PayFast return page', () => {
  it('goes to the subscription page once the subscription checkout is confirmed', async () => {
    renderReturnPage('?kind=subscription&m=m-1', [fillCheckoutStatusQuery('complete', 'm-1', tenantId)]);

    expect(await screen.findByText('subscriptions page')).toBeInTheDocument();
    expect(await screen.findByTestId('toast-1')).toHaveTextContent(/payment successful/i);
  });

  it('goes home once a donation is confirmed, like the Stripe donation page', async () => {
    renderReturnPage('?kind=donation&m=m-2', [fillCheckoutStatusQuery('complete', 'm-2', tenantId)]);

    expect(await screen.findByText('home page')).toBeInTheDocument();
  });

  describe('when PayFast takes longer than a minute', () => {
    beforeEach(() => jest.useFakeTimers({ advanceTimers: true }));
    afterEach(() => jest.useRealTimers());

    // Plan section 12, issue 6: after a donation, the way out is Home, as on success.
    it('offers Home after a donation', async () => {
      renderReturnPage('?kind=donation&m=m-4', [fillCheckoutStatusQuery('pending', 'm-4', tenantId)]);
      await act(() => jest.advanceTimersByTimeAsync(60000));

      expect(await screen.findByText(/still waiting for payfast/i)).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /go to home/i })).toBeInTheDocument();
      expect(screen.getByText(/appear in your transaction history/i)).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /go to my subscription/i })).not.toBeInTheDocument();
    });

    it('offers the subscription page after a subscription checkout', async () => {
      renderReturnPage('?kind=subscription&m=m-5', [fillCheckoutStatusQuery('pending', 'm-5', tenantId)]);
      await act(() => jest.advanceTimersByTimeAsync(60000));

      expect(await screen.findByRole('link', { name: /go to my subscription/i })).toBeInTheDocument();
    });
  });

  it('keeps waiting while PayFast has not confirmed yet', async () => {
    renderReturnPage('?kind=donation&m=m-3', [fillCheckoutStatusQuery('pending', 'm-3', tenantId)]);

    expect(await screen.findByText(/confirming your payment/i)).toBeInTheDocument();
    expect(screen.queryByText('home page')).not.toBeInTheDocument();
  });
});
