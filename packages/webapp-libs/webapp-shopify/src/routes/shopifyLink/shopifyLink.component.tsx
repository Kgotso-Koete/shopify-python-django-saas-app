import { useMutation, useQuery } from '@apollo/client/react';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { Link as LinkIcon, Store, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { FC, useCallback, useState } from 'react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { shopifyClaimQuery, shopifyLinkShopMutation } from '../../graphql/shopify.graphql';

export const ShopifyLink: FC = () => {
  const intl = useIntl();
  const navigate = useNavigate();
  // The shops list lives under /:lang/:tenantId/, so the path must carry the tenant id.
  const generateTenantPath = useGenerateTenantPath();
  const { data: currentTenant } = useCurrentTenant();
  const [searchParams] = useSearchParams();
  const claim = searchParams.get('claim') ?? '';
  const [linked, setLinked] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const { data: claimData, loading: claimLoading, error: claimError } = useQuery(shopifyClaimQuery, {
    variables: { claim },
    skip: !claim,
  });

  const [linkShop, { loading: linkLoading }] = useMutation(shopifyLinkShopMutation);

  const handleLink = useCallback(async () => {
    if (!currentTenant?.id || !claim) return;

    try {
      await linkShop({
        variables: {
          input: { tenantId: currentTenant.id, claim },
        },
      });
      setLinked(true);
      setTimeout(() => {
        navigate(generateTenantPath(RoutesConfig.shopify.list));
      }, 2000);
    } catch (err: any) {
      setErrorMessage(err?.message ?? String(err));
    }
  }, [currentTenant, claim, linkShop, navigate, generateTenantPath]);

  if (!claim) {
    return (
      <PageLayout>
        <Helmet
          title={intl.formatMessage({ defaultMessage: 'Link Shopify Store', id: 'ShopifyLink / page title no claim' })}
        />
        <div className="mx-auto w-full max-w-2xl">
          <Card>
            <CardContent className="py-16">
              <div className="flex flex-col items-center justify-center text-center">
                <AlertTriangle className="h-12 w-12 text-muted-foreground mb-4" />
                <h3 className="text-lg font-semibold mb-2">
                  <FormattedMessage id="ShopifyLink / No claim title" defaultMessage="No link provided" />
                </h3>
                <p className="text-sm text-muted-foreground">
                  <FormattedMessage
                    id="ShopifyLink / No claim description"
                    defaultMessage="This page requires a valid claim parameter. Install the app from Shopify first."
                  />
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </PageLayout>
    );
  }

  if (claimLoading) {
    return (
      <PageLayout>
        <div className="mx-auto w-full max-w-2xl animate-pulse space-y-4">
          <div className="h-8 w-48 rounded bg-muted" />
          <div className="h-64 rounded bg-muted" />
        </div>
      </PageLayout>
    );
  }

  if (claimError || !claimData?.shopifyClaim) {
    return (
      <PageLayout>
        <Helmet
          title={intl.formatMessage({ defaultMessage: 'Link Expired', id: 'ShopifyLink / page title expired' })}
        />
        <div className="mx-auto w-full max-w-2xl">
          <Card>
            <CardContent className="py-16">
              <div className="flex flex-col items-center justify-center text-center" data-testid="shopify-link-expired">
                <AlertTriangle className="h-12 w-12 text-amber-500 mb-4" />
                <h3 className="text-lg font-semibold mb-2">
                  <FormattedMessage id="ShopifyLink / Expired title" defaultMessage="This link has expired" />
                </h3>
                <p className="text-sm text-muted-foreground mb-4">
                  <FormattedMessage
                    id="ShopifyLink / Expired description"
                    defaultMessage="The store may already be connected, or the link has expired. Open the app from Shopify to get a new link."
                  />
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </PageLayout>
    );
  }

  const shopDomain = claimData.shopifyClaim.shopDomain;

  if (linked) {
    return (
      <PageLayout>
        <Helmet
          title={intl.formatMessage({ defaultMessage: 'Store Connected', id: 'ShopifyLink / page title success' })}
        />
        <div className="mx-auto w-full max-w-2xl">
          <Card>
            <CardContent className="py-16">
              <div className="flex flex-col items-center justify-center text-center" data-testid="shopify-link-success">
                <CheckCircle2 className="h-12 w-12 text-green-500 mb-4" />
                <h3 className="text-lg font-semibold mb-2">
                  <FormattedMessage id="ShopifyLink / Success title" defaultMessage="Store connected!" />
                </h3>
                <p className="text-sm text-muted-foreground">
                  <FormattedMessage
                    id="ShopifyLink / Success description"
                    defaultMessage="{domain} is now connected to your organization. Redirecting…"
                    values={{ domain: shopDomain }}
                  />
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout>
      <Helmet
        title={intl.formatMessage({ defaultMessage: 'Link Shopify Store', id: 'ShopifyLink / page title' })}
      />

      <div className="mx-auto w-full max-w-2xl space-y-8">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <LinkIcon className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage id="ShopifyLink / Title" defaultMessage="Connect Shopify Store" />
            </h1>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Store className="h-5 w-5" />
              {shopDomain}
            </CardTitle>
            <CardDescription>
              <FormattedMessage
                id="ShopifyLink / Card description"
                defaultMessage="Connect this store to your current organization"
              />
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {errorMessage && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive" data-testid="shopify-link-error">
                {errorMessage}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <button
                onClick={() => navigate(generateTenantPath(RoutesConfig.shopify.list))}
                className="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium ring-offset-background transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                <FormattedMessage id="ShopifyLink / Cancel" defaultMessage="Cancel" />
              </button>
              <button
                onClick={handleLink}
                disabled={linkLoading}
                className="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground ring-offset-background transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
                data-testid="shopify-link-confirm"
              >
                <FormattedMessage id="ShopifyLink / Confirm" defaultMessage="Connect to this organization" />
              </button>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
};
