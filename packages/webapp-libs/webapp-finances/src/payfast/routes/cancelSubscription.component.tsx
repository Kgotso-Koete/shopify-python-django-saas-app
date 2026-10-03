import { useMutation } from '@apollo/client/react';
import { SubscriptionPlanName } from '@sb/webapp-api-client/api/subscription/types';
import { Button, ButtonVariant, Link } from '@sb/webapp-core/components/buttons';
import { ConfirmDialog } from '@sb/webapp-core/components/confirmDialog';
import { FormattedDate } from '@sb/webapp-core/components/dateTime';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { Separator } from '@sb/webapp-core/components/ui/separator';
import { trackEvent } from '@sb/webapp-core/services/analytics';
import { useToast } from '@sb/webapp-core/toast/useToast';
import { reportError } from '@sb/webapp-core/utils/reportError';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { AlertTriangle, ArrowLeft, CreditCard, Info } from 'lucide-react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { Link as RouterLink, useNavigate } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { useSubscriptionPlanDisplayName } from '../../hooks/useSubscriptionPlanDetails/useSubscriptionPlanDetails.hook';
import { payfastActiveSubscriptionQuery, payfastCancelSubscriptionMutation } from '../payfast.graphql';
import { payfastErrorMessage } from '../payfastErrorMessage';
import { useFormatZar } from '../useFormatZar.hook';
import { usePayfastSubscription } from '../usePayfastSubscription.hook';

/**
 * PayFast counterpart of routes/cancelSubscription: the same page, details, confirmation and message.
 * PayFast stops charging immediately; the plan lasts until the end of the current period, then the
 * organisation is on the free plan, as with Stripe.
 */
