import { useQuery } from '@apollo/client/react';
import { apiClient, apiURL, auth } from '@sb/webapp-api-client/api';
import { SubscriptionPlanName } from '@sb/webapp-api-client/api/subscription/types';
import { Button, ButtonVariant } from '@sb/webapp-core/components/buttons';
import { FormattedDate } from '@sb/webapp-core/components/dateTime/formattedDate';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@sb/webapp-core/components/ui/table';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { ArrowLeft, Download, History } from 'lucide-react';
import { useState } from 'react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { Link } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { useSubscriptionPlanDisplayName } from '../../hooks/useSubscriptionPlanDetails/useSubscriptionPlanDetails.hook';
import { payfastActiveSubscriptionQuery, payfastInvoicesQuery, payfastPaymentsQuery } from '../payfast.graphql';
import { useFormatZar } from '../useFormatZar.hook';

type Payment = { id: string; kind: string; plan: string; amountGross: string; createdAt: string };
type Invoice = { id: string; number: string };

/**
 * Download invoice (WhatsApp plan phase 4, Step 4.5a, decisions 19 and 20). The login cookie lasts minutes
 * and only the GraphQL client renews it, so the button renews it first, then fetches the PDF from the
 * backend's checked address and saves it as a file, as the backup page saves its download. A refusal
 * shows a message here instead of an error page.
 */
const InvoiceDownload = ({ invoice }: { invoice: Invoice }) => {
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const onDownload = async () => {
    setFailed(false);
    setLoading(true);
    try {
      await auth.refreshToken();
      const { data } = await apiClient.get(apiURL(`/invoicing/${invoice.id}/pdf/`), { responseType: 'blob' });
      const url = URL.createObjectURL(data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${invoice.number}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-1">
      <Button variant={ButtonVariant.SECONDARY} size="sm" onClick={onDownload} disabled={loading}>
        <Download className="mr-1 h-4 w-4" />
        <FormattedMessage defaultMessage="Download invoice" id="PayFast / Transaction History / Download invoice" />
      </Button>
      {failed && (
        <p className="text-xs text-destructive">
          <FormattedMessage
            defaultMessage="The invoice couldn't be downloaded. Please try again."
            id="PayFast / Transaction History / Download invoice failed"
          />
        </p>
      )}
    </div>
  );
};

/** PayFast counterpart of components/stripe/transactionHistory/transactionHistoryEntry. */
const PayfastTransactionHistoryEntry = ({ payment, invoice }: { payment: Payment; invoice?: Invoice }) => {
  const intl = useIntl();
  const formatZar = useFormatZar();
  const planName = useSubscriptionPlanDisplayName(payment.plan as SubscriptionPlanName);

  // The same labels as the Stripe history. The kind is its stored name (PayFast plan section 14).
  const description =
    payment.kind === 'DONATION'
      ? intl.formatMessage({
          defaultMessage: 'Donation',
          id: 'Stripe / Transaction History / Donation payment description',
        })
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
      <TableCell>{invoice && <InvoiceDownload invoice={invoice} />}</TableCell>
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
  // Each payment's invoice, by the payment's GraphQL id (Step 4.5a); a payment may have none yet.
  const { data: invoicesData } = useQuery(payfastInvoicesQuery, {
    fetchPolicy: 'cache-and-network',
    variables: { tenantId: currentTenant?.id ?? '' },
    skip: !currentTenant,
  });
  const invoiceOf = new Map(
    (invoicesData?.invoices ?? []).flatMap((invoice) => (invoice.paymentId ? [[invoice.paymentId, invoice]] : []))
  );
  // User story WA.D6.OM.J2.A1: a free trial isn't a payment, so it has no invoice; until the first one, say
  // when it comes: the trial's end, when the first payment is charged.
  const { data: subscriptionData } = useQuery(payfastActiveSubscriptionQuery, {
    fetchPolicy: 'cache-and-network',
    variables: { tenantId: currentTenant?.id ?? '' },
    skip: !currentTenant,
  });
  const subscription = subscriptionData?.payfastActiveSubscription;
  const firstInvoiceDate =
    invoicesData && invoicesData.invoices?.length === 0 && subscription?.status === 'TRIALING'
      ? subscription.trialEnd
      : null;

  return (
    <>
      {firstInvoiceDate && (
        <Paragraph>
          <FormattedMessage
            id="PayFast / Transaction history / First invoice"
            defaultMessage="No invoices yet. Your first comes with your first payment on {date}."
            values={{ date: <FormattedDate value={firstInvoiceDate} /> }}
          />
        </Paragraph>
      )}
      <PayfastTransactionHistoryTable payments={payments} invoiceOf={invoiceOf} />
    </>
  );
};

const PayfastTransactionHistoryTable = ({
  payments,
  invoiceOf,
}: {
  payments: Payment[];
  invoiceOf: Map<string, Invoice>;
}) => {
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
          <TableHead>
            <FormattedMessage id="PayFast / Transaction history / Invoice" defaultMessage="Invoice" />
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {payments.map((payment) => (
          <PayfastTransactionHistoryEntry key={payment.id} payment={payment} invoice={invoiceOf.get(payment.id)} />
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
        title={intl.formatMessage({
          defaultMessage: 'Transaction History',
          id: 'Stripe / Transaction History / page title',
        })}
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
