import { useMutation, useQuery } from '@apollo/client/react';
import { SubscriptionPlanName } from '@sb/webapp-api-client/api/subscription/types';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent } from '@sb/webapp-core/components/ui/card';
import { trackEvent } from '@sb/webapp-core/services/analytics';
import { useToast } from '@sb/webapp-core/toast/useToast';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { ArrowLeft, CreditCard } from 'lucide-react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { Link } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { payfastCreateCheckoutMutation, payfastSubscriptionPlansQuery } from '../payfast.graphql';
import { payfastErrorMessage } from '../payfastErrorMessage';
import { submitPayfastCheckout } from '../submitPayfastCheckout';
import { usePayfastSubscription } from '../usePayfastSubscription.hook';
import { PayfastSubscriptionPlanItem } from './subscriptionPlanItem.component';

/** How much cheaper the yearly plan is than 12 monthly payments, in whole percent, or null if it isn't. */
const yearlySavingsPercent = (plans: Array<{ name: string; amount: string }>) => {
  const monthly = Number(plans.find((plan) => plan.name === SubscriptionPlanName.MONTHLY)?.amount ?? 0);
  const yearly = Number(plans.find((plan) => plan.name === SubscriptionPlanName.YEARLY)?.amount ?? 0);
  if (!monthly || !yearly) return null;
  const percent = Math.round((1 - yearly / (12 * monthly)) * 100);
  return percent > 0 ? percent : null;
};

/**
 * PayFast counterpart of routes/editSubscription: the same page and plan cards. A free organisation
 * choosing a paid plan is sent to PayFast to check out (with a free trial the first time); a paying
 * organisation switches with a new PayFast checkout that charges R0 now and the new price from the
 * end of the paid period, so the change applies at the next renewal, as on Stripe. As on the Stripe
 * page, moving to Free is done by cancelling, not from this page.
 */
export const PayfastEditSubscription = () => {
  const intl = useIntl();
  const { toast } = useToast();
  const generateTenantPath = useGenerateTenantPath();
  const { subscription, tenantId } = usePayfastSubscription();
  const { data: plansData, loading: plansLoading } = useQuery(payfastSubscriptionPlansQuery);

  const showError = (error: unknown) =>
    toast({ description: payfastErrorMessage(error, intl.formatMessage({ defaultMessage: 'Something went wrong. Please try again.', id: 'PayFast / Error / Generic' })), variant: 'destructive' });

  const [createCheckout, { loading: checkoutLoading }] = useMutation(payfastCreateCheckoutMutation, {
    onCompleted: (data) => {
      const checkout = data.payfastCreateCheckout?.checkout;
      if (!checkout) return;
      // Same analytics event as a Stripe plan change.
      trackEvent('subscription', 'change-plan');
      submitPayfastCheckout({ actionUrl: checkout.actionUrl, fields: checkout.fields });
    },
    onError: showError,
  });

  // Free organisations start a subscription; paying ones switch with a new subscription that
  // charges R0 now and the new price from the end of their paid period (plan section 10).
  const selectPlan = (planName: string) => {
    if (!tenantId) return;
    createCheckout({
      variables: {
        input: {
          tenantId,
          plan: planName,
          returnPath: `${generateTenantPath(RoutesConfig.finances.payfastReturn)}?kind=subscription`,
          cancelPath: generateTenantPath(RoutesConfig.subscriptions.currentSubscription.edit),
        },
      },
    });
  };

  const plans = plansData?.payfastSubscriptionPlans ?? [];
  const savings = yearlySavingsPercent(plans);

  return (
    <PageLayout>
      <Helmet title={intl.formatMessage({ defaultMessage: 'Choose a Plan', id: 'Change plan / page title' })} />

      <div className="mx-auto w-full max-w-5xl space-y-8">
        <div className="space-y-4">
          <Link
            to={generateTenantPath(RoutesConfig.subscriptions.index)}
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            <FormattedMessage defaultMessage="Back to subscription" id="Change plan / Back" />
          </Link>
          <div className="flex items-center gap-2">
            <CreditCard className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage defaultMessage="Plans" id="Change plan / Heading" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage defaultMessage="Choose a plan" id="Change plan / Subheading" />
          </Paragraph>
        </div>

        {plansLoading ? null : plans.length === 0 ? (
          <Card>
            <CardContent className="pt-6">
              <div className="text-center py-8">
                <p className="text-muted-foreground">
                  <FormattedMessage
                    defaultMessage="No subscription plans are currently available."
                    id="Change plan / No plans available"
                  />
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {plans.map((plan) => (
              <PayfastSubscriptionPlanItem
                key={plan.name}
                plan={plan}
                subscription={subscription}
                yearlySavingsPercent={savings}
                onSelect={selectPlan}
                loading={checkoutLoading}
              />
            ))}
          </div>
        )}
      </div>
    </PageLayout>
  );
};

export default PayfastEditSubscription;
