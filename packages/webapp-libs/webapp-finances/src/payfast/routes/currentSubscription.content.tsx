import { SubscriptionPlanName } from '@sb/webapp-api-client/api/subscription/types';
import { ButtonVariant, Link } from '@sb/webapp-core/components/buttons';
import { FormattedDate } from '@sb/webapp-core/components/dateTime';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { useGenerateTenantPath, usePermissionCheck } from '@sb/webapp-tenants/hooks';
import { AlarmClock, ArrowRightToLine, CalendarClock, CreditCard, StepForward } from 'lucide-react';
import { ReactNode } from 'react';
import { FormattedMessage } from 'react-intl';

import { RoutesConfig } from '../../config/routes';
import { useSubscriptionPlanDisplayName } from '../../hooks/useSubscriptionPlanDetails/useSubscriptionPlanDetails.hook';
import { useFormatZar } from '../useFormatZar.hook';
import { usePayfastSubscription } from '../usePayfastSubscription.hook';

const DetailRow = ({ icon, label, children }: { icon: ReactNode; label: ReactNode; children: ReactNode }) => (
  <div className="flex items-center gap-3 rounded-md p-3 bg-muted/50">
    {icon}
    <div className="flex-1 min-w-0">
      <p className="text-sm font-medium">{label}</p>
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  </div>
);

/**
 * PayFast counterpart of routes/subscriptions/subscriptions.content.tsx: the tenant's plan, price,
 * renewal or expiry date, trial end and any plan change waiting for the next renewal.
 */
export const PayfastCurrentSubscriptionContent = () => {
  const generateTenantPath = useGenerateTenantPath();
  const { hasPermission: canManageBilling } = usePermissionCheck('billing.manage');
  const formatZar = useFormatZar();
  const { subscription, isPaid } = usePayfastSubscription();

  const planName = useSubscriptionPlanDisplayName(
    (subscription?.effectivePlan ?? SubscriptionPlanName.FREE) as SubscriptionPlanName
  );
  const pendingPlanName = useSubscriptionPlanDisplayName(subscription?.pendingPlan as SubscriptionPlanName);

  if (!subscription) return null;

  const isYearly = subscription.effectivePlan === SubscriptionPlanName.YEARLY;
  const isTrialing = subscription.status === 'trialing';

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            <FormattedMessage defaultMessage="Current subscription" id="PayFast / My subscription / Header" />
          </CardTitle>
          <CardDescription>
            <FormattedMessage defaultMessage="Manage your subscription" id="PayFast / My subscription / Subheader" />
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">
                <FormattedMessage defaultMessage="Current plan:" id="PayFast / My subscription / Active plan" />
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-2xl font-semibold">{planName}</p>
                {isPaid ? (
                  <p className="text-sm text-muted-foreground mt-1">
                    {formatZar(subscription.amount)} /{' '}
                    {isYearly ? (
                      <FormattedMessage defaultMessage="year" id="PayFast / My subscription / Year" />
                    ) : (
                      <FormattedMessage defaultMessage="month" id="PayFast / My subscription / Month" />
                    )}
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground mt-1">
                    <FormattedMessage defaultMessage="Free plan" id="PayFast / My subscription / Free plan" />
                  </p>
                )}
              </div>

              {isPaid && subscription.currentPeriodEnd && (
                <div className="space-y-2 pt-2 border-t">
                  {subscription.cancelAtPeriodEnd ? (
                    <DetailRow
                      icon={<CalendarClock className="h-5 w-5 text-muted-foreground flex-shrink-0" />}
                      label={<FormattedMessage defaultMessage="Expiry date:" id="PayFast / My subscription / Expiry date" />}
                    >
                      <FormattedDate value={subscription.currentPeriodEnd} />
                    </DetailRow>
                  ) : (
                    <DetailRow
                      icon={<ArrowRightToLine className="h-5 w-5 text-muted-foreground flex-shrink-0" />}
                      label={<FormattedMessage defaultMessage="Next renewal:" id="PayFast / My subscription / Next renewal" />}
                    >
                      <FormattedDate value={subscription.currentPeriodEnd} />
                    </DetailRow>
                  )}

                  {subscription.pendingPlan && (
                    <DetailRow
                      icon={<StepForward className="h-5 w-5 text-muted-foreground flex-shrink-0" />}
                      label={
                        <FormattedMessage defaultMessage="Next billing plan:" id="PayFast / My subscription / Next plan" />
                      }
                    >
                      {pendingPlanName}
                    </DetailRow>
                  )}

                  {isTrialing && subscription.trialEnd && (
                    <DetailRow
                      icon={<AlarmClock className="h-5 w-5 text-muted-foreground flex-shrink-0" />}
                      label={
                        <FormattedMessage
                          defaultMessage="Free trial expiry date:"
                          id="PayFast / My subscription / Trial expiry date"
                        />
                      }
                    >
                      <FormattedDate value={subscription.trialEnd} />
                    </DetailRow>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {canManageBilling && (
            <div className="flex flex-col sm:flex-row gap-6">
              <Link
                to={generateTenantPath(RoutesConfig.subscriptions.currentSubscription.edit)}
                variant={ButtonVariant.PRIMARY}
              >
                <FormattedMessage defaultMessage="Edit subscription" id="PayFast / My subscription / Edit subscription" />
              </Link>
              {isPaid && !subscription.cancelAtPeriodEnd && (
                <Link
                  to={generateTenantPath(RoutesConfig.subscriptions.currentSubscription.cancel)}
                  variant={ButtonVariant.SECONDARY}
                >
                  <FormattedMessage
                    defaultMessage="Cancel subscription"
                    id="PayFast / My subscription / Cancel subscription"
                  />
                </Link>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default PayfastCurrentSubscriptionContent;
