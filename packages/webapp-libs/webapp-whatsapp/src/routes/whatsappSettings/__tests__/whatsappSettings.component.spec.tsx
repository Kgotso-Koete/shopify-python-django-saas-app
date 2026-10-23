// Tests for the WhatsApp tab in organization settings (WhatsApp plan Steps 1.6 and 1.17, user story 11):
// two forms, one for the internal communications number the team texts and one for the external
// communications numbers store customers text, each with its own examples, button and list.
//
// Kind of test: integration (agents.md section 2.5). Why: the tab renders with the real Apollo hooks,
// router and permission check; the backend is Apollo's MockedProvider, answering with the shapes
// apps/whatsapp/schema.py sends, its errors included.
import type { MockedResponse } from '@apollo/client/testing';
import { TenantType as TenantTypeField } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { RoutesConfig } from '@sb/webapp-tenants/config/routes';
import { currentUserPermissionsQuery } from '@sb/webapp-tenants/routes/tenantSettings/tenantRoles/tenantRoles.graphql';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { createMockRouterProps, render } from '@sb/webapp-tenants/tests/utils/rendering';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import {
  connectWhatsAppAccountMutation,
  disconnectWhatsAppAccountMutation,
  sendWhatsAppTestMessageMutation,
  whatsAppAccountsQuery,
} from '../../../graphql/whatsappAccounts.graphql';
import { WhatsAppSettings } from '../whatsappSettings.component';

const tenantId = 'tenant-whatsapp-test-1';

const INTERNAL = 'INTERNAL_COMMUNICATIONS';
const EXTERNAL = 'EXTERNAL_COMMUNICATIONS';

type AccountOverrides = Partial<{
  id: string;
  purpose: string;
  displayPhoneNumber: string;
  verifiedName: string;
  isActive: boolean;
  credentialsVerifiedAt: string | null;
  subscribedAt: string | null;
  lastMessageReceivedAt: string | null;
}>;

const account = (overrides: AccountOverrides = {}) => ({
  id: 'account-1',
  purpose: EXTERNAL,
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
  ...overrides,
});

const userMock = () =>
  fillCommonQueryWithUser(
    currentUserFactory({
      tenants: [tenantFactory({ id: tenantId, name: 'Test Org', type: TenantTypeField.ORGANIZATION })],
    })
  );

const permissionsMock = (permissions: string[]) =>
  composeMockedQueryResult(currentUserPermissionsQuery, {
    variables: { tenantId },
    data: { currentUserPermissions: permissions },
  });

const accountsMock = (accounts: ReturnType<typeof account>[]) =>
  composeMockedQueryResult(whatsAppAccountsQuery, {
    variables: { tenantId },
    data: { whatsAppAccounts: accounts },
  });

// How apps/whatsapp/schema.py sends a refusal: GraphQlValidationError, the message under the field at fault.
const validationError = (field: string, message: string, code: string) =>
  new GraphQLError('GraphQlValidationError', { extensions: { [field]: [{ message, code }] } });

const MANAGE = ['whatsapp.view', 'whatsapp.manage'];
const VIEW_ONLY = ['whatsapp.view'];

const renderTab = (permissions: string[], mocks: MockedResponse[]) =>
  render(<WhatsAppSettings />, {
    apolloMocks: [userMock(), permissionsMock(permissions), ...mocks],
    routerProps: createMockRouterProps(RoutesConfig.tenant.settings.whatsapp, { tenantId }),
  });

const connectionInput = (purpose = EXTERNAL) => ({
  tenantId,
  purpose,
  phoneNumberId: '100000000000901',
  wabaId: '200000000000901',
  accessToken: 'test-access-token',
});

// Each form has its own section on the tab.
const section = (purpose: string) => screen.findByTestId(`whatsapp-section-${purpose}`);

const fillConnectForm = async (user: ReturnType<typeof userEvent.setup>, purpose = EXTERNAL) => {
  const form = within(await section(purpose));
  const input = connectionInput(purpose);
  await user.type(await form.findByLabelText(/phone number id/i), input.phoneNumberId);
  await user.type(form.getByLabelText(/whatsapp business account id/i), input.wabaId);
  await user.type(form.getByLabelText(/access token/i), input.accessToken);
};

