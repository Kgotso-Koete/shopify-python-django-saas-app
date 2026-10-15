import type { MockedResponse } from '@apollo/client/testing';
import { TenantType as TenantTypeField } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/src/tests/factories/tenant';
import { createMockRouterProps, render } from '@sb/webapp-tenants/src/tests/utils/rendering';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import { RoutesConfig } from '../../../config/routes';
import { shopifyProductsQuery, shopifyShopsQuery } from '../../../graphql/shopify.graphql';
import { ShopifyProducts } from '../shopifyProducts.component';

const tenantId = 'tenant-shopify-products-1';
const STORE = 'demo.myshopify.com';
const PAGE_SIZE = 12;

const userMock = () =>
  fillCommonQueryWithUser(
    currentUserFactory({
      tenants: [tenantFactory({ id: tenantId, name: 'Test Org', type: TenantTypeField.ORGANIZATION })],
    })
  );

const shop = (shopDomain: string) => ({
  shopDomain,
  scopes: ['read_products'],
  installedAt: '2026-10-07T00:00:00+00:00',
  uninstalledAt: null,
  needsReinstall: false,
  __typename: 'ShopifyShopType',
});

const shopsMock = (domains: string[]) =>
  composeMockedQueryResult(shopifyShopsQuery, {
    variables: { tenantId },
    data: { shopifyShops: domains.map(shop) },
  });

const product = (n: number) => ({
  id: `gid://shopify/Product/${n}`,
  title: `Product ${n}`,
  handle: `product-${n}`,
  status: 'ACTIVE',
  imageUrl: `https://cdn.shopify.com/product-${n}.jpg`,
  imageAlt: `Photo of product ${n}`,
  priceMin: '19.99',
  priceMax: '24.50',
  currencyCode: 'ZAR',
  __typename: 'ShopifyProductType',
});

type PageOptions = {
  shopDomain?: string;
  // The page size the page asks for: 12 unless the "products per page" picker says otherwise.
  first?: number;
  after?: string;
  before?: string;
  products?: ReturnType<typeof product>[];
  hasNextPage?: boolean;
  hasPreviousPage?: boolean;
};

// The variables must match the page's request exactly: Apollo's mock answers only an identical request.
const pageVariables = ({ shopDomain = STORE, first = PAGE_SIZE, after, before }: PageOptions) => ({
  tenantId,
  shopDomain,
  first,
  ...(after ? { after } : {}),
  ...(before ? { before } : {}),
});

const productsMock = (options: PageOptions = {}) => {
  const { products = [product(1)], hasNextPage = false, hasPreviousPage = false } = options;
  return composeMockedQueryResult(shopifyProductsQuery, {
    variables: pageVariables(options),
    data: {
      shopifyProducts: {
        products,
        pageInfo: {
          hasNextPage,
          hasPreviousPage,
          startCursor: 'cursor-start',
          endCursor: 'cursor-end',
          __typename: 'ShopifyProductsPageInfoType',
        },
        __typename: 'ShopifyProductsType',
      },
    },
  });
};

// A store problem as the backend sends it (apps/shopify/schema.py): GraphQlValidationError with
// { non_field_errors: [{ message, code }] } in extensions.
const problemMock = (code: string, message: string) =>
  composeMockedQueryResult(shopifyProductsQuery, {
    variables: pageVariables({}),
    data: null,
    errors: [
      new GraphQLError('GraphQlValidationError', {
        extensions: { non_field_errors: [{ message, code }] },
      }),
    ],
  });

const productsPath = (search = '') =>
  `${createMockRouterProps(RoutesConfig.shopify.products, { tenantId }).initialEntries?.[0]}${search}`;

const renderPage = (mocks: MockedResponse[], search = '') =>
  render(<ShopifyProducts />, {
    apolloMocks: [userMock(), ...mocks],
    routerProps: { initialEntries: [productsPath(search)] },
  });

