// Tests for the organization's WhatsApp page, in the sidebar (WhatsApp plan Steps 1.6, 1.17 and 1.19,
// user story 11). Since Step 2.7 (decision 4) it has one form, asking who texts the number (the team,
// the customers, or both), and one list of every number with whom it serves, which an admin can change.
//
// Kind of test: integration (agents.md section 2.5). Why: the page renders with the real Apollo hooks,
// router and permission check; the backend is Apollo's MockedProvider, answering with the shapes
// apps/whatsapp/schema.py sends, its errors included.
import type { MockedResponse } from '@apollo/client/testing';
import { TenantType as TenantTypeField } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { organizationFeaturesQuery } from '@sb/webapp-tenants/hooks';
import { currentUserPermissionsQuery } from '@sb/webapp-tenants/routes/tenantSettings/tenantRoles/tenantRoles.graphql';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { createMockRouterProps, render } from '@sb/webapp-tenants/tests/utils/rendering';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import { RoutesConfig } from '../../../config/routes';
import {
  changeWhatsAppNumberPurposeMutation,
  connectWhatsAppAccountMutation,
  disconnectWhatsAppAccountMutation,
  sendWhatsAppTestMessageMutation,
  whatsAppAccountsQuery,
} from '../../../graphql/whatsappAccounts.graphql';
import {
  regenerateWhatsAppMetaAppVerifyTokenMutation,
  registerWhatsAppMetaAppMutation,
  removeWhatsAppMetaAppMutation,
  setWhatsAppNumberMetaAppMutation,
  updateWhatsAppMetaAppSecretMutation,
  whatsAppMetaAppsQuery,
} from '../../../graphql/whatsappMetaApps.graphql';
import {
  chooseWhatsAppStoreMutation,
  setWhatsAppStorefrontModeMutation,
  whatsAppEligibleStoresQuery,
  whatsAppStorefrontsQuery,
} from '../../../graphql/whatsappStorefronts.graphql';
import { WhatsAppSettings } from '../whatsappSettings.component';

const tenantId = 'tenant-whatsapp-test-1';

const INTERNAL = 'INTERNAL_COMMUNICATIONS';
const EXTERNAL = 'EXTERNAL_COMMUNICATIONS';
// One number for the team and the customers (Step 2.7).
const BOTH = 'INTERNAL_AND_EXTERNAL_COMMUNICATIONS';

