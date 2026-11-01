import { useQuery } from '@apollo/client/react';
import { extractGraphQLErrors } from '@sb/webapp-api-client/api';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent } from '@sb/webapp-core/components/ui/card';
import { PlanRequiredNotice } from '@sb/webapp-tenants/components/planRequiredNotice';
import { useGenerateTenantPath, useOrganizationFeatures } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { AlertTriangle, ChevronLeft, ChevronRight, Clock, Package, Store } from 'lucide-react';
import { FC, ReactNode } from 'react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { Link, useSearchParams } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { shopifyProductsQuery, shopifyShopsQuery } from '../../graphql/shopify.graphql';

// The "products per page" choices. They stay under the backend's cap of 50 per request
// (apps/shopify/products.py); the first one is the default.
export const PAGE_SIZES = [12, 24, 48] as const;
export const PAGE_SIZE = PAGE_SIZES[0];

/** The page size in the URL, if it's one we offer; otherwise the default. */
const pageSizeFrom = (value: string | null): number => {
  const requested = Number(value);
  return (PAGE_SIZES as readonly number[]).includes(requested) ? requested : PAGE_SIZE;
};

/**
 * The code of a store problem from shopifyProducts. The backend raises
 * GraphQlValidationError({"non_field_errors": [message]}, code=…) (apps/shopify/schema.py), so the code is
 * in the first error's `extensions.non_field_errors`: store_not_found, reconnect_required or try_again_later.
 */
const problemCode = (error: unknown): string | undefined => {
  for (const graphQLError of extractGraphQLErrors(error) ?? []) {
    const reasons = (graphQLError.extensions?.['non_field_errors'] ?? []) as Array<{ code?: string }>;
    if (reasons[0]?.code) return reasons[0].code;
  }
  return undefined;
};

// Prices stay the strings Shopify sent, so nothing is rounded on the way.
const formatPrice = (min: string, max: string, currencyCode: string) =>
  min === max ? `${currencyCode} ${min}` : `${currencyCode} ${min} – ${max}`;

const StatusLabel: FC<{ status: string }> = ({ status }) => {
  switch (status) {
    case 'ACTIVE':
      return <FormattedMessage id="ShopifyProducts / Status active" defaultMessage="Active" />;
    case 'DRAFT':
      return <FormattedMessage id="ShopifyProducts / Status draft" defaultMessage="Draft" />;
    case 'ARCHIVED':
      return <FormattedMessage id="ShopifyProducts / Status archived" defaultMessage="Archived" />;
    case 'UNLISTED':
      return <FormattedMessage id="ShopifyProducts / Status unlisted" defaultMessage="Unlisted" />;
    default:
      return <>{status}</>;
  }
};

const MessageCard: FC<{ testId: string; icon: ReactNode; title: ReactNode; children?: ReactNode }> = ({
  testId,
  icon,
  title,
  children,
}) => (
  <Card>
    <CardContent className="py-16">
      <div className="flex flex-col items-center justify-center text-center" data-testid={testId}>
        {icon}
        <h3 className="mb-2 text-lg font-semibold">{title}</h3>
        {children && <div className="text-sm text-muted-foreground">{children}</div>}
      </div>
    </CardContent>
  </Card>
);

