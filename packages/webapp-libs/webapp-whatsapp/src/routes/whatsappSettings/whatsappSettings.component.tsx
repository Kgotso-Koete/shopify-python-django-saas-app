import { useQuery } from '@apollo/client/react';
import { AccountPurpose, ConversationMode } from '@sb/webapp-api-client/graphql';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { PlanRequiredNotice } from '@sb/webapp-tenants/components/planRequiredNotice';
import { useOrganizationFeatures, usePermissionCheck } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { AlertTriangle, MessageCircle } from 'lucide-react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';

import { whatsAppAccountsQuery } from '../../graphql/whatsappAccounts.graphql';
import { whatsAppMetaAppsQuery } from '../../graphql/whatsappMetaApps.graphql';
import { whatsAppEligibleStoresQuery, whatsAppStorefrontsQuery } from '../../graphql/whatsappStorefronts.graphql';
import { servesCustomers } from '../../utils/purposes';
import { AccountRow, WhatsAppAccount } from './accountRow.component';
import { ConnectNumberForm } from './connectNumberForm.component';
import { MetaApp, MetaAppsCard } from './metaAppsCard.component';

/**
 * Which store each number serving customers sells from, and the stores the picker offers (WhatsApp plan
 * Step 2.1b, user story 25). A number serving the team only never sells.
 */
type Storefronts = {
  // The store each number sells from, by account id; null while none is chosen.
  storeOf: Map<string, string | null>;
  // Menus or the assistant for each number's customers (phase 2, decision 2); null while no store is chosen.
  modeOf: Map<string, ConversationMode | null>;
  // The organization's stores that can sell on WhatsApp; empty for whatsapp.view, which has no picker.
  eligibleStores: string[];
  // True once the picker's list has arrived, so "connect a store first" never flashes while it loads.
  storesLoaded: boolean;
};

// As whatsAppAccountsQuery returns them: each with its purpose, whom it serves.
type ListedAccount = WhatsAppAccount & { purpose: AccountPurpose };

/**
 * The organization's WhatsApp page (WhatsApp plan Steps 1.6, 1.17 and 1.19, user story 11), in the
 * sidebar under Shopify products. Every number belongs to the organization. Since Step 2.7 (decision 4)
 * the page has one form, asking who texts the number (the team, the customers, or both), and one list of
 * every number with whom it serves: one number for both, or two numbers kept apart.
 *
 * Everyone with whatsapp.view sees the numbers and their status; whatsapp.manage also connects, changes,
 * tests and disconnects them, and registers the organization's own Meta apps on a card of their own
 * (Step 2.9). The backend checks the same permissions on every request: hiding the controls is a
 * courtesy, not the protection.
 */