type AccountOverrides = Partial<{
  id: string;
  purpose: string;
  displayPhoneNumber: string;
  verifiedName: string;
  isActive: boolean;
  credentialsVerifiedAt: string | null;
  subscribedAt: string | null;
  lastMessageReceivedAt: string | null;
  metaAppId: string | null;
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
  // This service's Meta app (Step 2.9).
  metaAppId: null,
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

// What the organization's plan unlocks (WhatsApp plan phase 3, decision 8): WhatsApp, unless a test says not.
const featuresMock = (features: string[]) =>
  composeMockedQueryResult(organizationFeaturesQuery, {
    variables: { tenantId },
    data: { organizationFeatures: features },
  });
const UNLOCKED = ['SHOPIFY', 'WHATSAPP'];

// Which store each external number sells from (Step 2.1b, apps/whatsapp_shop/schema.py).
const STORE = 'demo-store.myshopify.com';
const OTHER_STORE = 'second-store.myshopify.com';

// The mode is menus or the assistant for the number's customers (phase 2, decision 2); null without a store.
const storefront = (accountId: string, shopDomain: string | null, conversationMode: string | null = null) => ({
  accountId,
  shopDomain,
  conversationMode: shopDomain ? (conversationMode ?? 'WHATSAPP_FORM') : null,
  __typename: 'WhatsAppStorefrontType',
});

// `reuse` answers every later fetch too, for the default mocks renderTab adds.
const storefrontsMock = (storefronts: ReturnType<typeof storefront>[], { reuse = false } = {}) => ({
  ...composeMockedQueryResult(whatsAppStorefrontsQuery, {
    variables: { tenantId },
    data: { whatsAppStorefronts: storefronts },
  }),
  ...(reuse ? { maxUsageCount: Number.POSITIVE_INFINITY } : {}),
});

const eligibleStoresMock = (domains: string[], { reuse = false } = {}) => ({
  ...composeMockedQueryResult(whatsAppEligibleStoresQuery, {
    variables: { tenantId },
    data: { whatsAppEligibleStores: domains },
  }),
  ...(reuse ? { maxUsageCount: Number.POSITIVE_INFINITY } : {}),
});

const chooseStoreMock = (accountId: string, shopDomain: string) =>
  composeMockedQueryResult(chooseWhatsAppStoreMutation, {
    variables: { input: { tenantId, accountId, shopDomain } },
    data: {
      chooseWhatsAppStore: { storefront: storefront(accountId, shopDomain), __typename: 'ChooseWhatsAppStore' },
    },
  });

// One of the organization's own Meta apps (Step 2.9), as apps/whatsapp/schema.py lists it.
const META_APP_ID = '1234567890123456';
const metaApp = (overrides: Partial<{ id: string; appId: string; verifyToken: string }> = {}) => ({
  id: 'meta-app-1',
  appId: META_APP_ID,
  webhookUrl: 'https://api.example.com/api/whatsapp/webhook/aBcD1234eFgH5678iJkL/',
  verifyToken: 'generated-verify-token-1',
  createdAt: '2026-11-01T09:00:00+00:00',
  __typename: 'WhatsAppMetaAppType',
  ...overrides,
});

const metaAppsMock = (apps: ReturnType<typeof metaApp>[], { reuse = false } = {}) => ({
  ...composeMockedQueryResult(whatsAppMetaAppsQuery, {
    variables: { tenantId },
    data: { whatsAppMetaApps: apps },
  }),
  ...(reuse ? { maxUsageCount: Number.POSITIVE_INFINITY } : {}),
});

type StoreOptions = {
  storefronts?: ReturnType<typeof storefront>[];
  eligible?: string[];
  features?: string[];
  metaApps?: ReturnType<typeof metaApp>[];
};

// By default no number has a store yet, the organization has one store that can sell on WhatsApp, no
// Meta app of its own, and its plan includes WhatsApp.
const renderTab = (
  permissions: string[],
  mocks: MockedResponse[],
  { storefronts = [], eligible = [STORE], features = UNLOCKED, metaApps = [] }: StoreOptions = {}
) =>
  render(<WhatsAppSettings />, {
    apolloMocks: [
      userMock(),
      permissionsMock(permissions),
      ...mocks,
      storefrontsMock(storefronts, { reuse: true }),
      eligibleStoresMock(eligible, { reuse: true }),
      metaAppsMock(metaApps, { reuse: true }),
      { ...featuresMock(features), maxUsageCount: Number.POSITIVE_INFINITY },
    ],
    routerProps: createMockRouterProps(RoutesConfig.whatsapp, { tenantId }),
  });

const connectionInput = (purpose = EXTERNAL) => ({
  tenantId,
  purpose,
  phoneNumberId: '100000000000901',
  wabaId: '200000000000901',
  accessToken: 'test-access-token',
});

// Since Step 2.7 (decision 4) one form asks who texts the number, and one list shows every number.
const connectForm = () => screen.findByTestId('whatsapp-connect-form');

const WHO = { [INTERNAL]: /^your team$/i, [EXTERNAL]: /^your customers$/i, [BOTH]: /^both/i } as const;

const chooseWho = async (user: ReturnType<typeof userEvent.setup>, purpose: keyof typeof WHO) =>
  user.click(await within(await connectForm()).findByRole('radio', { name: WHO[purpose] }));

const fillConnectForm = async (user: ReturnType<typeof userEvent.setup>, purpose: keyof typeof WHO = EXTERNAL) => {
  await chooseWho(user, purpose);
  const form = within(await connectForm());
  const input = connectionInput(purpose);
  await user.type(await form.findByLabelText(/phone number id/i), input.phoneNumberId);
  await user.type(form.getByLabelText(/whatsapp business account id/i), input.wabaId);
  await user.type(form.getByLabelText(/access token/i), input.accessToken);
};

const connectButton = async () => within(await connectForm()).findByRole('button', { name: /connect number/i });

describe('WhatsAppSettings: Component', () => {
  // Step 1.19: its own page, reached from the sidebar, so it carries its own heading.
  it('is a page of its own, with a heading saying what it is for', async () => {
    renderTab(VIEW_ONLY, [accountsMock([])]);

    expect(await screen.findByRole('heading', { level: 1, name: /^whatsapp$/i })).toBeInTheDocument();
    expect(screen.getByText(/the numbers your team and your customers text/i)).toBeInTheDocument();
  });

  // Step 2.7: one number for both, or two numbers kept apart (decisions 1 and 4).
  describe('the two setups', () => {
    it('explains one number for both and two numbers kept apart, with examples', async () => {
      renderTab(MANAGE, [accountsMock([])]);

      const numbers = await screen.findByTestId('whatsapp-numbers');
      expect(numbers).toHaveTextContent(/one number for both/i);
      expect(numbers).toHaveTextContent(/two numbers kept apart/i);
      expect(numbers).toHaveTextContent(/add an item called Winter stock/i);
      expect(numbers).toHaveTextContent(/blue shirts in medium/i);
    });

    it('lists every number in one list, each saying who texts it', async () => {
      renderTab(VIEW_ONLY, [
        accountsMock([
          account({ id: 'account-1', purpose: INTERNAL, displayPhoneNumber: '27000000805' }),
          account({ id: 'account-2', purpose: EXTERNAL, displayPhoneNumber: '27000000801' }),
          account({ id: 'account-3', purpose: BOTH, displayPhoneNumber: '27000000806' }),
        ]),
      ]);

      const list = within(await screen.findByTestId('whatsapp-numbers-list'));
      expect(await list.findByTestId('whatsapp-purpose-account-1')).toHaveTextContent(/^your team$/i);
      expect(list.getByTestId('whatsapp-purpose-account-2')).toHaveTextContent(/^your customers$/i);
      expect(list.getByTestId('whatsapp-purpose-account-3')).toHaveTextContent(/^your team and your customers$/i);
    });

    it('asks who texts a number before connecting it', async () => {
      const user = userEvent.setup();
      const connectMock = composeMockedQueryResult(connectWhatsAppAccountMutation, {
        variables: { input: connectionInput() },
        data: null,
      });
      renderTab(MANAGE, [accountsMock([]), connectMock]);

      await user.click(await connectButton());

      expect(await screen.findByText(/choose who texts this number/i)).toBeInTheDocument();
      expect(connectMock.result).not.toHaveBeenCalled();
    });

    it('connects one number for both, with its store', async () => {
      const user = userEvent.setup();
      const chooseMock = chooseStoreMock('account-9', STORE);
      renderTab(MANAGE, [
        accountsMock([]),
        composeMockedQueryResult(connectWhatsAppAccountMutation, {
          variables: { input: connectionInput(BOTH) },
          data: {
            connectWhatsAppAccount: {
              account: {
                id: 'account-9',
                purpose: BOTH,
                displayPhoneNumber: '27000000901',
                verifiedName: 'Demo Store',
                subscribedAt: '2026-10-23T09:00:00+00:00',
                __typename: 'WhatsAppAccountType',
              },
              __typename: 'ConnectWhatsAppAccount',
            },
          },
        }),
        chooseMock,
        accountsMock([account({ id: 'account-9', purpose: BOTH, displayPhoneNumber: '27000000901' })]),
      ]);

      await fillConnectForm(user, BOTH);
      await user.click(await connectButton());

      await waitFor(() => expect(chooseMock.result).toHaveBeenCalled());
      expect(await screen.findByTestId('whatsapp-purpose-account-9')).toHaveTextContent(/your team and your customers/i);
    });

    it('connects the team number with its purpose, with no store', async () => {
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
      // The team's number never sells, so there's no store to choose.
      expect(within(await connectForm()).queryByLabelText(/^store$/i)).not.toBeInTheDocument();
      await user.click(await connectButton());

      expect(await screen.findByTestId('whatsapp-connected')).toBeInTheDocument();
      expect(await screen.findByTestId('whatsapp-account-account-9')).toBeInTheDocument();
    });

    it('shows why a second team number is refused', async () => {
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
      await user.click(await connectButton());

      expect(await within(await connectForm()).findByText(reason)).toBeInTheDocument();
    });
  });

  // Step 2.7, decisions 2 and 3: an admin changes whom a connected number serves, after confirming.
  describe('changing whom a number serves', () => {
    it('changes the team number to serve customers too, after the admin confirms', async () => {
      const user = userEvent.setup();
      const changeMock = composeMockedQueryResult(changeWhatsAppNumberPurposeMutation, {
        variables: { input: { tenantId, accountId: 'account-1', purpose: BOTH } },
        data: {
          changeWhatsAppNumberPurpose: {
            account: { id: 'account-1', purpose: BOTH, __typename: 'WhatsAppAccountType' },
            __typename: 'ChangeWhatsAppNumberPurpose',
          },
        },
      });
      renderTab(MANAGE, [
        accountsMock([account({ id: 'account-1', purpose: INTERNAL })]),
        changeMock,
        accountsMock([account({ id: 'account-1', purpose: BOTH })]),
      ]);

      const row = within(await screen.findByTestId('whatsapp-account-account-1'));
      await user.selectOptions(await row.findByLabelText(/who texts this number/i), BOTH);
      await user.click(row.getByRole('button', { name: /^change$/i }));
      // The dialog says what changes before anything does.
      expect(await screen.findByText(/members linked on it are unlinked/i)).toBeInTheDocument();
      await user.click(await screen.findByRole('button', { name: /^change whom it serves$/i }));

      await waitFor(() => expect(changeMock.result).toHaveBeenCalled());
      await waitFor(() =>
        expect(row.getByTestId('whatsapp-purpose-account-1')).toHaveTextContent(/your team and your customers/i)
      );
      // Step 2.8, finding 14.
      expect(await screen.findByTestId('toast-1')).toHaveTextContent(/now serves your team and your customers/i);
    });

    it('offers a member no change', async () => {
      renderTab(VIEW_ONLY, [accountsMock([account({ id: 'account-1', purpose: INTERNAL })])]);

      const row = within(await screen.findByTestId('whatsapp-account-account-1'));
      expect(await row.findByTestId('whatsapp-purpose-account-1')).toBeInTheDocument();
      expect(row.queryByLabelText(/who texts this number/i)).not.toBeInTheDocument();
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

      expect(await screen.findByText(/no number connected yet/i)).toBeInTheDocument();
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

    it('asks for no App secret: an App secret is registered once, with its Meta app (Step 2.9)', async () => {
      renderTab(MANAGE, [accountsMock([])]);

      const form = within(await connectForm());
      expect(await form.findByLabelText(/access token/i)).toBeInTheDocument();
      expect(form.queryByLabelText(/app secret/i)).not.toBeInTheDocument();
    });

    it('says the access token must be a permanent one', async () => {
      renderTab(MANAGE, [accountsMock([])]);

      expect(await within(await connectForm()).findByText(/a system user's permanent token/i)).toBeInTheDocument();
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
        // The second call (Step 2.1b, decision 5): the number now sells from the one store offered.
        chooseStoreMock('account-9', STORE),
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

  // Step 2.1b, user story 25: each external number sells from one of the organization's stores.
  describe('the store an external number sells from', () => {
    const connected = {
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
    };

    it('connects the number, then saves the store chosen in the same form', async () => {
      const user = userEvent.setup();
      const chooseMock = chooseStoreMock('account-9', OTHER_STORE);
      renderTab(
        MANAGE,
        [
          accountsMock([]),
          composeMockedQueryResult(connectWhatsAppAccountMutation, {
            variables: { input: connectionInput() },
            data: connected,
          }),
          chooseMock,
          accountsMock([account({ id: 'account-9', displayPhoneNumber: '27000000901' })]),
        ],
        { eligible: [STORE, OTHER_STORE] }
      );

      await fillConnectForm(user);
      const form = within(await connectForm());
      // With two stores, the admin picks one: none is chosen for them. The list arrives first.
      await form.findByRole('option', { name: OTHER_STORE });
      await user.selectOptions(form.getByLabelText(/^store$/i), OTHER_STORE);
      await user.click(await connectButton());

      await waitFor(() => expect(chooseMock.result).toHaveBeenCalled());
      expect(await screen.findByTestId('whatsapp-connected')).toHaveTextContent('27000000901 is connected');
    });

    it("preselects the organization's only store", async () => {
      const user = userEvent.setup();
      renderTab(MANAGE, [accountsMock([])]);

      await chooseWho(user, EXTERNAL);
      const picker = await within(await connectForm()).findByLabelText(/^store$/i);
      await waitFor(() => expect(picker).toHaveValue(STORE));
    });

    it('asks for a store before connecting when there are several', async () => {
      const user = userEvent.setup();
      const connectMock = composeMockedQueryResult(connectWhatsAppAccountMutation, {
        variables: { input: connectionInput() },
        data: connected,
      });
      renderTab(MANAGE, [accountsMock([]), connectMock], { eligible: [STORE, OTHER_STORE] });

      await fillConnectForm(user);
      await user.click(await connectButton());

      expect(await screen.findByText(/choose the store this number sells from/i)).toBeInTheDocument();
      expect(connectMock.result).not.toHaveBeenCalled();
    });

    it('says to connect a store on the Shopify page first when none can sell on WhatsApp', async () => {
      const user = userEvent.setup();
      renderTab(MANAGE, [accountsMock([])], { eligible: [] });

      for (const purpose of [EXTERNAL, BOTH] as const) {
        await chooseWho(user, purpose);
        const form = within(await connectForm());
        expect(await form.findByText(/connect a shopify store on the shopify page first/i)).toBeInTheDocument();
        expect(await connectButton()).toBeDisabled();
      }
      // The team's number needs no store.
      await chooseWho(user, INTERNAL);
      expect(await connectButton()).toBeEnabled();
    });

    it("keeps the number connected and says so when the store couldn't be saved", async () => {
      const user = userEvent.setup();
      const reason = "demo-store.myshopify.com can't sell on WhatsApp yet. Reconnect it on the Shopify page.";
      renderTab(MANAGE, [
        accountsMock([]),
        composeMockedQueryResult(connectWhatsAppAccountMutation, {
          variables: { input: connectionInput() },
          data: connected,
        }),
        composeMockedQueryResult(chooseWhatsAppStoreMutation, {
          variables: { input: { tenantId, accountId: 'account-9', shopDomain: STORE } },
          data: null,
          errors: [validationError('shop_domain', reason, 'store_not_eligible')],
        }),
        accountsMock([account({ id: 'account-9', displayPhoneNumber: '27000000901' })]),
      ]);

      await fillConnectForm(user);
      await user.click(await connectButton());

      expect(await screen.findByTestId('whatsapp-connected')).toBeInTheDocument();
      expect(await screen.findByText(reason)).toBeInTheDocument();
    });

    it('shows on each external row the store it sells from, or that none is chosen', async () => {
      renderTab(
        VIEW_ONLY,
        [
          accountsMock([
            account({ id: 'account-1', purpose: INTERNAL, displayPhoneNumber: '27000000805' }),
            account({ id: 'account-2', displayPhoneNumber: '27000000802' }),
            account({ id: 'account-3', displayPhoneNumber: '27000000803' }),
          ]),
        ],
        { storefronts: [storefront('account-2', STORE), storefront('account-3', null)] }
      );

      // The store's name is in bold, so each line is checked as a whole.
      await waitFor(async () =>
        expect(await screen.findByTestId('whatsapp-store-account-2')).toHaveTextContent(/sells from demo-store\.myshopify\.com/i)
      );
      expect(screen.getByTestId('whatsapp-store-account-3')).toHaveTextContent(/no store chosen/i);
      // The team's number never sells from a store.
      expect(screen.queryByTestId('whatsapp-store-account-1')).not.toBeInTheDocument();
      // A Member sees the store, but can't change it.
      expect(screen.queryByRole('button', { name: /save store/i })).not.toBeInTheDocument();
    });

    it('shows no store line on a disconnected number, which gets no messages', async () => {
      renderTab(
        MANAGE,
        [
          accountsMock([
            account({ id: 'account-2', displayPhoneNumber: '27000000802' }),
            account({ id: 'account-4', displayPhoneNumber: '27000000804', isActive: false }),
          ]),
        ],
        { storefronts: [storefront('account-2', STORE), storefront('account-4', null)] }
      );

      await waitFor(async () =>
        expect(await screen.findByTestId('whatsapp-store-account-2')).toHaveTextContent(/sells from demo-store/i)
      );
      expect(await screen.findByTestId('whatsapp-account-account-4')).toBeInTheDocument();
      expect(screen.queryByTestId('whatsapp-store-account-4')).not.toBeInTheDocument();
    });

    it("lets an admin change a number's store on its row", async () => {
      const user = userEvent.setup();
      const chooseMock = chooseStoreMock('account-2', OTHER_STORE);
      renderTab(
        MANAGE,
        [
          accountsMock([account({ id: 'account-2', displayPhoneNumber: '27000000802' })]),
          storefrontsMock([storefront('account-2', STORE)]),
          chooseMock,
          accountsMock([account({ id: 'account-2', displayPhoneNumber: '27000000802' })]),
          storefrontsMock([storefront('account-2', OTHER_STORE)]),
        ],
        { eligible: [STORE, OTHER_STORE] }
      );

      const row = within(await screen.findByTestId('whatsapp-account-account-2'));
      await waitFor(() => expect(row.getByTestId('whatsapp-store-account-2')).toHaveTextContent(/sells from demo-store/i));
      await row.findByRole('option', { name: OTHER_STORE });
      await user.selectOptions(row.getByLabelText(/change store/i), OTHER_STORE);
      await user.click(row.getByRole('button', { name: /save store/i }));

      await waitFor(() => expect(chooseMock.result).toHaveBeenCalled());
      await waitFor(() =>
        expect(row.getByTestId('whatsapp-store-account-2')).toHaveTextContent(/sells from second-store\.myshopify\.com/i)
      );
      // Step 2.8, finding 14.
      expect(await screen.findByTestId('toast-1')).toHaveTextContent(/now sells from second-store\.myshopify\.com/i);
    });
  });

  // Phase 2, decision 2: the number's own setting, not the customer's; menus by default.
  describe("how a number's customers are answered", () => {
    it('says the external numbers answer customers now', async () => {
      renderTab(MANAGE, [accountsMock([])]);

      const numbers = await screen.findByTestId('whatsapp-numbers');
      expect(numbers).not.toHaveTextContent(/arrives in a later release/i);
      expect(numbers).toHaveTextContent(/browse, search, fill a cart and check out/i);
    });

    it('shows a member whether customers get menus or the assistant', async () => {
      renderTab(
        VIEW_ONLY,
        [
          accountsMock([
            account({ id: 'account-2', displayPhoneNumber: '27000000802' }),
            account({ id: 'account-3', displayPhoneNumber: '27000000803' }),
          ]),
        ],
        { storefronts: [storefront('account-2', STORE), storefront('account-3', STORE, 'AGENTIC')] }
      );

      await waitFor(async () =>
        expect(await screen.findByTestId('whatsapp-mode-account-2')).toHaveTextContent(/customers get menus/i)
      );
      expect(screen.getByTestId('whatsapp-mode-account-3')).toHaveTextContent(/customers get the ai assistant/i);
      expect(screen.queryByRole('radio')).not.toBeInTheDocument();
    });

    it('shows no setting while no store is chosen', async () => {
      renderTab(MANAGE, [accountsMock([account({ id: 'account-3', displayPhoneNumber: '27000000803' })])], {
        storefronts: [storefront('account-3', null)],
      });

      await waitFor(async () =>
        expect(await screen.findByTestId('whatsapp-store-account-3')).toHaveTextContent(/no store chosen/i)
      );
      expect(screen.queryByTestId('whatsapp-mode-account-3')).not.toBeInTheDocument();
    });

    it("lets an admin switch a number's customers to the assistant", async () => {
      const user = userEvent.setup();
      const setModeMock = composeMockedQueryResult(setWhatsAppStorefrontModeMutation, {
        variables: { input: { tenantId, accountId: 'account-2', mode: 'AGENTIC' } },
        data: {
          setWhatsAppStorefrontMode: {
            storefront: storefront('account-2', STORE, 'AGENTIC'),
            __typename: 'SetWhatsAppStorefrontMode',
          },
        },
      });
      renderTab(MANAGE, [
        accountsMock([account({ id: 'account-2', displayPhoneNumber: '27000000802' })]),
        storefrontsMock([storefront('account-2', STORE)]),
        setModeMock,
        accountsMock([account({ id: 'account-2', displayPhoneNumber: '27000000802' })]),
        storefrontsMock([storefront('account-2', STORE, 'AGENTIC')]),
      ]);

      const row = within(await screen.findByTestId('whatsapp-account-account-2'));
      const assistant = await row.findByRole('radio', { name: /ai assistant/i });
      await waitFor(() => expect(row.getByRole('radio', { name: /menus/i })).toBeChecked());
      await user.click(assistant);

      await waitFor(() => expect(setModeMock.result).toHaveBeenCalled());
      await waitFor(() => expect(row.getByRole('radio', { name: /ai assistant/i })).toBeChecked());
      // Step 2.8, finding 14: the admin sees it saved, not just a radio that moved.
      expect(await screen.findByTestId('toast-1')).toHaveTextContent(/customers now get the ai assistant/i);
    });

    // Step 2.8, finding 2: on a number serving both, a linked member's own setting decides their mode.
    it('says on a number serving both that members choose their own on their profile page', async () => {
      renderTab(MANAGE, [accountsMock([account({ id: 'account-2', displayPhoneNumber: '27000000802', purpose: BOTH })])], {
        storefronts: [storefront('account-2', STORE)],
      });

      await waitFor(async () =>
        expect(await screen.findByTestId('whatsapp-mode-account-2')).toHaveTextContent(
          /members who linked their phone choose their own on their profile page/i
        )
      );
    });

    it('says nothing about members on a number serving only customers', async () => {
      renderTab(MANAGE, [accountsMock([account({ id: 'account-2', displayPhoneNumber: '27000000802' })])], {
        storefronts: [storefront('account-2', STORE)],
      });

      await waitFor(async () => expect(await screen.findByTestId('whatsapp-mode-account-2')).toBeInTheDocument());
      expect(screen.getByTestId('whatsapp-mode-account-2')).not.toHaveTextContent(/members who linked/i);
    });
  });

  // WhatsApp plan phase 3, decision 5: the page stays, read-only, with one way back to a plan.
  describe("a plan that doesn't include WhatsApp", () => {
    const lapsedNumber = () => account({ id: 'account-2', displayPhoneNumber: '27000000802' });

    // Step 2.8, finding 16: setting up needs no plan, so a business can be ready before its trial
    // starts; only replies wait for a plan.
    it('keeps everything for setting up, and says replies wait for a plan', async () => {
      renderTab([...MANAGE, 'billing.manage'], [accountsMock([lapsedNumber()])], {
        storefronts: [storefront('account-2', STORE)],
        features: [],
      });

      const row = within(await screen.findByTestId('whatsapp-account-account-2'));
      const notice = await screen.findByTestId('plan-required');
      expect(notice).toHaveTextContent(/your plan doesn't include whatsapp/i);
      expect(notice).toHaveTextContent(/numbers don't reply/i);
      expect(await screen.findByTestId('whatsapp-connect-form')).toBeInTheDocument();
      expect(row.getByRole('button', { name: /disconnect/i })).toBeInTheDocument();
      expect(await row.findAllByRole('radio')).not.toHaveLength(0);
    });

    it('offers whoever manages billing a link to choose a plan', async () => {
      renderTab([...MANAGE, 'billing.manage'], [accountsMock([lapsedNumber()])], { features: [] });

      const link = await within(await screen.findByTestId('plan-required')).findByRole('link', {
        name: /choose a plan/i,
      });
      expect(link).toHaveAttribute('href', expect.stringMatching(/\/subscriptions$/));
    });

    it('asks anyone else to ask the owner', async () => {
      renderTab(VIEW_ONLY, [accountsMock([lapsedNumber()])], { features: [] });

      const notice = await screen.findByTestId('plan-required');
      expect(notice).toHaveTextContent(/ask the organization's owner to choose a plan/i);
      expect(within(notice).queryByRole('link')).not.toBeInTheDocument();
    });

    it('shows nothing about plans while WhatsApp is included', async () => {
      renderTab(MANAGE, [accountsMock([lapsedNumber()])]);

      await screen.findByTestId('whatsapp-account-account-2');
      expect(screen.queryByTestId('plan-required')).not.toBeInTheDocument();
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
      // WhatsApp plan Step 2.8, finding 17: the admin is told what's deleted before confirming.
      expect(await screen.findByText(/its conversations, with every message and customer, are deleted/i)).toBeInTheDocument();
      await user.click(await screen.findByRole('button', { name: /^disconnect number$/i }));

      await waitFor(() => expect(disconnectMock.result).toHaveBeenCalled());
      expect(await within(screen.getByTestId('whatsapp-account-account-1')).findByText(/^disconnected$/i)).toBeInTheDocument();
    });
  });

  // WhatsApp plan Step 2.9, decisions 1 to 5: an organization registers each of its own Meta apps once,
  // pastes the address and token we made into Meta, and picks the app when connecting a number.
  describe("an organization's own Meta apps", () => {
    const metaAppsCard = () => screen.findByTestId('whatsapp-meta-apps');

    it('shows each app with the callback URL and verify token to paste into Meta, never its secret', async () => {
      renderTab(MANAGE, [accountsMock([])], { metaApps: [metaApp()] });

      const app = within(await screen.findByTestId('whatsapp-meta-app-meta-app-1'));
      expect(app.getByText(new RegExp(META_APP_ID))).toBeInTheDocument();
      expect(app.getByLabelText(/^callback url$/i)).toHaveValue(metaApp().webhookUrl);
      expect(app.getByLabelText(/^verify token$/i)).toHaveValue('generated-verify-token-1');
      expect(app.getByRole('button', { name: /copy callback url/i })).toBeInTheDocument();
      expect(app.getByRole('button', { name: /copy verify token/i })).toBeInTheDocument();
    });

    it('offers a member no Meta apps card', async () => {
      renderTab(VIEW_ONLY, [accountsMock([account()])]);

      expect(await screen.findByTestId('whatsapp-account-account-1')).toBeInTheDocument();
      expect(screen.queryByTestId('whatsapp-meta-apps')).not.toBeInTheDocument();
    });

    it('registers an app, then shows its callback URL and verify token', async () => {
      const user = userEvent.setup();
      const registerMock = composeMockedQueryResult(registerWhatsAppMetaAppMutation, {
        variables: { input: { tenantId, appId: META_APP_ID, appSecret: 'the-app-secret' } },
        data: { registerWhatsAppMetaApp: { metaApp: metaApp(), __typename: 'RegisterWhatsAppMetaApp' } },
      });
      renderTab(MANAGE, [accountsMock([]), metaAppsMock([]), registerMock, metaAppsMock([metaApp()])]);

      const card = within(await metaAppsCard());
      await user.type(await card.findByLabelText(/^app id$/i), META_APP_ID);
      await user.type(card.getByLabelText(/^app secret$/i), 'the-app-secret');
      await user.click(card.getByRole('button', { name: /register app/i }));

      await waitFor(() => expect(registerMock.result).toHaveBeenCalled());
      const app = within(await screen.findByTestId('whatsapp-meta-app-meta-app-1'));
      expect(app.getByLabelText(/^verify token$/i)).toHaveValue('generated-verify-token-1');
      // The secret leaves the page as soon as it's saved.
      expect(card.getByLabelText(/^app secret$/i)).toHaveValue('');
    });

    it('shows why an app is refused, under its App ID', async () => {
      const user = userEvent.setup();
      const reason = 'This Meta app is already connected to another organization.';
      renderTab(MANAGE, [
        accountsMock([]),
        composeMockedQueryResult(registerWhatsAppMetaAppMutation, {
          variables: { input: { tenantId, appId: META_APP_ID, appSecret: 'the-app-secret' } },
          data: null,
          errors: [validationError('app_id', reason, 'already_connected')],
        }),
      ]);

      const card = within(await metaAppsCard());
      await user.type(await card.findByLabelText(/^app id$/i), META_APP_ID);
      await user.type(card.getByLabelText(/^app secret$/i), 'the-app-secret');
      await user.click(card.getByRole('button', { name: /register app/i }));

      expect(await card.findByText(reason)).toBeInTheDocument();
    });

    it("updates an app's secret, after it was reset in Meta", async () => {
      const user = userEvent.setup();
      const updateMock = composeMockedQueryResult(updateWhatsAppMetaAppSecretMutation, {
        variables: { input: { tenantId, metaAppId: 'meta-app-1', appSecret: 'a-new-secret' } },
        data: {
          updateWhatsAppMetaAppSecret: {
            metaApp: { id: 'meta-app-1', __typename: 'WhatsAppMetaAppType' },
            __typename: 'UpdateWhatsAppMetaAppSecret',
          },
        },
      });
      renderTab(MANAGE, [accountsMock([]), updateMock], { metaApps: [metaApp()] });

      const app = within(await screen.findByTestId('whatsapp-meta-app-meta-app-1'));
      await user.click(app.getByRole('button', { name: /update secret/i }));
      await user.type(await app.findByLabelText(/new app secret/i), 'a-new-secret');
      await user.click(app.getByRole('button', { name: /save secret/i }));

      await waitFor(() => expect(updateMock.result).toHaveBeenCalled());
      expect(await screen.findByTestId('toast-1')).toHaveTextContent(/app secret is updated/i);
    });

    it('regenerates the verify token after the admin confirms', async () => {
      const user = userEvent.setup();
      const regenerateMock = composeMockedQueryResult(regenerateWhatsAppMetaAppVerifyTokenMutation, {
        variables: { input: { tenantId, metaAppId: 'meta-app-1' } },
        data: {
          regenerateWhatsAppMetaAppVerifyToken: {
            metaApp: { id: 'meta-app-1', verifyToken: 'generated-verify-token-2', __typename: 'WhatsAppMetaAppType' },
            __typename: 'RegenerateWhatsAppMetaAppVerifyToken',
          },
        },
      });
      renderTab(MANAGE, [
        accountsMock([]),
        metaAppsMock([metaApp()]),
        regenerateMock,
        metaAppsMock([metaApp({ verifyToken: 'generated-verify-token-2' })]),
      ]);

      const app = within(await screen.findByTestId('whatsapp-meta-app-meta-app-1'));
      await user.click(app.getByRole('button', { name: /regenerate token/i }));
      // Messages keep arriving: Meta asks for the token only when its webhook settings are saved.
      expect(await screen.findByText(/messages keep arriving/i)).toBeInTheDocument();
      await user.click(await screen.findByRole('button', { name: /^regenerate verify token$/i }));

      await waitFor(() => expect(regenerateMock.result).toHaveBeenCalled());
      await waitFor(() =>
        expect(
          within(screen.getByTestId('whatsapp-meta-app-meta-app-1')).getByLabelText(/^verify token$/i)
        ).toHaveValue('generated-verify-token-2')
      );
    });

    it('says which numbers to disconnect before an app can be removed', async () => {
      const user = userEvent.setup();
      const reason = 'Disconnect its numbers first: 27000000801.';
      renderTab(
        MANAGE,
        [
          accountsMock([account({ metaAppId: 'meta-app-1' })]),
          composeMockedQueryResult(removeWhatsAppMetaAppMutation, {
            variables: { input: { tenantId, metaAppId: 'meta-app-1' } },
            data: null,
            errors: [validationError('non_field_errors', reason, 'app_in_use')],
          }),
        ],
        { metaApps: [metaApp()] }
      );

      const app = within(await screen.findByTestId('whatsapp-meta-app-meta-app-1'));
      await user.click(app.getByRole('button', { name: /^remove$/i }));
      await user.click(await screen.findByRole('button', { name: /^remove app$/i }));

      expect(await app.findByText(reason)).toBeInTheDocument();
    });

    it("connects a number in the organization's own app", async () => {
      const user = userEvent.setup();
      const connectMock = composeMockedQueryResult(connectWhatsAppAccountMutation, {
        variables: { input: { ...connectionInput(INTERNAL), metaAppId: 'meta-app-1' } },
        data: {
          connectWhatsAppAccount: {
            account: {
              id: 'account-9',
              purpose: INTERNAL,
              displayPhoneNumber: '27000000901',
              verifiedName: 'Demo Store',
              subscribedAt: '2026-11-01T09:00:00+00:00',
              __typename: 'WhatsAppAccountType',
            },
            __typename: 'ConnectWhatsAppAccount',
          },
        },
      });
      renderTab(MANAGE, [accountsMock([]), connectMock, accountsMock([account({ id: 'account-9' })])], {
        metaApps: [metaApp()],
      });

      await fillConnectForm(user, INTERNAL);
      const form = within(await connectForm());
      // This service's app is the default; the organization's own are offered by their App IDs.
      expect(form.getByLabelText(/^meta app$/i)).toHaveValue('');
      await user.selectOptions(form.getByLabelText(/^meta app$/i), 'meta-app-1');
      await user.click(await connectButton());

      await waitFor(() => expect(connectMock.result).toHaveBeenCalled());
    });

    it('offers no choice of app before one is registered', async () => {
      renderTab(MANAGE, [accountsMock([account()])]);

      const form = within(await connectForm());
      expect(await form.findByLabelText(/access token/i)).toBeInTheDocument();
      expect(form.queryByLabelText(/^meta app$/i)).not.toBeInTheDocument();
      expect(within(screen.getByTestId('whatsapp-account-account-1')).queryByLabelText(/^meta app$/i)).not.toBeInTheDocument();
    });

    it("moves a number to the organization's app, after a reminder to paste its callback URL and token into Meta", async () => {
      const user = userEvent.setup();
      const setMock = composeMockedQueryResult(setWhatsAppNumberMetaAppMutation, {
        variables: { input: { tenantId, accountId: 'account-1', metaAppId: 'meta-app-1' } },
        data: {
          setWhatsAppNumberMetaApp: {
            account: { id: 'account-1', metaAppId: 'meta-app-1', __typename: 'WhatsAppAccountType' },
            __typename: 'SetWhatsAppNumberMetaApp',
          },
        },
      });
      renderTab(MANAGE, [accountsMock([account()]), setMock, accountsMock([account({ metaAppId: 'meta-app-1' })])], {
        metaApps: [metaApp()],
      });

      const row = within(await screen.findByTestId('whatsapp-account-account-1'));
      await user.selectOptions(await row.findByLabelText(/^meta app$/i), 'meta-app-1');
      await user.click(row.getByRole('button', { name: /^change app$/i }));
      expect(await screen.findByText(/paste the app's callback url and verify token/i)).toBeInTheDocument();
      await user.click(await screen.findByRole('button', { name: /^move number$/i }));

      await waitFor(() => expect(setMock.result).toHaveBeenCalled());
      expect(await screen.findByTestId('toast-1')).toHaveTextContent(new RegExp(`27000000801 is now in app ${META_APP_ID}`, 'i'));
    });

    it("offers a member no change of a number's app", async () => {
      renderTab(VIEW_ONLY, [accountsMock([account({ metaAppId: 'meta-app-1' })])]);

      const row = within(await screen.findByTestId('whatsapp-account-account-1'));
      expect(await row.findByTestId('whatsapp-purpose-account-1')).toBeInTheDocument();
      expect(row.queryByLabelText(/^meta app$/i)).not.toBeInTheDocument();
    });
  });
});
