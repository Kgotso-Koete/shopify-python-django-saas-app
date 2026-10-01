import { useQuery } from '@apollo/client/react';
import { SubscriptionPlanName } from '@sb/webapp-api-client/api/subscription/types';
import { FormattedDate } from '@sb/webapp-core/components/dateTime/formattedDate';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@sb/webapp-core/components/ui/table';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { ArrowLeft, History } from 'lucide-react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { Link } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { useSubscriptionPlanDisplayName } from '../../hooks/useSubscriptionPlanDetails/useSubscriptionPlanDetails.hook';
import { payfastPaymentsQuery } from '../payfast.graphql';
import { useFormatZar } from '../useFormatZar.hook';

type Payment = { id: string; kind: string; plan: string; amountGross: string; createdAt: string };

/** PayFast counterpart of components/stripe/transactionHistory/transactionHistoryEntry. */
const PayfastTransactionHistoryEntry = ({ payment }: { payment: Payment }) => {
  const intl = useIntl();
  const formatZar = useFormatZar();
  const planName = useSubscriptionPlanDisplayName(payment.plan as SubscriptionPlanName);

  // The same labels as the Stripe history.
  const description =
    payment.kind === 'donation'
      ? intl.formatMessage({ defaultMessage: 'Donation', id: 'Stripe / Transaction History / Donation payment description' })
      : intl.formatMessage(
          { defaultMessage: '{planName} plan', id: 'Stripe / Transaction History / Subscription payment description' },
          { planName }
        );

  return (
    <TableRow>
      <TableCell>
        <FormattedDate value={payment.createdAt} />
      </TableCell>
      <TableCell>{description}</TableCell>
      {/* PayFast's payment notifications don't say which card or method was used. */}
      <TableCell>PayFast</TableCell>
      <TableCell>{formatZar(payment.amountGross)}</TableCell>
    </TableRow>
  );
};

/** PayFast counterpart of components/stripe/transactionHistory: the same table and columns. */
const PayfastTransactionHistoryList = () => {
  const { data: currentTenant } = useCurrentTenant();
  const { data } = useQuery(payfastPaymentsQuery, {
    fetchPolicy: 'cache-and-network',
    variables: { tenantId: currentTenant?.id ?? '' },
    skip: !currentTenant,
  });
  const payments = (data?.payfastPayments?.edges ?? []).flatMap((edge) => (edge?.node ? [edge.node as Payment] : []));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            <FormattedMessage id="Stripe / Transaction history / Date" defaultMessage="Date" />
          </TableHead>
          <TableHead>
            <FormattedMessage id="Stripe / Transaction history / Description" defaultMessage="Description" />
          </TableHead>
          <TableHead>
            <FormattedMessage id="Stripe / Transaction history / Payment method" defaultMessage="Payment method" />
          </TableHead>
          <TableHead>
            <FormattedMessage id="Stripe / Transaction history / Amount" defaultMessage="Amount" />
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {payments.map((payment) => (
          <PayfastTransactionHistoryEntry key={payment.id} payment={payment} />
        ))}
      </TableBody>
    </Table>
  );
};

/** PayFast counterpart of routes/transactionHistory: the same full-page transaction history. */
export const PayfastTransactionHistory = () => {
  const intl = useIntl();
  const generateTenantPath = useGenerateTenantPath();

  return (
    <PageLayout>
      <Helmet
        title={intl.formatMessage({ defaultMessage: 'Transaction History', id: 'Stripe / Transaction History / page title' })}
      />

      <div className="mx-auto w-full max-w-5xl space-y-8">
        <div className="space-y-4">
          <Link
            to={generateTenantPath(RoutesConfig.subscriptions.transactionHistory.index)}
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            <FormattedMessage defaultMessage="Back to transaction history" id="Stripe / Transaction History / Back" />
          </Link>
          <div className="flex items-center gap-2">
            <History className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage defaultMessage="Transaction history" id="Stripe / Transaction History / Header" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage defaultMessage="View transaction history" id="Stripe / Transaction History / Subheader" />
          </Paragraph>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <History className="h-5 w-5" />
              <FormattedMessage defaultMessage="Transactions" id="Stripe / Transaction History / Card Title" />
            </CardTitle>
            <CardDescription>
              <FormattedMessage
                defaultMessage="View all your past transactions and payments"
                id="Stripe / Transaction History / Card Description"
              />
            </CardDescription>
          </CardHeader>
          <CardContent>
            <PayfastTransactionHistoryList />
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
};

export default PayfastTransactionHistory;