export const ShopifyProducts: FC = () => {
  const intl = useIntl();
  const generateTenantPath = useGenerateTenantPath();
  const { data: currentTenant } = useCurrentTenant();
  // The store and the cursor live in the URL, so a refresh or the back button keeps the page.
  const [searchParams, setSearchParams] = useSearchParams();

  const { isUnlocked } = useOrganizationFeatures();
  const shopifyUnlocked = isUnlocked('SHOPIFY');
  const { data: shopsData, loading: shopsLoading } = useQuery(shopifyShopsQuery, {
    variables: { tenantId: currentTenant?.id ?? '' },
    skip: !currentTenant,
  });
  const shops = shopsData?.shopifyShops ?? [];
  const requestedShop = searchParams.get('shop');
  const shopDomain = shops.find((shop) => shop.shopDomain === requestedShop)?.shopDomain ?? shops[0]?.shopDomain;
  const after = searchParams.get('after');
  const before = searchParams.get('before');
  const perPage = pageSizeFrom(searchParams.get('perPage'));

  const { data, loading, error } = useQuery(shopifyProductsQuery, {
    variables: {
      tenantId: currentTenant?.id ?? '',
      shopDomain: shopDomain ?? '',
      first: perPage,
      ...(after ? { after } : {}),
      ...(before ? { before } : {}),
    },
    // Browsing calls Shopify, so it waits for a plan that includes it (WhatsApp plan phase 3, decision 5).
    skip: !currentTenant || !shopDomain || !shopifyUnlocked,
  });

  const shopifyPagePath = generateTenantPath(RoutesConfig.shopify.list);
  // Passed into translated messages as a value, so React needs a key for it.
  const shopifyPageLink = (
    <Link key="shopify-page-link" to={shopifyPagePath} className="font-medium text-primary underline">
      <FormattedMessage id="ShopifyProducts / Open Shopify page" defaultMessage="Open the Shopify page" />
    </Link>
  );

  const products = data?.shopifyProducts.products ?? [];
  const pageInfo = data?.shopifyProducts.pageInfo;

  const renderContent = () => {
    if (!shopifyUnlocked) {
      return (
        <PlanRequiredNotice feature="Shopify">
          <FormattedMessage
            id="ShopifyProducts / Plan required"
            defaultMessage="Your stores are kept, and their products show here again on a plan that includes Shopify. Shopify comes with the paid plans, free trial included."
          />
        </PlanRequiredNotice>
      );
    }

    if (shopsLoading || (loading && !data)) {
      return (
        <div className="animate-pulse space-y-4">
          <div className="h-64 rounded bg-muted" />
        </div>
      );
    }

    if (shops.length === 0) {
      return (
        <MessageCard
          testId="shopify-products-no-stores"
          icon={<Store className="mb-4 h-12 w-12 text-muted-foreground" />}
          title={
            <FormattedMessage
              id="ShopifyProducts / No stores title"
              defaultMessage="No Shopify stores are connected"
            />
          }
        >
          <FormattedMessage
            id="ShopifyProducts / No stores description"
            defaultMessage="Connect a store first. {link}"
            values={{ link: shopifyPageLink }}
          />
        </MessageCard>
      );
    }

    if (error) {
      const code = problemCode(error);
      if (code === 'reconnect_required') {
        return (
          <MessageCard
            testId="shopify-products-reconnect"
            icon={<AlertTriangle className="mb-4 h-12 w-12 text-amber-500" />}
            title={
              <FormattedMessage
                id="ShopifyProducts / Reconnect title"
                defaultMessage="This store needs to be reconnected"
              />
            }
          >
            <FormattedMessage
              id="ShopifyProducts / Reconnect description"
              defaultMessage="Its connection to Shopify no longer works. {link} and connect it again."
              values={{ link: shopifyPageLink }}
            />
          </MessageCard>
        );
      }
      if (code === 'try_again_later') {
        return (
          <MessageCard
            testId="shopify-products-try-again"
            icon={<Clock className="mb-4 h-12 w-12 text-muted-foreground" />}
            title={<FormattedMessage id="ShopifyProducts / Busy title" defaultMessage="Shopify is busy right now" />}
          >
            <FormattedMessage
              id="ShopifyProducts / Busy description"
              defaultMessage="Please try again in a few seconds."
            />
          </MessageCard>
        );
      }
      return (
        <MessageCard
          testId="shopify-products-error"
          icon={<AlertTriangle className="mb-4 h-12 w-12 text-amber-500" />}
          title={
            <FormattedMessage id="ShopifyProducts / Load error title" defaultMessage="Couldn't load the products" />
          }
        >
          <FormattedMessage id="ShopifyProducts / Load error description" defaultMessage="Please refresh the page." />
        </MessageCard>
      );
    }

    if (products.length === 0) {
      return (
        <MessageCard
          testId="shopify-products-empty"
          icon={<Package className="mb-4 h-12 w-12 text-muted-foreground" />}
          title={<FormattedMessage id="ShopifyProducts / Empty title" defaultMessage="This store has no products" />}
        />
      );
    }

    return (
      <>
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="shopify-products-grid">
          {products.map((product) => (
            <li key={product.id} data-testid={`shopify-product-${product.id}`}>
              <Card className="h-full overflow-hidden">
                {product.imageUrl ? (
                  <img
                    src={product.imageUrl}
                    alt={product.imageAlt ?? product.title}
                    className="aspect-square w-full object-cover"
                  />
                ) : (
                  <div className="flex aspect-square w-full items-center justify-center bg-muted">
                    <Package className="h-12 w-12 text-muted-foreground" />
                  </div>
                )}
                <CardContent className="space-y-1 p-4">
                  <p className="font-medium">{product.title}</p>
                  <p className="text-sm">{formatPrice(product.priceMin, product.priceMax, product.currencyCode)}</p>
                  <p className="text-xs text-muted-foreground">
                    <StatusLabel status={product.status} />
                  </p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>

        <div className="flex items-center justify-between">
          <button
            type="button"
            disabled={!pageInfo?.hasPreviousPage || !pageInfo.startCursor}
            onClick={() =>
              shopDomain &&
              setSearchParams({ shop: shopDomain, perPage: String(perPage), before: pageInfo?.startCursor ?? '' })
            }
            className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm font-medium disabled:opacity-50"
            data-testid="shopify-products-previous"
          >
            <ChevronLeft className="h-4 w-4" />
            <FormattedMessage id="ShopifyProducts / Previous" defaultMessage="Previous" />
          </button>
          <button
            type="button"
            disabled={!pageInfo?.hasNextPage || !pageInfo.endCursor}
            onClick={() =>
              shopDomain &&
              setSearchParams({ shop: shopDomain, perPage: String(perPage), after: pageInfo?.endCursor ?? '' })
            }
            className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-2 text-sm font-medium disabled:opacity-50"
            data-testid="shopify-products-next"
          >
            <FormattedMessage id="ShopifyProducts / Next" defaultMessage="Next" />
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </>
    );
  };

  return (
    <PageLayout>
      <Helmet title={intl.formatMessage({ defaultMessage: 'Shopify products', id: 'ShopifyProducts / page title' })} />

      <div className="mx-auto w-full max-w-5xl space-y-8">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Package className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage id="ShopifyProducts / Title" defaultMessage="Shopify products" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage
              id="ShopifyProducts / Subheader"
              defaultMessage="The products in your connected Shopify store, read live from Shopify"
            />
          </Paragraph>
        </div>

        {shops.length > 0 && (
          <div className="flex flex-wrap items-center gap-6">
            {shops.length > 1 && (
              <label className="flex items-center gap-3 text-sm font-medium">
                <FormattedMessage id="ShopifyProducts / Store picker label" defaultMessage="Store" />
                <select
                  value={shopDomain}
                  // A new store starts at its first page, so the cursor is dropped; the page size is kept.
                  onChange={(event) => setSearchParams({ shop: event.target.value, perPage: String(perPage) })}
                  className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                  data-testid="shopify-products-store-picker"
                >
                  {shops.map((shop) => (
                    <option key={shop.shopDomain} value={shop.shopDomain}>
                      {shop.shopDomain}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="flex items-center gap-3 text-sm font-medium">
              <FormattedMessage id="ShopifyProducts / Per page label" defaultMessage="Products per page" />
              <select
                value={String(perPage)}
                // A cursor from one page size doesn't line up with another, so it's dropped: back to page 1.
                onChange={(event) => shopDomain && setSearchParams({ shop: shopDomain, perPage: event.target.value })}
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                data-testid="shopify-products-per-page"
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={String(size)}>
                    {size}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {renderContent()}
      </div>
    </PageLayout>
  );
};