const connectButton = async (purpose = EXTERNAL) =>
  within(await section(purpose)).findByRole('button', { name: /connect number/i });

describe('WhatsAppSettings: Component', () => {
  describe('the two forms', () => {
    it('explains each kind of number with examples', async () => {
      renderTab(MANAGE, [accountsMock([])]);

      const internal = await section(INTERNAL);
      expect(internal).toHaveTextContent(/internal communications number/i);
      expect(internal).toHaveTextContent(/your team texts this number/i);
      expect(internal).toHaveTextContent(/add an item called Winter stock/i);
      const external = await section(EXTERNAL);
      expect(external).toHaveTextContent(/external communications numbers/i);
      expect(external).toHaveTextContent(/your customers text this number/i);
      expect(external).toHaveTextContent(/blue shirts in medium/i);
    });

    it('lists each number under its own form', async () => {
      renderTab(VIEW_ONLY, [
        accountsMock([
          account({ id: 'account-1', purpose: INTERNAL, displayPhoneNumber: '27000000805' }),
          account({ id: 'account-2', purpose: EXTERNAL, displayPhoneNumber: '27000000801' }),
        ]),
      ]);

      expect(await within(await section(INTERNAL)).findByTestId('whatsapp-account-account-1')).toBeInTheDocument();
      expect(within(await section(INTERNAL)).queryByTestId('whatsapp-account-account-2')).not.toBeInTheDocument();
      expect(within(await section(EXTERNAL)).getByTestId('whatsapp-account-account-2')).toBeInTheDocument();
    });

    it('connects the internal number with its purpose', async () => {
      const user = userEvent.setup();
      const connectMock = composeMockedQueryResult(connectWhatsAppAccountMutation, {
        variables: { input: connectionInput(INTERNAL) },
        data: {
          connectWhatsAppAccount: {
            account: {
              id: 'account-9',
              purpose: INTERNAL,
              displayPhoneNumber: '27000000901',
              verifiedName: 'Demo Team',
              subscribedAt: '2026-10-23T09:00:00+00:00',
              __typename: 'WhatsAppAccountType',
            },
            __typename: 'ConnectWhatsAppAccount',
          },
        },
      });
      renderTab(MANAGE, [
        accountsMock([]),
        connectMock,
        accountsMock([account({ id: 'account-9', purpose: INTERNAL, displayPhoneNumber: '27000000901' })]),
      ]);

      await fillConnectForm(user, INTERNAL);
      await user.click(await connectButton(INTERNAL));

      expect(await within(await section(INTERNAL)).findByTestId('whatsapp-connected')).toBeInTheDocument();
      expect(await within(await section(INTERNAL)).findByTestId('whatsapp-account-account-9')).toBeInTheDocument();
    });

    it('shows why a second internal number is refused', async () => {
      const user = userEvent.setup();
      const reason = 'Your organization\'s team already texts 27000000805. Disconnect it first to connect another.';
      renderTab(MANAGE, [
        accountsMock([account({ id: 'account-1', purpose: INTERNAL, displayPhoneNumber: '27000000805' })]),
        composeMockedQueryResult(connectWhatsAppAccountMutation, {
          variables: { input: connectionInput(INTERNAL) },
          data: null,
          errors: [validationError('non_field_errors', reason, 'internal_number_exists')],
        }),
      ]);

      await fillConnectForm(user, INTERNAL);
      await user.click(await connectButton(INTERNAL));

      expect(await within(await section(INTERNAL)).findByText(reason)).toBeInTheDocument();
    });
  });

  describe('the numbers', () => {
    it('lists each number with the proofs it has passed', async () => {
      renderTab(VIEW_ONLY, [
        accountsMock([
          account({
            id: 'account-1',
            displayPhoneNumber: '27000000802',
            subscribedAt: '2026-10-18T10:00:00+00:00',
            lastMessageReceivedAt: '2026-10-18T11:00:00+00:00',
          }),
          account({ id: 'account-2', displayPhoneNumber: '27000000804', isActive: false }),
        ]),
      ]);

      const working = await screen.findByTestId('whatsapp-account-account-1');
      expect(working).toHaveTextContent('27000000802');
      expect(working).toHaveTextContent('Demo Store');
      expect(within(working).getByText(/^credentials verified$/i)).toBeInTheDocument();
      expect(within(working).getByText(/^app subscribed$/i)).toBeInTheDocument();
      expect(within(working).getByText(/^message received$/i)).toBeInTheDocument();
      expect(within(screen.getByTestId('whatsapp-account-account-2')).getByText(/^disconnected$/i)).toBeInTheDocument();
    });

    it('says when no number is connected', async () => {
      renderTab(VIEW_ONLY, [accountsMock([])]);

      expect(await within(await section(INTERNAL)).findByText(/no number connected yet/i)).toBeInTheDocument();
      expect(within(await section(EXTERNAL)).getByText(/no number connected yet/i)).toBeInTheDocument();
    });

    it('says the numbers could not be loaded, rather than that there are none', async () => {
      renderTab(VIEW_ONLY, [
        composeMockedQueryResult(whatsAppAccountsQuery, {
          variables: { tenantId },
          data: null,
          errors: [new GraphQLError('Something went wrong')],
        }),
      ]);

      expect(await screen.findByTestId('whatsapp-accounts-error')).toBeInTheDocument();
      expect(screen.queryByText(/no number connected yet/i)).not.toBeInTheDocument();
    });

    it('shows a member with only whatsapp.view the status but no form and no buttons', async () => {
      renderTab(VIEW_ONLY, [accountsMock([account()])]);

      expect(await screen.findByTestId('whatsapp-account-account-1')).toBeInTheDocument();
      expect(screen.queryByTestId('whatsapp-connect-form')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /send test message/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /disconnect/i })).not.toBeInTheDocument();
    });
  });

  describe('connecting a number', () => {
    it('checks the required fields without asking the backend', async () => {
      const user = userEvent.setup();
      const connectMock = composeMockedQueryResult(connectWhatsAppAccountMutation, {
        variables: { input: connectionInput() },
        data: null,
      });
      renderTab(MANAGE, [accountsMock([]), connectMock]);

      await user.click(await connectButton());

      expect(await screen.findByText(/phone number id is required/i)).toBeInTheDocument();
      expect(screen.getByText(/whatsapp business account id is required/i)).toBeInTheDocument();
      expect(screen.getByText(/access token is required/i)).toBeInTheDocument();
      expect(connectMock.result).not.toHaveBeenCalled();
    });

    it('asks for no App secret: every number is on our Meta app', async () => {
      renderTab(MANAGE, [accountsMock([])]);

      expect(await within(await section(EXTERNAL)).findByLabelText(/access token/i)).toBeInTheDocument();
      expect(screen.queryByLabelText(/app secret/i)).not.toBeInTheDocument();
    });

    it("shows Meta's rejection under the access token", async () => {
      const user = userEvent.setup();
      const rejection = 'Meta rejected this access token (Meta error 190). Generate a new one and try again.';
      renderTab(MANAGE, [
        accountsMock([]),
        composeMockedQueryResult(connectWhatsAppAccountMutation, {
          variables: { input: connectionInput() },
          data: null,
          errors: [validationError('access_token', rejection, 'token_rejected')],
        }),
      ]);

      await fillConnectForm(user);
      await user.click(await connectButton());

      expect(await screen.findByText(rejection)).toBeInTheDocument();
      expect(screen.queryByTestId('whatsapp-connected')).not.toBeInTheDocument();
    });

    it('says the number is connected and ready for messages, and lists it', async () => {
      const user = userEvent.setup();
      const connected = account({ id: 'account-9', displayPhoneNumber: '27000000901' });
      renderTab(MANAGE, [
        accountsMock([]),
        composeMockedQueryResult(connectWhatsAppAccountMutation, {
          variables: { input: connectionInput() },
          data: {
            connectWhatsAppAccount: {
              account: {
                id: 'account-9',
                purpose: EXTERNAL,
                displayPhoneNumber: '27000000901',
                verifiedName: 'Demo Store',
                subscribedAt: '2026-10-23T09:00:00+00:00',
                __typename: 'WhatsAppAccountType',
              },
              __typename: 'ConnectWhatsAppAccount',
            },
          },
        }),
        accountsMock([connected]),
      ]);

      await fillConnectForm(user);
      await user.click(await connectButton());

      const shown = await screen.findByTestId('whatsapp-connected');
      expect(shown).toHaveTextContent('27000000901 is connected');
      expect(shown).toHaveTextContent(/messages to it now reach this app/i);
      // The operator sets our app's webhook once; there's nothing for the organization to paste.
      expect(shown).not.toHaveTextContent(/verify token/i);

      expect(await screen.findByTestId('whatsapp-account-account-9')).toBeInTheDocument();
    });
  });

  describe('a connected number', () => {
    it("sends the test message and shows Meta's message id", async () => {
      const user = userEvent.setup();
      renderTab(MANAGE, [
        accountsMock([account()]),
        composeMockedQueryResult(sendWhatsAppTestMessageMutation, {
          variables: { input: { tenantId, accountId: 'account-1', to: '083 000 0001' } },
          data: { sendWhatsAppTestMessage: { messageId: 'wamid.TEST1', __typename: 'SendWhatsAppTestMessage' } },
        }),
      ]);

      const row = await screen.findByTestId('whatsapp-account-account-1');
      // The manage controls appear once the permissions have loaded.
      await user.type(await within(row).findByLabelText(/send a test message to/i), '083 000 0001');
      await user.click(within(row).getByRole('button', { name: /send test message/i }));

      expect(await within(row).findByText(/wamid\.TEST1/)).toBeInTheDocument();
    });

    it("shows why Meta refused the test message", async () => {
      const user = userEvent.setup();
      const reason = 'Meta can only send to numbers added as test recipients (Meta error 131030).';
      renderTab(MANAGE, [
        accountsMock([account()]),
        composeMockedQueryResult(sendWhatsAppTestMessageMutation, {
          variables: { input: { tenantId, accountId: 'account-1', to: '083 000 0001' } },
          data: null,
          errors: [validationError('non_field_errors', reason, 'meta_refused')],
        }),
      ]);

      const row = await screen.findByTestId('whatsapp-account-account-1');
      await user.type(await within(row).findByLabelText(/send a test message to/i), '083 000 0001');
      await user.click(within(row).getByRole('button', { name: /send test message/i }));

      expect(await within(row).findByText(reason)).toBeInTheDocument();
    });

    it('disconnects only after the admin confirms', async () => {
      const user = userEvent.setup();
      const disconnectMock = composeMockedQueryResult(disconnectWhatsAppAccountMutation, {
        variables: { input: { tenantId, accountId: 'account-1' } },
        data: {
          disconnectWhatsAppAccount: {
            account: { id: 'account-1', isActive: false, __typename: 'WhatsAppAccountType' },
            __typename: 'DisconnectWhatsAppAccount',
          },
        },
      });
      renderTab(MANAGE, [accountsMock([account()]), disconnectMock, accountsMock([account({ isActive: false })])]);

      const row = await screen.findByTestId('whatsapp-account-account-1');
      await user.click(await within(row).findByRole('button', { name: /disconnect/i }));
      await user.click(await screen.findByRole('button', { name: /cancel/i }));
      expect(disconnectMock.result).not.toHaveBeenCalled();

      await user.click(within(row).getByRole('button', { name: /disconnect/i }));
      await user.click(await screen.findByRole('button', { name: /^disconnect number$/i }));

      await waitFor(() => expect(disconnectMock.result).toHaveBeenCalled());
      expect(await within(screen.getByTestId('whatsapp-account-account-1')).findByText(/^disconnected$/i)).toBeInTheDocument();
    });
  });
});
