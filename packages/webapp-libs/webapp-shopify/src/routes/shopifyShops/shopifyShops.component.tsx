import { useMutation, useQuery } from '@apollo/client/react';
import { ButtonVariant, Link } from '@sb/webapp-core/components/buttons';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { Store, Plus, AlertTriangle, XCircle, CheckCircle2, Unplug } from 'lucide-react';
import { FC, FormEvent, useCallback, useState } from 'react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';

import {
  shopifyConfigQuery,
  shopifyShopsQuery,
  shopifyStartInstallMutation,
  shopifyDisconnectShopMutation,
} from '../../graphql/shopify.graphql';

export const ShopifyShops: FC = () => {
  const intl = useIntl();
  const { data: currentTenant } = useCurrentTenant();
  const [shopDomain, setShopDomain] = useState('');
  const [domainError, setDomainError] = useState('');
  const [disconnecting, setDisconnecting] = useState<string | null>(null);

  const { data: configData, loading: configLoading } = useQuery(shopifyConfigQuery);
  const { data: shopsData, loading: shopsLoading, refetch } = useQuery(shopifyShopsQuery, {
    variables: { tenantId: currentTenant?.id ?? '' },
    skip: !currentTenant,
  });

  const [startInstall, { loading: installLoading }] = useMutation(shopifyStartInstallMutation);
  const [disconnectShop] = useMutation(shopifyDisconnectShopMutation);

  const isValidDomain = (domain: string): boolean => {
    return /^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$/.test(domain);
  };

  const handleStartInstall = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      setDomainError('');

      if (!isValidDomain(shopDomain)) {
        setDomainError(
          intl.formatMessage({
            defaultMessage: 'Enter a valid Shopify domain (e.g. my-store.myshopify.com)',
            id: 'ShopifyShops / Invalid domain',
          })
        );
        return;
      }

      try {
        const result = await startInstall({
          variables: {
            input: { tenantId: currentTenant?.id ?? '', shopDomain },
          },
        });
        const url = result.data?.shopifyStartInstall?.authorizeUrl;
        if (url) {
          window.location.href = url;
        }
      } catch (err) {
        setDomainError(String(err));
      }
    },
    [shopDomain, currentTenant, startInstall, intl]
  );

  const handleDisconnect = useCallback(
    async (domain: string) => {
      if (!window.confirm(intl.formatMessage(
        { defaultMessage: 'Disconnect {domain}? The app stays installed on the store.', id: 'ShopifyShops / Confirm disconnect' },
        { domain }
      ))) {
        return;
      }

      setDisconnecting(domain);
      try {
        await disconnectShop({
          variables: {
            input: { tenantId: currentTenant?.id ?? '', shopDomain: domain },
          },
        });
        await refetch();
      } finally {
        setDisconnecting(null);
      }
    },
    [currentTenant, disconnectShop, refetch, intl]
  );

  if (configLoading) {
    return (
      <PageLayout>
        <div className="mx-auto w-full max-w-5xl animate-pulse space-y-4">
          <div className="h-8 w-48 rounded bg-muted" />
          <div className="h-4 w-96 rounded bg-muted" />
          <div className="h-64 rounded bg-muted" />
        </div>
      </PageLayout>
    );
  }

  if (!configData?.shopifyConfig?.enabled) {
    return (
      <PageLayout>
        <Helmet
          title={intl.formatMessage({ defaultMessage: 'Shopify', id: 'ShopifyShops / page title disabled' })}
        />
        <div className="mx-auto w-full max-w-5xl">
          <Card>
            <CardContent className="py-16">
              <div className="flex flex-col items-center justify-center text-center">
                <AlertTriangle className="h-12 w-12 text-muted-foreground mb-4" />
                <h3 className="text-lg font-semibold mb-2">
                  <FormattedMessage id="ShopifyShops / Not configured title" defaultMessage="Shopify integration is not configured" />
                </h3>
                <p className="text-sm text-muted-foreground">
                  <FormattedMessage
                    id="ShopifyShops / Not configured description"
                    defaultMessage="Set SHOPIFY_API_KEY and SHOPIFY_API_SECRET to enable it."
                  />
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </PageLayout>
    );
  }

  const shops = shopsData?.shopifyShops ?? [];

  const getBadge = (shop: (typeof shops)[number]) => {
    if (shop.needsReinstall) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-400">
          <AlertTriangle className="h-3 w-3" />
          <FormattedMessage id="ShopifyShops / Badge needs reinstall" defaultMessage="Needs reinstall" />
        </span>
      );
    }
    if (shop.uninstalledAt) {
      return (
        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400">
          <XCircle className="h-3 w-3" />
          <FormattedMessage id="ShopifyShops / Badge uninstalled" defaultMessage="Uninstalled" />
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
        <CheckCircle2 className="h-3 w-3" />
        <FormattedMessage id="ShopifyShops / Badge active" defaultMessage="Active" />
      </span>
    );
  };

  return (
    <PageLayout>
      <Helmet
        title={intl.formatMessage({ defaultMessage: 'Shopify Stores', id: 'ShopifyShops / page title' })}
      />

      <div className="mx-auto w-full max-w-5xl space-y-8">
        {/* Header */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Store className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage id="ShopifyShops / Title" defaultMessage="Shopify Stores" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage
              id="ShopifyShops / Subheader"
              defaultMessage="Connect and manage your Shopify stores"
            />
          </Paragraph>
        </div>

        {/* Connect a store form */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Plus className="h-5 w-5" />
              <FormattedMessage id="ShopifyShops / Connect title" defaultMessage="Connect a store" />
            </CardTitle>
            <CardDescription>
              <FormattedMessage
                id="ShopifyShops / Connect description"
                defaultMessage="Enter your Shopify store domain to start the installation"
              />
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleStartInstall} className="flex gap-3">
              <div className="flex-1">
                <input
                  type="text"
                  value={shopDomain}
                  onChange={(e) => {
                    setShopDomain(e.target.value);
                    setDomainError('');
                  }}
                  placeholder="my-store.myshopify.com"
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  data-testid="shopify-domain-input"
                />
                {domainError && (
                  <p className="mt-1 text-sm text-destructive" data-testid="shopify-domain-error">
                    {domainError}
                  </p>
                )}
              </div>
              <button
                type="submit"
                disabled={installLoading || !shopDomain}
                className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground ring-offset-background transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
                data-testid="shopify-connect-button"
              >
                <FormattedMessage id="ShopifyShops / Connect button" defaultMessage="Connect" />
              </button>
            </form>
          </CardContent>
        </Card>

        {/* Stores list */}
        {shopsLoading ? (
          <Card>
            <CardContent className="py-8">
              <div className="animate-pulse space-y-3">
                <div className="h-10 rounded bg-muted" />
                <div className="h-10 rounded bg-muted" />
              </div>
            </CardContent>
          </Card>
        ) : shops.length === 0 ? (
          <Card>
            <CardContent className="py-16">
              <div className="flex flex-col items-center justify-center text-center">
                <Store className="h-12 w-12 text-muted-foreground mb-4" />
                <h3 className="text-lg font-semibold mb-2">
                  <FormattedMessage id="ShopifyShops / Empty title" defaultMessage="No stores connected" />
                </h3>
                <p className="text-sm text-muted-foreground">
                  <FormattedMessage
                    id="ShopifyShops / Empty description"
                    defaultMessage="Connect your first Shopify store using the form above"
                  />
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Store className="h-5 w-5" />
                <FormattedMessage id="ShopifyShops / Stores title" defaultMessage="Connected stores" />
              </CardTitle>
              <CardDescription>
                <FormattedMessage
                  id="ShopifyShops / Stores description"
                  defaultMessage="{count, plural, one {# store} other {# stores}} connected to this organization"
                  values={{ count: shops.length }}
                />
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <ul className="divide-y" data-testid="shopify-shops-list">
                {shops.map((shop) => (
                  <li
                    key={shop.shopDomain}
                    className="flex items-center justify-between px-6 py-4"
                    data-testid={`shopify-shop-${shop.shopDomain}`}
                  >
                    <div className="flex items-center gap-3">
                      <Store className="h-5 w-5 text-muted-foreground" />
                      <div>
                        <p className="text-sm font-medium">{shop.shopDomain}</p>
                        <p className="text-xs text-muted-foreground">
                          {shop.scopes?.join(', ')}
                        </p>
                      </div>
                      {getBadge(shop)}
                    </div>
                    <button
                      onClick={() => handleDisconnect(shop.shopDomain)}
                      disabled={disconnecting === shop.shopDomain}
                      className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground shadow-sm hover:bg-accent hover:text-accent-foreground transition-colors disabled:opacity-50"
                      data-testid={`shopify-disconnect-${shop.shopDomain}`}
                    >
                      <Unplug className="h-3 w-3" />
                      <FormattedMessage id="ShopifyShops / Disconnect" defaultMessage="Disconnect" />
                    </button>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>
    </PageLayout>
  );
};
