// Tests for Download invoice in the PayFast transaction history (WhatsApp plan phase 4, Step 4.5a, decisions
// 12, 19 and 20): each payment with an invoice offers it; the button renews the login, fetches the PDF from
// /api/invoicing/<id>/pdf/ and saves it as a file named after the invoice's number, as the backup page saves
// its download; a refusal shows a message instead of an error page.
//
// Kind of test: integration (agents.md section 2.5). Why: the page renders with the real Apollo hooks and
// router; the backend is Apollo's MockedProvider, and the login renewal and the PDF request are spied on, with
// the browser's file save (URL.createObjectURL and the link's click) faked, since jsdom has neither.
import { apiClient, apiURL, auth } from '@sb/webapp-api-client/api';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { PayfastTransactionHistory } from '../routes/transactionHistory.component';
import { fillPayfastInvoicesQuery, fillPayfastPaymentsQuery, fillPayfastSubscriptionQuery } from '../tests/fixtures';

const tenantId = 'tenantId';
const tenantMock = () => fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId })] }));

const payments = [
  { pfPaymentId: '1', kind: 'DONATION', plan: '', amountGross: '50.00', createdAt: '2026-10-02T10:00:00+00:00' },
  { pfPaymentId: '2', kind: 'SUBSCRIPTION', plan: 'monthly_plan', amountGross: '199.00', createdAt: '2026-10-01T10:00:00+00:00' },
];
// The fixture gives each payment the id `id-<pfPaymentId>`; only the plan payment has an invoice here.
const invoices = [{ id: 'inv-1', number: 'INV-2026-000001', paymentId: 'id-2' }];

const renderPage = () =>
  render(<PayfastTransactionHistory />, {
    routerProps: createMockRouterProps(RoutesConfig.subscriptions.transactionHistory.history, { tenantId }),
    apolloMocks: [tenantMock(), fillPayfastPaymentsQuery(payments, tenantId), fillPayfastInvoicesQuery(invoices, tenantId)],
  });

const rowOf = async (text: string) => (await screen.findByText(text)).closest('tr') as HTMLElement;

describe('WA.D6.OM.J2.A1 Download invoice in the PayFast transaction history', () => {
  let refresh: jest.SpyInstance;
  let get: jest.SpyInstance;
  let click: jest.SpyInstance;

  beforeEach(() => {
    refresh = jest.spyOn(auth, 'refreshToken').mockResolvedValue(undefined as never);
    get = jest.spyOn(apiClient, 'get').mockResolvedValue({ data: new Blob(['%PDF']) } as never);
    URL.createObjectURL = jest.fn(() => 'blob:invoice');
    URL.revokeObjectURL = jest.fn();
    click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => jest.restoreAllMocks());

  it('offers it on a payment that has an invoice, and not on one that has none', async () => {
    renderPage();

    expect(await within(await rowOf('Monthly plan')).findByRole('button', { name: /download invoice/i })).toBeInTheDocument();
    expect(within(await rowOf('Donation')).queryByRole('button', { name: /download invoice/i })).not.toBeInTheDocument();
  });

  it('renews the login, fetches the PDF and saves it named after the invoice', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await within(await rowOf('Monthly plan')).findByRole('button', { name: /download invoice/i }));

    await waitFor(() => expect(get).toHaveBeenCalledWith(apiURL('/invoicing/inv-1/pdf/'), { responseType: 'blob' }));
    expect(refresh.mock.invocationCallOrder[0]).toBeLessThan(get.mock.invocationCallOrder[0]);
    await waitFor(() => expect(click).toHaveBeenCalled());
    const link = click.mock.instances[0] as unknown as HTMLAnchorElement;
    expect(link.download).toBe('INV-2026-000001.pdf');
    expect(link.href).toBe('blob:invoice');
  });

  it('shows a message, not an error page, when the server refuses', async () => {
    const user = userEvent.setup();
    get.mockRejectedValue({ response: { status: 403 } });
    renderPage();

    await user.click(await within(await rowOf('Monthly plan')).findByRole('button', { name: /download invoice/i }));

    expect(await screen.findByText(/couldn't be downloaded/i)).toBeInTheDocument();
    expect(click).not.toHaveBeenCalled();
  });

  // User story WA.D6.OM.J2.A1: a free trial isn't a payment, so it has no invoice; the page says when the
  // first one comes (the trial's end, when the first payment is charged) instead of showing an empty list.
  const FIRST_INVOICE = /No invoices yet\. Your first comes with your first payment on/;
  const trialing = {
    plan: 'monthly_plan',
    effectivePlan: 'monthly_plan',
    status: 'TRIALING',
    trialEnd: '2026-12-07T10:00:00+00:00',
    currentPeriodEnd: '2026-12-07T10:00:00+00:00',
    canActivateTrial: false,
  };

  it('says when the first invoice comes during a trial with none yet', async () => {
    render(<PayfastTransactionHistory />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.transactionHistory.history, { tenantId }),
      apolloMocks: [
        tenantMock(),
        fillPayfastPaymentsQuery([], tenantId),
        fillPayfastInvoicesQuery([], tenantId),
        fillPayfastSubscriptionQuery(trialing, tenantId),
      ],
    });

    expect(await screen.findByText(FIRST_INVOICE)).toBeInTheDocument();
  });

  it('says nothing about a first invoice once there are invoices', async () => {
    render(<PayfastTransactionHistory />, {
      routerProps: createMockRouterProps(RoutesConfig.subscriptions.transactionHistory.history, { tenantId }),
      apolloMocks: [
        tenantMock(),
        fillPayfastPaymentsQuery(payments, tenantId),
        fillPayfastInvoicesQuery(invoices, tenantId),
        fillPayfastSubscriptionQuery(trialing, tenantId),
      ],
    });

    expect(await within(await rowOf('Monthly plan')).findByRole('button', { name: /download invoice/i })).toBeInTheDocument();
    expect(screen.queryByText(FIRST_INVOICE)).not.toBeInTheDocument();
  });
});
