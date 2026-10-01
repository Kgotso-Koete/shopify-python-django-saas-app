import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen } from '@testing-library/react';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { PayfastTransactionHistory } from '../routes/transactionHistory.component';
import { PayfastTransactionsHistoryContent } from '../routes/transactionsHistory.content';
import { fillPayfastPaymentsQuery } from '../tests/fixtures';

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

const payments = [
  { pfPaymentId: '1', kind: 'donation', plan: '', amountGross: '50.00', createdAt: '2026-10-02T10:00:00+00:00' },
  { pfPaymentId: '2', kind: 'subscription', plan: 'monthly_plan', amountGross: '199.00', createdAt: '2026-10-01T10:00:00+00:00' },
];

// Mirrors the Stripe tab (routes/subscriptions/transactionsHistory.content.tsx) and full page
// (routes/transactionHistory): the tab links to the full page, which has the table.
describe('PayFast transaction history tab', () => {
  it('links to the full history when there are payments, as the Stripe tab does', async () => {
    render(<PayfastTransactionsHistoryContent />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.transactionHistory.index, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastPaymentsQuery(payments, tenantId)],
    });

    expect(await screen.findByRole('link', { name: /view transaction history/i })).toHaveAttribute(
      'href',
      `/en/${tenantId}/${RoutesConfig.subscriptions.transactionHistory.history}`
    );
  });

  it('shows the Stripe empty state when there are no payments yet', async () => {
    render(<PayfastTransactionsHistoryContent />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.transactionHistory.index, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastPaymentsQuery([], tenantId)],
    });

    expect(await screen.findByText(/no transactions yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /view transaction history/i })).not.toBeInTheDocument();
  });
});

describe('PayFast transaction history page', () => {
  it('lists donations and plan payments with the same labels and columns as Stripe', async () => {
    render(<PayfastTransactionHistory />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.transactionHistory.history, { tenantId }),
      apolloMocks: [tenantMock(), fillPayfastPaymentsQuery(payments, tenantId)],
    });

    expect(await screen.findByText('Donation')).toBeInTheDocument();
    expect(screen.getByText('Monthly plan')).toBeInTheDocument();
    expect(screen.getByText(/50\.00/)).toBeInTheDocument();
    expect(screen.getByText(/199\.00/)).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /payment method/i })).toBeInTheDocument();
    // PayFast's notifications don't say which card was used, so the column names the processor.
    expect(screen.getAllByText('PayFast')).toHaveLength(2);
    expect(screen.getByRole('link', { name: /back to transaction history/i })).toBeInTheDocument();
  });
});
