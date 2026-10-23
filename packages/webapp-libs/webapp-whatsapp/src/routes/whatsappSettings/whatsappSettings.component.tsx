import { useQuery } from '@apollo/client/react';
import { AccountPurpose } from '@sb/webapp-api-client/graphql';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { usePermissionCheck } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { AlertTriangle, MessageCircle, Users } from 'lucide-react';
import { ReactNode } from 'react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';

import { whatsAppAccountsQuery } from '../../graphql/whatsappAccounts.graphql';
import { AccountRow, WhatsAppAccount } from './accountRow.component';
import { ConnectNumberForm } from './connectNumberForm.component';

/**
 * The organization's WhatsApp page (WhatsApp plan Steps 1.6, 1.17 and 1.19, user story 11), in the
 * sidebar under Shopify products; it was a tab in organization settings until Step 1.19. Every number
 * belongs to the organization, and the page has a form for each kind, each with its own examples,
 * Connect number button and list: the internal communications number its team texts, of which it has
 * one, and the external communications numbers its store customers text.
 *
 * Everyone with whatsapp.view sees the numbers and their status; whatsapp.manage also connects, tests
 * and disconnects them. The backend checks the same permissions on every request: hiding the forms is
 * a courtesy, not the protection.
 */
export const WhatsAppSettings = () => {
  const intl = useIntl();
  const { data: currentTenant } = useCurrentTenant();
  const tenantId = currentTenant?.id ?? '';
  const { hasPermission: canManage } = usePermissionCheck('whatsapp.manage');
  const { data, loading, error, refetch } = useQuery(whatsAppAccountsQuery, {
    variables: { tenantId },
    skip: !tenantId,
  });
  const reload = () => {
    void refetch();
  };

  const accounts = data?.whatsAppAccounts ?? [];
  const shared = { tenantId, canManage, reload, loading: loading && !data, failed: Boolean(error) };

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
        <WhatsAppNumbers accounts={accounts} shared={shared} />
      </div>
    </PageLayout>
  );
};

type SharedProps = Pick<NumberSectionProps, 'tenantId' | 'canManage' | 'reload' | 'loading' | 'failed'>;
// As whatsAppAccountsQuery returns them: each with its purpose, which picks its section.
type ListedAccount = WhatsAppAccount & { purpose: AccountPurpose };

/** The two kinds of number, each in its own section, with one load error above them. */
const WhatsAppNumbers = ({ accounts, shared }: { accounts: ListedAccount[]; shared: SharedProps }) => {
  return (
    <div className="space-y-6">
      {shared.failed && (
        // A failed load must not look like "no numbers connected".
        <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="whatsapp-accounts-error">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <FormattedMessage
            defaultMessage="Couldn't load your WhatsApp numbers. Please refresh the page."
            id="WhatsAppSettings / Numbers / Load error"
          />
        </p>
      )}
      <NumberSection
        {...shared}
        purpose={AccountPurpose.INTERNAL_COMMUNICATIONS}
        accounts={accounts.filter((account) => account.purpose === AccountPurpose.INTERNAL_COMMUNICATIONS)}
        icon={<Users className="h-5 w-5" />}
        title={
          <FormattedMessage defaultMessage="Internal communications number" id="WhatsAppSettings / Internal / Title" />
        }
        description={
          <FormattedMessage
            defaultMessage="Your team texts this number to run the organization from WhatsApp: list and create items, rename the organization, check your Shopify products, or ask the AI assistant. It only answers members who have linked their phone on their profile page."
            id="WhatsAppSettings / Internal / Description"
          />
        }
        example={
          <FormattedMessage
            defaultMessage="Example: your shop manager texts “add an item called Winter stock”."
            id="WhatsAppSettings / Internal / Example"
          />
        }
      />
      <NumberSection
        {...shared}
        purpose={AccountPurpose.EXTERNAL_COMMUNICATIONS}
        accounts={accounts.filter((account) => account.purpose === AccountPurpose.EXTERNAL_COMMUNICATIONS)}
        icon={<MessageCircle className="h-5 w-5" />}
        title={
          <FormattedMessage defaultMessage="External communications numbers" id="WhatsAppSettings / External / Title" />
        }
        description={
          <FormattedMessage
            defaultMessage="Your customers text this number: browsing and ordering from your store, and order updates. Anyone can text it. Answering customers arrives in a later release; until then, messages are received and stored."
            id="WhatsAppSettings / External / Description"
          />
        }
        example={
          <FormattedMessage
            defaultMessage="Example: a customer texts “do you have blue shirts in medium?”."
            id="WhatsAppSettings / External / Example"
          />
        }
      />
    </div>
  );
};

type NumberSectionProps = {
  purpose: AccountPurpose;
  accounts: WhatsAppAccount[];
  tenantId: string;
  canManage: boolean;
  reload: () => void;
  loading: boolean;
  failed: boolean;
  icon: ReactNode;
  title: ReactNode;
  description: ReactNode;
  example: ReactNode;
};

/** One kind of number: what it's for, with an example, its form, and its connected numbers. */
const NumberSection = ({
  purpose,
  accounts,
  tenantId,
  canManage,
  reload,
  loading,
  failed,
  icon,
  title,
  description,
  example,
}: NumberSectionProps) => (
  <Card data-testid={`whatsapp-section-${purpose}`}>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        {icon}
        {title}
      </CardTitle>
      <CardDescription className="space-y-2">
        <span className="block">{description}</span>
        <span className="block italic">{example}</span>
      </CardDescription>
    </CardHeader>
    <CardContent className="space-y-6">
      {canManage && <ConnectNumberForm tenantId={tenantId} purpose={purpose} onConnected={reload} />}

      {loading ? (
        <div className="h-10 animate-pulse rounded bg-muted" />
      ) : failed ? null : accounts.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          <FormattedMessage defaultMessage="No number connected yet." id="WhatsAppSettings / Numbers / Empty" />
        </p>
      ) : (
        <ul className="divide-y rounded-md border">
          {accounts.map((account) => (
            <AccountRow key={account.id} account={account} tenantId={tenantId} canManage={canManage} onChanged={reload} />
          ))}
        </ul>
      )}
    </CardContent>
  </Card>
);
