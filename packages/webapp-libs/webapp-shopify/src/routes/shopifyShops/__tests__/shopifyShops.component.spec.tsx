import type { MockedResponse } from '@apollo/client/testing';
import { TenantType as TenantTypeField } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { organizationFeaturesQuery } from '@sb/webapp-tenants/hooks';
import { tenantFactory } from '@sb/webapp-tenants/src/tests/factories/tenant';
import { createMockRouterProps, render } from '@sb/webapp-tenants/src/tests/utils/rendering';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import { RoutesConfig } from '../../../config/routes';
import {
  shopifyConfigQuery,
  shopifyDisconnectShopMutation,
  shopifyShopsQuery,
  shopifyStartInstallMutation,
} from '../../../graphql/shopify.graphql';
import { ShopifyShops } from '../shopifyShops.component';

const tenantId = 'tenant-shopify-test-1';

type ShopOverrides = { shopDomain: string; uninstalledAt?: string | null; needsReinstall?: boolean };
const shop = ({ shopDomain, uninstalledAt = null, needsReinstall = false }: ShopOverrides) => ({
  shopDomain,
  scopes: ['read_products'],
  installedAt: '2026-10-07T00:00:00+00:00',
  uninstalledAt,
  needsReinstall,
  __typename: 'ShopifyShopType',
});

const userMock = () =>
  fillCommonQueryWithUser(
    currentUserFactory({
      tenants: [tenantFactory({ id: tenantId, name: 'Test Org', type: TenantTypeField.ORGANIZATION })],
    })
  );

const configMock = (enabled = true) =>
  composeMockedQueryResult(shopifyConfigQuery, {
    data: { shopifyConfig: { enabled, __typename: 'ShopifyConfigType' } },
  });

const shopsMock = (shops: ReturnType<typeof shop>[]) =>
  composeMockedQueryResult(shopifyShopsQuery, {
    variables: { tenantId },
    data: { shopifyShops: shops },
  });

// What the organization's plan unlocks (WhatsApp plan phase 3, decision 8): Shopify, unless a test says not.
const featuresMock = (features: string[]) => ({
  ...composeMockedQueryResult(organizationFeaturesQuery, {
    variables: { tenantId },
    data: { organizationFeatures: features },
  }),
  maxUsageCount: Number.POSITIVE_INFINITY,
});

const renderPage = (mocks: MockedResponse[], features = ['SHOPIFY', 'WHATSAPP']) =>
  render(<ShopifyShops />, {
    apolloMocks: [userMock(), featuresMock(features), ...mocks],
    routerProps: createMockRouterProps(RoutesConfig.shopify.list, { tenantId }),
  });

