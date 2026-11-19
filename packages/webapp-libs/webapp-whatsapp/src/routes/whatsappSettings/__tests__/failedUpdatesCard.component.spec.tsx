// Tests for the order updates WhatsApp couldn't deliver, on the WhatsApp page (WhatsApp plan Step 4.7, user story
// WA.D3.OM.J2.A3, decided 2026-11-08): each with Meta's reason in plain words, and Send again once the cause is
// fixed, which asks Shopify for the order and builds the update fresh on the backend.
//
// Kind of test: integration (agents.md section 2.5). Why: the card renders with the app's providers and the
// real Apollo hooks; the backend is Apollo's MockedProvider, answering with the shapes
// apps/whatsapp_shop/schema.py sends, its refusals included.
import { TenantType as TenantTypeField } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { render } from '@sb/webapp-tenants/tests/utils/rendering';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import {
  sendWhatsAppOrderUpdateAgainMutation,
  whatsAppFailedOrderUpdatesQuery,
} from '../../../graphql/failedOrderUpdates.graphql';
import { FailedUpdatesCard } from '../failedUpdatesCard.component';

const tenantId = 'tenant-whatsapp-test-3';

const failedUpdate = (overrides: Partial<Record<string, unknown>> = {}) => ({
  checkoutId: '41',
  stage: 'PAID',
  accountId: 'account-1',
  number: '27000000801',
  customer: 'Thandi',
  failedAt: '2026-11-08T09:00:00+00:00',
  errorCode: 190,
  reason: "Meta rejected the number's access token: it expired or was revoked.",
  __typename: 'WhatsAppFailedOrderUpdateType',
  ...overrides,
});

const userMock = () =>
  fillCommonQueryWithUser(
    currentUserFactory({
      tenants: [tenantFactory({ id: tenantId, name: 'Test Org', type: TenantTypeField.ORGANIZATION })],
    })
  );

const failedMock = (updates: ReturnType<typeof failedUpdate>[]) =>
  composeMockedQueryResult(whatsAppFailedOrderUpdatesQuery, {
    variables: { tenantId },
    data: { whatsAppFailedOrderUpdates: updates },
  });

const sendAgainInput = { tenantId, checkoutId: '41', stage: 'PAID' };

const renderCard = (canManage: boolean, mocks: ReturnType<typeof failedMock>[]) =>
  render(<FailedUpdatesCard tenantId={tenantId} canManage={canManage} />, { apolloMocks: [userMock(), ...mocks] });

describe('FailedUpdatesCard', () => {
  it("WA.D3.OM.J2.A3 lists each failed update with its stage, customer, number and Meta's reason", async () => {
    renderCard(false, [failedMock([failedUpdate()])]);

    const row = await screen.findByTestId('whatsapp-failed-update-41-PAID');
    expect(row).toHaveTextContent(/order paid/i);
    expect(row).toHaveTextContent('Thandi');
    expect(row).toHaveTextContent('27000000801');
    expect(row).toHaveTextContent(/access token/i);
  });

  it('WA.D3.OM.J2.A3 shows nothing when no update failed', async () => {
    const mock = failedMock([]);
    renderCard(true, [mock]);

    await waitFor(() => expect(mock.result).toHaveBeenCalled());
    expect(screen.queryByTestId('whatsapp-failed-updates')).not.toBeInTheDocument();
  });

  it('WA.D3.OM.J2.A3 Send again sends it and the list refreshes', async () => {
    const user = userEvent.setup();
    const sendMock = composeMockedQueryResult(sendWhatsAppOrderUpdateAgainMutation, {
      variables: { input: sendAgainInput },
      data: {
        sendWhatsAppOrderUpdateAgain: {
          checkoutId: '41',
          stage: 'PAID',
          __typename: 'SendWhatsAppOrderUpdateAgain',
        },
      },
    });
    renderCard(true, [failedMock([failedUpdate()]), sendMock, failedMock([])]);

    await user.click(await screen.findByRole('button', { name: /send again/i }));

    await waitFor(() => expect(sendMock.result).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('whatsapp-failed-update-41-PAID')).not.toBeInTheDocument());
  });

  it("WA.D3.OM.J2.A3 Send again's refusal shows the reason", async () => {
    const user = userEvent.setup();
    const refused = {
      ...composeMockedQueryResult(sendWhatsAppOrderUpdateAgainMutation, {
        variables: { input: sendAgainInput },
        data: null,
      }),
      result: {
        errors: [
          new GraphQLError('GraphQlValidationError', {
            extensions: {
              non_field_errors: [
                {
                  message: 'The store must be reconnected on the Shopify page before this update can be sent.',
                  code: 'reconnect',
                },
              ],
            },
          }),
        ],
      },
    };
    renderCard(true, [failedMock([failedUpdate()]), refused]);

    await user.click(await screen.findByRole('button', { name: /send again/i }));

    expect(await screen.findByText(/the store must be reconnected/i)).toBeInTheDocument();
  });

  it('WA.D3.OM.J2.A3 without whatsapp.manage there is no Send again', async () => {
    renderCard(false, [failedMock([failedUpdate()])]);

    expect(await screen.findByTestId('whatsapp-failed-update-41-PAID')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /send again/i })).not.toBeInTheDocument();
  });
});
