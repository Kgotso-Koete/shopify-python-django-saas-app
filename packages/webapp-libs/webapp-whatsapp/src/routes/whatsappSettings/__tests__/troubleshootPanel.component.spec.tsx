// Tests for the number troubleshooting panel on the WhatsApp page (WhatsApp plan D18, Steps 1.6b and 1.19,
// user story 23).
//
// Kind of test: integration (agents.md section 2.5). Why: the panel renders inside the real page, with the
// real Apollo hooks, router and permission check; the backend is Apollo's MockedProvider, answering with
// the shapes apps/whatsapp/schema.py sends, Meta's explained errors included.
import type { MockedResponse } from '@apollo/client/testing';
import { TenantType as TenantTypeField } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { currentUserPermissionsQuery } from '@sb/webapp-tenants/routes/tenantSettings/tenantRoles/tenantRoles.graphql';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { createMockRouterProps, render } from '@sb/webapp-tenants/tests/utils/rendering';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import { RoutesConfig } from '../../../config/routes';
import {
  registerWhatsAppNumberMutation,
  requestWhatsAppVerificationCodeMutation,
  subscribeWhatsAppAppMutation,
  verifyWhatsAppNumberMutation,
  whatsAppNumberStatusQuery,
} from '../../../graphql/numberTools.graphql';
import { whatsAppAccountsQuery } from '../../../graphql/whatsappAccounts.graphql';
import { WhatsAppSettings } from '../whatsappSettings.component';

const tenantId = 'tenant-whatsapp-test-2';
const accountId = 'account-1';
const ERROR_CODES_DOC = 'https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes';

const accountsMock = () =>
  composeMockedQueryResult(whatsAppAccountsQuery, {
    variables: { tenantId },
    data: {
      whatsAppAccounts: [
        {
          id: accountId,
          purpose: 'EXTERNAL_COMMUNICATIONS',
          phoneNumberId: '100000000000801',
          wabaId: '200000000000801',
          displayPhoneNumber: '27000000801',
          verifiedName: 'Demo Store',
          connectionMethod: 'MANUAL',
          isActive: true,
          credentialsVerifiedAt: '2026-10-18T09:00:00+00:00',
          subscribedAt: null,
          lastMessageReceivedAt: null,
          __typename: 'WhatsAppAccountType',
        },
      ],
    },
  });

const statusMock = () =>
  composeMockedQueryResult(whatsAppNumberStatusQuery, {
    variables: { tenantId, accountId },
    data: {
      whatsAppNumberStatus: {
        status: 'CONNECTED',
        codeVerificationStatus: 'NOT_VERIFIED',
        qualityRating: 'GREEN',
        nameStatus: 'APPROVED',
        verifiedName: 'Demo Store',
        displayPhoneNumber: '+27 00 000 0801',
        __typename: 'WhatsAppNumberStatusType',
      },
    },
  });

const ok = (field: string, typename: string) => ({ data: { [field]: { ok: true, __typename: typename } } });

const renderTab = (permissions: string[], mocks: MockedResponse[]) =>
  render(<WhatsAppSettings />, {
    apolloMocks: [
      fillCommonQueryWithUser(
        currentUserFactory({
          tenants: [tenantFactory({ id: tenantId, name: 'Test Org', type: TenantTypeField.ORGANIZATION })],
        })
      ),
      composeMockedQueryResult(currentUserPermissionsQuery, {
        variables: { tenantId },
        data: { currentUserPermissions: permissions },
      }),
      accountsMock(),
      ...mocks,
    ],
    routerProps: createMockRouterProps(RoutesConfig.whatsapp, { tenantId }),
  });

const MANAGE = ['whatsapp.view', 'whatsapp.manage'];

const openPanel = async (user: ReturnType<typeof userEvent.setup>) => {
  const row = await screen.findByTestId(`whatsapp-account-${accountId}`);
  await user.click(await within(row).findByRole('button', { name: /troubleshoot/i }));
  return within(await screen.findByTestId(`whatsapp-troubleshoot-${accountId}`));
};