export const PayfastCancelSubscription = () => {
  const intl = useIntl();
  const { toast } = useToast();
  const navigate = useNavigate();
  const formatZar = useFormatZar();
  const generateTenantPath = useGenerateTenantPath();
  const { subscription, isPaid, tenantId } = usePayfastSubscription();
  const planName = useSubscriptionPlanDisplayName(subscription?.effectivePlan as SubscriptionPlanName);
  const pendingPlanName = useSubscriptionPlanDisplayName(subscription?.pendingPlan as SubscriptionPlanName);

  // The same message as the Stripe page (routes/cancelSubscription/cancelSubscription.hook.ts).
  const successMessage = intl.formatMessage({
    defaultMessage: 'You will be moved to free plan with the next billing period',
    id: 'Cancel subscription / Success message',
  });

  const [cancel] = useMutation(payfastCancelSubscriptionMutation, {
    refetchQueries: [{ query: payfastActiveSubscriptionQuery, variables: { tenantId } }],
    onCompleted: () => {
      toast({ description: successMessage, variant: 'info' });
      trackEvent('subscription', 'cancel');
      navigate(generateTenantPath(RoutesConfig.subscriptions.index));
    },
    onError: (error) => {
      reportError(error);
      // Unlike Stripe, cancelling calls PayFast's API, which can fail; say why instead of failing silently.
      toast({ description: payfastErrorMessage(error, intl.formatMessage({ defaultMessage: 'Something went wrong. Please try again.', id: 'PayFast / Error / Generic' })), variant: 'destructive' });
    },
  });

  const handleCancel = () => {
    if (!tenantId) return;
    cancel({ variables: { input: { tenantId } } });
  };

  const hasActiveSubscription = isPaid && subscription && !subscription.cancelAtPeriodEnd;
  const isYearly = subscription?.effectivePlan === SubscriptionPlanName.YEARLY;
  // As on the current subscription page: a trial charges nothing yet, and a plan switch shows what
  // PayFast will charge from the next billing period.
  const isTrialing = subscription?.status === 'trialing';
  const hasPendingPrice = Boolean(subscription?.pendingPlan && subscription?.pendingAmount);
  const isPendingYearly = subscription?.pendingPlan === SubscriptionPlanName.YEARLY;

  return (
    <PageLayout>
      <Helmet title={intl.formatMessage({ defaultMessage: 'Cancel Subscription', id: 'Cancel subscription / page title' })} />

      <div className="mx-auto w-full max-w-5xl space-y-8">
        <div className="space-y-4">
          <RouterLink
            to={generateTenantPath(RoutesConfig.subscriptions.index)}
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            <FormattedMessage defaultMessage="Back to subscription" id="Cancel subscription / Back" />
          </RouterLink>
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-6 w-6 text-destructive" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage defaultMessage="Cancel Subscription" id="Cancel subscription / Header" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage defaultMessage="Details about your current plan" id="Cancel subscription / Current plan label" />
          </Paragraph>
        </div>

        {!hasActiveSubscription ? (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Info className="h-5 w-5" />
                <FormattedMessage defaultMessage="No Active Subscription" id="Cancel subscription / No active subscription title" />
              </CardTitle>
              <CardDescription>
                <FormattedMessage
                  defaultMessage="You don't have an active paid subscription to cancel."
                  id="Cancel subscription / No active subscription description"
                />
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-3">
                <Paragraph>
                  <FormattedMessage
                    defaultMessage="If you cancel your subscription, you will be moved to the free plan at the end of your current billing period. You'll continue to have access to all features until then."
                    id="Cancel subscription / Cancel explanation"
                  />
                </Paragraph>
                <Paragraph>
                  <FormattedMessage
                    defaultMessage="Alternatively, you can choose a different subscription plan that better fits your needs."
                    id="Cancel subscription / Alternative explanation"
                  />
                </Paragraph>
              </div>
              <Separator />
              <div>
                <Link to={generateTenantPath(RoutesConfig.subscriptions.currentSubscription.edit)} variant={ButtonVariant.PRIMARY}>
                  <FormattedMessage defaultMessage="Choose a subscription plan" id="Cancel subscription / Choose plan button" />
                </Link>
              </div>
            </CardContent>
          </Card>
        ) : (
          <>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <CreditCard className="h-5 w-5" />
                  <FormattedMessage defaultMessage="Current plan info" id="Cancel subscription / Current plan header" />
                </CardTitle>
                <CardDescription>
                  <FormattedMessage
                    defaultMessage="Review your subscription details before canceling"
                    id="Cancel subscription / Current plan description"
                  />
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1">
                  <div className="text-sm font-medium text-muted-foreground">
                    <FormattedMessage defaultMessage="Active plan:" id="Cancel subscription / Active plan" />
                  </div>
                  <Paragraph className="text-base font-semibold">{planName}</Paragraph>
                </div>
                <Separator />
                <div className="space-y-1">
                  <div className="text-sm font-medium text-muted-foreground">
                    <FormattedMessage defaultMessage="Active plan price:" id="Cancel subscription / Active plan price" />
                  </div>
                  <Paragraph className="text-base font-semibold">
                    {isTrialing ? (
                      <FormattedMessage defaultMessage="Free trial" id="PayFast / Cancel subscription / Free trial" />
                    ) : (
                      <>
                        {formatZar(subscription.amount)}
                        <span className="text-sm font-normal text-muted-foreground">
                          {isYearly ? ' / year' : ' / month'}
                        </span>
                      </>
                    )}
                  </Paragraph>
                </div>
                {hasPendingPrice && (
                  <>
                    <Separator />
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-muted-foreground">
                        <FormattedMessage defaultMessage="Next billing plan:" id="PayFast / My subscription / Next plan" />
                      </div>
                      <Paragraph className="text-base font-semibold">
                        <FormattedMessage
                          defaultMessage="{plan}, {price} / {interval}"
                          id="PayFast / My subscription / Next plan with price"
                          values={{
                            plan: pendingPlanName,
                            price: formatZar(subscription.pendingAmount),
                            interval: isPendingYearly ? (
                              <FormattedMessage defaultMessage="year" id="PayFast / My subscription / Year" />
                            ) : (
                              <FormattedMessage defaultMessage="month" id="PayFast / My subscription / Month" />
                            ),
                          }}
                        />
                      </Paragraph>
                    </div>
                  </>
                )}
                {subscription.currentPeriodEnd && (
                  <>
                    <Separator />
                    <div className="space-y-1">
                      <div className="text-sm font-medium text-muted-foreground">
                        <FormattedMessage defaultMessage="Next renewal / expiry:" id="Cancel subscription / Next renewal" />
                      </div>
                      <Paragraph className="text-base font-semibold">
                        <FormattedDate value={subscription.currentPeriodEnd} />
                      </Paragraph>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="border-destructive/50">
              <CardContent className="pt-6">
                <ConfirmDialog
                  title={<FormattedMessage defaultMessage="Cancel subscription" id="Cancel subscription / Confirm Dialog / Cancel Title" />}
                  description={
                    <FormattedMessage
                      id="Cancel subscription / Confirm Dialog / Cancel Description"
                      defaultMessage="Are you sure you want to cancel your subscription?"
                    />
                  }
                  onContinue={handleCancel}
                  variant="destructive"
                >
                  <Button variant="destructive" className="w-full sm:w-fit">
                    <FormattedMessage defaultMessage="Cancel subscription" id="Cancel subscription / Button label" />
                  </Button>
                </ConfirmDialog>
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </PageLayout>
  );
};

export default PayfastCancelSubscription;