describe('ShopifyShops: Component', () => {
  // WhatsApp plan Step 2.8, finding 16: connecting a store needs no plan, so a business can be ready
  // before its trial starts; browsing its products waits for a plan.
  it("keeps the stores and the connect form while the plan doesn't include Shopify", async () => {
    renderPage([configMock(), shopsMock([shop({ shopDomain: 'kept.myshopify.com' })])], []);

    const notice = await screen.findByTestId('plan-required');
    expect(notice).toHaveTextContent(/your plan doesn't include shopify/i);
    expect(notice).toHaveTextContent(/products show/i);
    expect(await screen.findByTestId('shopify-shop-kept.myshopify.com')).toBeInTheDocument();
    expect(screen.getByTestId('shopify-domain-input')).toBeInTheDocument();
  });

  it('says the integration is not configured when Shopify is disabled', async () => {
    renderPage([configMock(false)]);

    expect(await screen.findByText(/shopify integration is not configured/i)).toBeInTheDocument();
    expect(screen.queryByTestId('shopify-domain-input')).not.toBeInTheDocument();
  });

  it('shows the empty state and the connect form when no stores are connected', async () => {
    renderPage([configMock(), shopsMock([])]);

    expect(await screen.findByText(/no stores connected/i)).toBeInTheDocument();
    expect(screen.getByTestId('shopify-domain-input')).toBeInTheDocument();
  });

  it('marks each store as active, uninstalled or needing a reinstall', async () => {
    renderPage([
      configMock(),
      shopsMock([
        shop({ shopDomain: 'active.myshopify.com' }),
        shop({ shopDomain: 'gone.myshopify.com', uninstalledAt: '2026-10-08T00:00:00+00:00' }),
        shop({ shopDomain: 'stale.myshopify.com', needsReinstall: true }),
      ]),
    ]);

    // Exact badge labels: the domains themselves contain words like "active", so matching the row's
    // whole text would pass even with the wrong badge.
    expect(within(await screen.findByTestId('shopify-shop-active.myshopify.com')).getByText(/^active$/i)).toBeInTheDocument();
    expect(within(screen.getByTestId('shopify-shop-gone.myshopify.com')).getByText(/^uninstalled$/i)).toBeInTheDocument();
    expect(within(screen.getByTestId('shopify-shop-stale.myshopify.com')).getByText(/^needs reinstall$/i)).toBeInTheDocument();
  });

  it('says the stores could not be loaded when the list fails, instead of "no stores connected"', async () => {
    const failingShopsMock = composeMockedQueryResult(shopifyShopsQuery, {
      variables: { tenantId },
      data: null,
      errors: [new GraphQLError('Something went wrong')],
    });
    renderPage([configMock(), failingShopsMock]);

    expect(await screen.findByTestId('shopify-shops-error')).toHaveTextContent(/couldn't load your shopify stores/i);
    expect(screen.queryByText(/no stores connected/i)).not.toBeInTheDocument();
  });

  describe('connect a store', () => {
    const originalLocation = window.location;

    beforeEach(() => {
      // jsdom can't navigate; a plain object lets the test read where the page sent the browser.
      Object.defineProperty(window, 'location', { value: { href: '' }, writable: true, configurable: true });
    });

    afterEach(() => {
      Object.defineProperty(window, 'location', { value: originalLocation, writable: true, configurable: true });
    });

    it("sends the browser to Shopify's approval page for a valid domain", async () => {
      const authorizeUrl = 'https://my-store.myshopify.com/admin/oauth/authorize?client_id=abc';
      const installMock = composeMockedQueryResult(shopifyStartInstallMutation, {
        variables: { input: { tenantId, shopDomain: 'my-store.myshopify.com' } },
        data: { shopifyStartInstall: { authorizeUrl, __typename: 'ShopifyStartInstall' } },
      });
      renderPage([configMock(), shopsMock([]), installMock]);

      await userEvent.type(await screen.findByTestId('shopify-domain-input'), 'my-store.myshopify.com');
      await userEvent.click(screen.getByTestId('shopify-connect-button'));

      await waitFor(() => expect(window.location.href).toBe(authorizeUrl));
    });

    it('rejects an invalid domain without calling the backend', async () => {
      const installMock = composeMockedQueryResult(shopifyStartInstallMutation, {
        variables: { input: { tenantId, shopDomain: 'not-a-shop.example' } },
        data: { shopifyStartInstall: { authorizeUrl: 'https://unused', __typename: 'ShopifyStartInstall' } },
      });
      renderPage([configMock(), shopsMock([]), installMock]);

      await userEvent.type(await screen.findByTestId('shopify-domain-input'), 'not-a-shop.example');
      await userEvent.click(screen.getByTestId('shopify-connect-button'));

      expect(await screen.findByTestId('shopify-domain-error')).toHaveTextContent(/enter a valid shopify domain/i);
      expect(installMock.result).not.toHaveBeenCalled();
      expect(window.location.href).toBe('');
    });
  });

  it('disconnects a store after confirmation and reloads the list without it', async () => {
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
    const disconnectMock = composeMockedQueryResult(shopifyDisconnectShopMutation, {
      variables: { input: { tenantId, shopDomain: 'active.myshopify.com' } },
      data: { shopifyDisconnectShop: { ok: true, __typename: 'ShopifyDisconnectShop' } },
    });
    renderPage([
      configMock(),
      shopsMock([shop({ shopDomain: 'active.myshopify.com' })]),
      disconnectMock,
      // The page refetches the list after disconnecting.
      shopsMock([]),
    ]);

    await userEvent.click(await screen.findByTestId('shopify-disconnect-active.myshopify.com'));

    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(disconnectMock.result).toHaveBeenCalled());
    expect(await screen.findByText(/no stores connected/i)).toBeInTheDocument();
    expect(screen.queryByTestId('shopify-shop-active.myshopify.com')).not.toBeInTheDocument();

    confirmSpy.mockRestore();
  });
});