describe('TroubleshootPanel: Component', () => {
  it("shows Meta's own status for the number", async () => {
    const user = userEvent.setup();
    renderTab(MANAGE, [statusMock()]);

    const panel = await openPanel(user);

    expect(await panel.findByText('CONNECTED')).toBeInTheDocument();
    expect(panel.getByText('NOT_VERIFIED')).toBeInTheDocument();
    expect(panel.getByText('GREEN')).toBeInTheDocument();
    expect(panel.getByText('APPROVED')).toBeInTheDocument();
  });

  it.each([
    ['SMS', /request a code by sms/i],
    ['VOICE', /request a code by voice call/i],
  ])('requests a code by %s, then verifies it', async (method, buttonName) => {
    const user = userEvent.setup();
    renderTab(MANAGE, [
      statusMock(),
      composeMockedQueryResult(requestWhatsAppVerificationCodeMutation, {
        variables: { input: { tenantId, accountId, method } },
        ...ok('requestWhatsAppVerificationCode', 'RequestWhatsAppVerificationCode'),
      }),
      composeMockedQueryResult(verifyWhatsAppNumberMutation, {
        variables: { input: { tenantId, accountId, code: '123456' } },
        ...ok('verifyWhatsAppNumber', 'VerifyWhatsAppNumber'),
      }),
    ]);

    const panel = await openPanel(user);
    await user.click(panel.getByRole('button', { name: buttonName }));
    expect(await panel.findByText(/code requested/i)).toBeInTheDocument();

    await user.type(panel.getByLabelText(/verification code/i), '123456');
    await user.click(panel.getByRole('button', { name: /verify code/i }));

    expect(await panel.findByText(/number verified/i)).toBeInTheDocument();
  });

  it('registers with a PIN, after warning about the 72-hour limit', async () => {
    const user = userEvent.setup();
    renderTab(MANAGE, [
      statusMock(),
      composeMockedQueryResult(registerWhatsAppNumberMutation, {
        variables: { input: { tenantId, accountId, pin: '654321' } },
        ...ok('registerWhatsAppNumber', 'RegisterWhatsAppNumber'),
      }),
    ]);

    const panel = await openPanel(user);
    expect(panel.getByText(/10 .*attempts .*72 hours/i)).toBeInTheDocument();

    const register = panel.getByRole('button', { name: /register number/i });
    await user.type(panel.getByLabelText(/6-digit pin/i), '12');
    // A PIN is exactly six digits; anything else would waste one of Meta's ten attempts.
    expect(register).toBeDisabled();

    await user.clear(panel.getByLabelText(/6-digit pin/i));
    await user.type(panel.getByLabelText(/6-digit pin/i), '654321');
    await user.click(register);

    expect(await panel.findByText(/number registered/i)).toBeInTheDocument();
  });

  it('re-subscribes the app to the WhatsApp Business account', async () => {
    const user = userEvent.setup();
    renderTab(MANAGE, [
      statusMock(),
      composeMockedQueryResult(subscribeWhatsAppAppMutation, {
        variables: { input: { tenantId, accountId } },
        ...ok('subscribeWhatsAppApp', 'SubscribeWhatsAppApp'),
      }),
    ]);

    const panel = await openPanel(user);
    await user.click(panel.getByRole('button', { name: /re-subscribe the app/i }));

    expect(await panel.findByText(/app subscribed/i)).toBeInTheDocument();
  });

  it("shows Meta's error with its explanation and a link to Meta's page", async () => {
    const user = userEvent.setup();
    const explanation = 'The code is wrong or has expired. Request a new one (Meta error 136025).';
    renderTab(MANAGE, [
      statusMock(),
      composeMockedQueryResult(verifyWhatsAppNumberMutation, {
        variables: { input: { tenantId, accountId, code: '000000' } },
        data: null,
        errors: [
          new GraphQLError('GraphQlValidationError', {
            extensions: { code: [{ message: `${explanation} ${ERROR_CODES_DOC}`, code: 'wrong_code' }] },
          }),
        ],
      }),
    ]);

    const panel = await openPanel(user);
    await user.type(panel.getByLabelText(/verification code/i), '000000');
    await user.click(panel.getByRole('button', { name: /verify code/i }));

    expect(await panel.findByText(new RegExp(explanation.replace(/[.()]/g, '\\$&')))).toBeInTheDocument();
    expect(panel.getByRole('link', { name: ERROR_CODES_DOC })).toHaveAttribute('href', ERROR_CODES_DOC);
  });

  it('is not offered to a member with only whatsapp.view, whom the backend would refuse', async () => {
    renderTab(['whatsapp.view'], []);

    const row = await screen.findByTestId(`whatsapp-account-${accountId}`);

    expect(within(row).queryByRole('button', { name: /troubleshoot/i })).not.toBeInTheDocument();
  });
});
