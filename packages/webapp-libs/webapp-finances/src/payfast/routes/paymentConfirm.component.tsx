import { useMutation, useQuery } from '@apollo/client/react';
import { Button } from '@sb/webapp-core/components/buttons';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { RadioGroup, RadioGroupItem } from '@sb/webapp-core/components/ui/radio-group';
import { trackEvent } from '@sb/webapp-core/services/analytics';
import { useToast } from '@sb/webapp-core/toast/useToast';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { CreditCard, Wallet } from 'lucide-react';
import { useState } from 'react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';

import { RoutesConfig } from '../../config/routes';
import { payfastCreateDonationCheckoutMutation, payfastDonationAmountsQuery } from '../payfast.graphql';
import { payfastErrorMessage } from '../payfastErrorMessage';
import { submitPayfastCheckout } from '../submitPayfastCheckout';
import { useFormatZar } from '../useFormatZar.hook';

/**
 * PayFast counterpart of the Stripe donation page (routes/paymentConfirm): the same fixed-amount
 * picker, then the buyer pays on PayFast's page and comes back to the PayFast return page.
 */
export const PayfastPaymentConfirm = () => {
  const intl = useIntl();
  const { toast } = useToast();
  const formatZar = useFormatZar();
  const generateTenantPath = useGenerateTenantPath();
  const { data: currentTenant } = useCurrentTenant();
  const [amount, setAmount] = useState<string>('');

  const { data } = useQuery(payfastDonationAmountsQuery);
  const [createDonation, { loading }] = useMutation(payfastCreateDonationCheckoutMutation, {
    onCompleted: (result) => {
      const checkout = result.payfastCreateDonationCheckout?.checkout;
      if (!checkout) return;
      // Same analytics event as a Stripe donation.
      trackEvent('payment', 'make-payment');
      submitPayfastCheckout({ actionUrl: checkout.actionUrl, fields: checkout.fields });
    },
    onError: (error) =>
      toast({ description: payfastErrorMessage(error, intl.formatMessage({ defaultMessage: 'Something went wrong. Please try again.', id: 'PayFast / Error / Generic' })), variant: 'destructive' }),
  });

  const pay = () => {
    if (!currentTenant || !amount) return;
    createDonation({
      variables: {
        input: {
          tenantId: currentTenant.id,
          amount,
          returnPath: `${generateTenantPath(RoutesConfig.finances.payfastReturn)}?kind=donation`,
          cancelPath: generateTenantPath(RoutesConfig.finances.paymentConfirm),
        },
      },
    });
  };

  return (
    <PageLayout>
      <Helmet title={intl.formatMessage({ defaultMessage: 'Payments', id: 'PayFast / Payment confirm / page title' })} />

      <div className="mx-auto w-full max-w-5xl space-y-8">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <Wallet className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage defaultMessage="Payments" id="PayFast / Payment confirm / heading" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage
              defaultMessage="Example of a single payment powered by PayFast. Choose an amount to donate, then pay securely on PayFast."
              id="PayFast / Payment confirm / subheading"
            />
          </Paragraph>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              <FormattedMessage defaultMessage="Payment Details" id="PayFast / Payment form / Title" />
            </CardTitle>
            <CardDescription>
              <FormattedMessage
                defaultMessage="Complete your payment securely with PayFast"
                id="PayFast / Payment form / Description"
              />
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-8">
            {/* The same label and description as the Stripe donation form (components/stripe/stripePaymentForm). */}
            <div className="space-y-2">
              <p className="text-sm font-medium">
                <FormattedMessage defaultMessage="Choose the amount" id="Stripe / payment form / product label" />
              </p>
              <p className="text-sm text-muted-foreground">
                <FormattedMessage
                  defaultMessage="Select amount you would like to donate"
                  id="Stripe / payment form / product description"
                />
              </p>
            </div>
            <RadioGroup value={amount} onValueChange={setAmount} className="grid max-w-md grid-cols-3 gap-8 pt-2">
              {(data?.payfastDonationAmounts ?? []).map((value) => {
                const id = `payfast-donation-${value}`;
                return (
                  <label
                    key={value}
                    htmlFor={id}
                    className="flex justify-center items-center rounded-md border-2 border-muted p-1 aspect-square cursor-pointer font-semibold text-lg has-[[data-state=checked]]:border-primary"
                  >
                    <RadioGroupItem id={id} value={String(value)} className="sr-only" />
                    {formatZar(value)}
                  </label>
                );
              })}
            </RadioGroup>

            <Button type="button" disabled={!amount || loading} onClick={pay}>
              <FormattedMessage
                defaultMessage="Pay {amount}"
                id="PayFast / Payment form / Pay CTA"
                values={{ amount: amount ? formatZar(amount) : '' }}
              />
            </Button>
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
};

export default PayfastPaymentConfirm;
