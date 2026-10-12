import type { MockedResponse } from '@apollo/client/testing';
import { TenantType as TenantTypeField } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/src/tests/factories/tenant';
import { render } from '@sb/webapp-tenants/src/tests/utils/rendering';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import { shopifyClaimQuery, shopifyLinkShopMutation } from '../../../graphql/shopify.graphql';
import { ShopifyLink } from '../shopifyLink.component';

const tenantId = 'tenant-shopify-link-1';
const claim = 'signed-claim-123';
const shopDomain = 'linkme.myshopify.com';

const userMock = () =>
  fillCommonQueryWithUser(
    currentUserFactory({
      tenants: [tenantFactory({ id: tenantId, name: 'Test Org', type: TenantTypeField.ORGANIZATION })],
    })
  );

const claimMock = () =>
  composeMockedQueryResult(shopifyClaimQuery, {
    variables: { claim },
    data: { shopifyClaim: { shopDomain, __typename: 'ShopifyClaimType' } },
  });

const linkMock = () =>
  composeMockedQueryResult(shopifyLinkShopMutation, {
    variables: { input: { tenantId, claim } },
    data: {
      shopifyLinkShop: {
        shop: {
          shopDomain,
          scopes: ['read_products'],
          installedAt: '2026-10-11T00:00:00+00:00',
          __typename: 'ShopifyShopType',
        },
        __typename: 'ShopifyLinkShop',
      },
    },
  });

const failingLinkMock = (message: string) =>
  composeMockedQueryResult(shopifyLinkShopMutation, {
    variables: { input: { tenantId, claim } },
    data: null,
    errors: [new GraphQLError(message)],
  });

// The link page lives outside the tenant prefix: /en/shopify/link?claim=…
const renderPage = (mocks: MockedResponse[], search = `?claim=${claim}`) =>
  render(<ShopifyLink />, {
    apolloMocks: [userMock(), ...mocks],
    routerProps: { initialEntries: [`/en/shopify/link${search}`] },
  });

describe('ShopifyLink: Component', () => {
  it('asks for a link from Shopify when the URL has no claim', async () => {
    renderPage([], '');

    expect(await screen.findByText(/no link provided/i)).toBeInTheDocument();
  });

  it('says the link has expired when the claim is invalid or expired', async () => {
    const expiredMock = composeMockedQueryResult(shopifyClaimQuery, {
      variables: { claim },
      data: null,
      errors: [new GraphQLError('Invalid or expired claim')],
    });
    renderPage([expiredMock]);

    expect(await screen.findByTestId('shopify-link-expired')).toHaveTextContent(/this link has expired/i);
  });

  it('links the store to the current organization and confirms it', async () => {
    const mock = linkMock();
    renderPage([claimMock(), mock]);

    expect(await screen.findByText(shopDomain)).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('shopify-link-confirm'));

    await waitFor(() => expect(mock.result).toHaveBeenCalled());
    expect(await screen.findByTestId('shopify-link-success')).toHaveTextContent(/store connected/i);
  });

  it("shows the server's message when the store is already connected", async () => {
    const message = 'This store is already connected to an organization.';
    renderPage([claimMock(), failingLinkMock(message)]);

    await userEvent.click(await screen.findByTestId('shopify-link-confirm'));

    expect(await screen.findByTestId('shopify-link-error')).toHaveTextContent(message);
  });

  // Decision B (Shopify plan, section 4.2): say which organization the store will be linked to.
  it('names the organization the store will be linked to', async () => {
    renderPage([claimMock()]);

    expect(await screen.findByTestId('shopify-link-target-organization')).toHaveTextContent('Test Org');
  });

  // Decision D (Shopify plan, section 4.2): never show the raw "permission_denied" code.
  it('explains a missing permission in plain words instead of the raw error code', async () => {
    renderPage([claimMock(), failingLinkMock('permission_denied')]);

    await userEvent.click(await screen.findByTestId('shopify-link-confirm'));

    const error = await screen.findByTestId('shopify-link-error');
    expect(error).toHaveTextContent(/you need permission to manage shopify stores in this organization/i);
    expect(error).not.toHaveTextContent('permission_denied');
  });
});