describe('ShopifyProducts: Component', () => {
  it("shows a page of the store's products with image, title, price and status", async () => {
    renderPage([shopsMock([STORE]), productsMock({ products: [product(1), product(2)] })]);

    const card = await screen.findByTestId('shopify-product-gid://shopify/Product/1');
    expect(within(card).getByText('Product 1')).toBeInTheDocument();
    expect(within(card).getByRole('img', { name: 'Photo of product 1' })).toHaveAttribute(
      'src',
      'https://cdn.shopify.com/product-1.jpg'
    );
    // Prices are shown as Shopify sent them, never rounded.
    expect(within(card).getByText('ZAR 19.99 – 24.50')).toBeInTheDocument();
    expect(within(card).getByText(/^active$/i)).toBeInTheDocument();
    expect(screen.getByTestId('shopify-product-gid://shopify/Product/2')).toBeInTheDocument();
  });

  it('shows one price when the lowest and highest are the same', async () => {
    renderPage([shopsMock([STORE]), productsMock({ products: [{ ...product(1), priceMax: '19.99' }] })]);

    const card = await screen.findByTestId('shopify-product-gid://shopify/Product/1');
    expect(within(card).getByText('ZAR 19.99')).toBeInTheDocument();
  });

  it('disables Previous on the first page and Next on the last', async () => {
    renderPage([shopsMock([STORE]), productsMock({ hasNextPage: false, hasPreviousPage: false })]);

    await screen.findByTestId('shopify-product-gid://shopify/Product/1');
    expect(screen.getByTestId('shopify-products-previous')).toBeDisabled();
    expect(screen.getByTestId('shopify-products-next')).toBeDisabled();
  });

  it('Next asks for the page after the last product shown', async () => {
    renderPage([
      shopsMock([STORE]),
      productsMock({ products: [product(1)], hasNextPage: true }),
      productsMock({ after: 'cursor-end', products: [product(13)], hasPreviousPage: true }),
    ]);

    await screen.findByTestId('shopify-product-gid://shopify/Product/1');
    await userEvent.click(screen.getByTestId('shopify-products-next'));

    expect(await screen.findByTestId('shopify-product-gid://shopify/Product/13')).toBeInTheDocument();
    expect(screen.getByTestId('shopify-products-previous')).toBeEnabled();
  });

  it('Previous asks for the page before the first product shown', async () => {
    renderPage(
      [
        shopsMock([STORE]),
        productsMock({ after: 'cursor-end', products: [product(13)], hasPreviousPage: true }),
        productsMock({ before: 'cursor-start', products: [product(1)], hasNextPage: true }),
      ],
      `?shop=${STORE}&after=cursor-end`
    );

    await screen.findByTestId('shopify-product-gid://shopify/Product/13');
    await userEvent.click(screen.getByTestId('shopify-products-previous'));

    expect(await screen.findByTestId('shopify-product-gid://shopify/Product/1')).toBeInTheDocument();
  });

  it('opens on the page in the URL, so a refresh stays on the same page', async () => {
    renderPage(
      [shopsMock([STORE]), productsMock({ after: 'cursor-end', products: [product(13)], hasPreviousPage: true })],
      `?shop=${STORE}&after=cursor-end`
    );

    expect(await screen.findByTestId('shopify-product-gid://shopify/Product/13')).toBeInTheDocument();
  });

  it('says the store has no products', async () => {
    renderPage([shopsMock([STORE]), productsMock({ products: [] })]);

    expect(await screen.findByTestId('shopify-products-empty')).toHaveTextContent(/this store has no products/i);
  });

  it('says no stores are connected and links to the Shopify page', async () => {
    renderPage([shopsMock([])]);

    const message = await screen.findByTestId('shopify-products-no-stores');
    expect(message).toHaveTextContent(/no shopify stores are connected/i);
    expect(within(message).getByRole('link')).toHaveAttribute('href', `/en/${tenantId}/shopify`);
  });

  it('asks to reconnect the store and links to the Shopify page', async () => {
    renderPage([shopsMock([STORE]), problemMock('reconnect_required', 'This store needs to be reconnected.')]);

    const message = await screen.findByTestId('shopify-products-reconnect');
    expect(message).toHaveTextContent(/needs to be reconnected/i);
    expect(within(message).getByRole('link')).toHaveAttribute('href', `/en/${tenantId}/shopify`);
  });

  it('asks to try again shortly when Shopify is busy', async () => {
    renderPage([shopsMock([STORE]), problemMock('try_again_later', 'Shopify is busy right now.')]);

    expect(await screen.findByTestId('shopify-products-try-again')).toHaveTextContent(/try again/i);
  });

  it('hides the store picker when the organization has one store', async () => {
    renderPage([shopsMock([STORE]), productsMock()]);

    await screen.findByTestId('shopify-product-gid://shopify/Product/1');
    expect(screen.queryByTestId('shopify-products-store-picker')).not.toBeInTheDocument();
  });

  it('switches to another store with the store picker, starting at its first page', async () => {
    const other = 'other.myshopify.com';
    renderPage([
      shopsMock([STORE, other]),
      productsMock({ products: [product(1)] }),
      productsMock({ shopDomain: other, products: [product(99)] }),
    ]);

    await screen.findByTestId('shopify-product-gid://shopify/Product/1');
    await userEvent.selectOptions(screen.getByTestId('shopify-products-store-picker'), other);

    expect(await screen.findByTestId('shopify-product-gid://shopify/Product/99')).toBeInTheDocument();
  });

  describe('products per page', () => {
    // The choices stay under the backend's cap of 50 per request (apps/shopify/products.py).
    it('shows 12 per page by default, and offers 12, 24 and 48', async () => {
      renderPage([shopsMock([STORE]), productsMock()]);

      await screen.findByTestId('shopify-product-gid://shopify/Product/1');
      const picker = screen.getByTestId('shopify-products-per-page');
      expect(picker).toHaveValue('12');
      expect(within(picker).getAllByRole('option').map((option) => option.textContent)).toEqual([
        '12',
        '24',
        '48',
      ]);
    });

    it('asks Shopify for the chosen number of products', async () => {
      renderPage([
        shopsMock([STORE]),
        productsMock({ products: [product(1)] }),
        productsMock({ first: 24, products: [product(1), product(24)] }),
      ]);

      await screen.findByTestId('shopify-product-gid://shopify/Product/1');
      await userEvent.selectOptions(screen.getByTestId('shopify-products-per-page'), '24');

      // Product 24 is only in the 24-per-page answer, so seeing it proves first: 24 was asked for.
      expect(await screen.findByTestId('shopify-product-gid://shopify/Product/24')).toBeInTheDocument();
    });

    it('opens with the number in the URL, so a refresh keeps the choice', async () => {
      renderPage(
        [shopsMock([STORE]), productsMock({ first: 48, products: [product(48)] })],
        `?shop=${STORE}&perPage=48`
      );

      expect(await screen.findByTestId('shopify-product-gid://shopify/Product/48')).toBeInTheDocument();
      expect(screen.getByTestId('shopify-products-per-page')).toHaveValue('48');
    });

    it('falls back to 12 when the URL has a number it does not offer', async () => {
      renderPage([shopsMock([STORE]), productsMock({ products: [product(1)] })], `?shop=${STORE}&perPage=500`);

      expect(await screen.findByTestId('shopify-product-gid://shopify/Product/1')).toBeInTheDocument();
      expect(screen.getByTestId('shopify-products-per-page')).toHaveValue('12');
    });

    it('goes back to the first page when the number changes, keeping the store', async () => {
      // A cursor from a 12-per-page view doesn't line up with 24 per page, so it's dropped.
      renderPage(
        [
          shopsMock([STORE]),
          productsMock({ after: 'cursor-end', products: [product(13)], hasPreviousPage: true }),
          productsMock({ first: 24, products: [product(1)] }),
        ],
        `?shop=${STORE}&after=cursor-end`
      );

      await screen.findByTestId('shopify-product-gid://shopify/Product/13');
      await userEvent.selectOptions(screen.getByTestId('shopify-products-per-page'), '24');

      expect(await screen.findByTestId('shopify-product-gid://shopify/Product/1')).toBeInTheDocument();
      expect(screen.getByTestId('shopify-products-previous')).toBeDisabled();
    });
  });
});