export const WhatsAppSettings = () => {
  const intl = useIntl();
  const { data: currentTenant } = useCurrentTenant();
  const tenantId = currentTenant?.id ?? '';
  const { hasPermission: canManage } = usePermissionCheck('whatsapp.manage');
  // Setting numbers up needs no plan, so a business is ready before its trial starts (WhatsApp plan
  // Step 2.8, finding 16): the page works as usual, and only says the numbers don't reply yet.
  const { isUnlocked } = useOrganizationFeatures();
  const unlocked = isUnlocked('WHATSAPP');
  const { data, loading, error, refetch } = useQuery(whatsAppAccountsQuery, {
    variables: { tenantId },
    skip: !tenantId,
  });
  const { data: storefrontsData, refetch: refetchStorefronts } = useQuery(whatsAppStorefrontsQuery, {
    variables: { tenantId },
    skip: !tenantId,
  });
  // Only the picker uses this list, and only whatsapp.manage sees the picker (the backend agrees).
  const { data: eligibleData } = useQuery(whatsAppEligibleStoresQuery, {
    variables: { tenantId },
    skip: !tenantId || !canManage,
  });
  // The organization's own Meta apps (Step 2.9): only whatsapp.manage, since the list holds their tokens.
  const { data: metaAppsData, refetch: refetchMetaApps } = useQuery(whatsAppMetaAppsQuery, {
    variables: { tenantId },
    skip: !tenantId || !canManage,
  });
  const metaApps: MetaApp[] = metaAppsData?.whatsAppMetaApps ?? [];
  const reload = () => {
    void refetch();
    void refetchStorefronts();
  };

  const accounts: ListedAccount[] = data?.whatsAppAccounts ?? [];
  const listed = storefrontsData?.whatsAppStorefronts ?? [];
  const storefronts: Storefronts = {
    storeOf: new Map(listed.map((storefront) => [storefront.accountId, storefront.shopDomain ?? null])),
    modeOf: new Map(listed.map((storefront) => [storefront.accountId, storefront.conversationMode ?? null])),
    eligibleStores: eligibleData?.whatsAppEligibleStores ?? [],
    storesLoaded: Boolean(eligibleData),
  };

  return (
    // The same page shell as the Shopify products page, its neighbour in the sidebar.
    <PageLayout>
      <Helmet title={intl.formatMessage({ defaultMessage: 'WhatsApp', id: 'WhatsAppSettings / page title' })} />
      <div className="mx-auto w-full max-w-5xl space-y-8">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <MessageCircle className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage defaultMessage="WhatsApp" id="WhatsAppSettings / Title" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage
              defaultMessage="The numbers your team and your customers text, connected to this app"
              id="WhatsAppSettings / Subheader"
            />
          </Paragraph>
        </div>

        {!unlocked && (
          <PlanRequiredNotice feature="WhatsApp">
            <FormattedMessage
              defaultMessage="Your numbers don't reply to anyone, your team or your customers, until your plan includes WhatsApp. You can connect and set them up now, and everything is kept. WhatsApp comes with the paid plans, free trial included."
              id="WhatsAppSettings / Plan required"
            />
          </PlanRequiredNotice>
        )}

        {error && (
          // A failed load must not look like "no numbers connected".
          <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="whatsapp-accounts-error">
            <AlertTriangle className="h-4 w-4 text-amber-500" />
            <FormattedMessage
              defaultMessage="Couldn't load your WhatsApp numbers. Please refresh the page."
              id="WhatsAppSettings / Numbers / Load error"
            />
          </p>
        )}

        <Card data-testid="whatsapp-numbers">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageCircle className="h-5 w-5" />
              <FormattedMessage defaultMessage="Your WhatsApp numbers" id="WhatsAppSettings / Numbers / Title" />
            </CardTitle>
            <CardDescription className="space-y-2">
              <span className="block">
                <FormattedMessage
                  defaultMessage="Your team texts a number to run the organization from WhatsApp: list and create items, rename the organization, check your Shopify products, or ask the AI assistant. It answers members who have linked their phone on their profile page. Your customers text a number to shop from the store it sells from: browse, search, fill a cart and check out in your Shopify checkout."
                  id="WhatsAppSettings / Numbers / Description"
                />
              </span>
              <span className="block">
                <FormattedMessage
                  defaultMessage="One number for both: members who linked their phone get the team's menus, and anyone else shops. Two numbers kept apart: your team's number answers only members, and on your customers' number everyone is a customer. Your organization has one number for its team."
                  id="WhatsAppSettings / Numbers / Setups"
                />
              </span>
              <span className="block italic">
                <FormattedMessage
                  defaultMessage="Examples: your shop manager texts “add an item called Winter stock”; a customer texts “do you have blue shirts in medium?”."
                  id="WhatsAppSettings / Numbers / Examples"
                />
              </span>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {canManage && (
              <ConnectNumberForm
                tenantId={tenantId}
                onConnected={reload}
                stores={storefronts.eligibleStores}
                storesLoaded={storefronts.storesLoaded}
                metaApps={metaApps}
              />
            )}

            {loading && !data ? (
              <div className="h-10 animate-pulse rounded bg-muted" />
            ) : error ? null : accounts.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                <FormattedMessage defaultMessage="No number connected yet." id="WhatsAppSettings / Numbers / Empty" />
              </p>
            ) : (
              <ul className="divide-y rounded-md border" data-testid="whatsapp-numbers-list">
                {accounts.map((account) => (
                  <AccountRow
                    key={account.id}
                    account={account}
                    tenantId={tenantId}
                    canManage={canManage}
                    onChanged={reload}
                    metaApps={metaApps}
                    // Only a number serving customers sells from a store (Step 2.1b).
                    store={servesCustomers(account.purpose) ? (storefronts.storeOf.get(account.id) ?? null) : undefined}
                    stores={storefronts.eligibleStores}
                    mode={storefronts.modeOf.get(account.id) ?? null}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        {canManage && <MetaAppsCard tenantId={tenantId} apps={metaApps} onChanged={() => void refetchMetaApps()} />}
      </div>
    </PageLayout>
  );
};
