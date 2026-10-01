import { SubscriptionPlanName } from '@sb/webapp-api-client/api/subscription/types';
import { Button } from '@sb/webapp-core/components/buttons';
import { Badge } from '@sb/webapp-core/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { cn } from '@sb/webapp-core/lib/utils';
import { Check, Clock, Crown, Gift, Sparkles, Zap } from 'lucide-react';
import { times } from 'ramda';
import { FormattedMessage, useIntl } from 'react-intl';

import { useSubscriptionPlanDisplayName } from '../../hooks/useSubscriptionPlanDetails/useSubscriptionPlanDetails.hook';
import { useFormatZar } from '../useFormatZar.hook';

export type PayfastPlan = { name: string; amount: string; interval?: string | null };

export type PayfastSubscriptionPlanItemProps = {
  plan: PayfastPlan;
  subscription: {
    effectivePlan: string;
    pendingPlan?: string | null;
    cancelAtPeriodEnd: boolean;
    canActivateTrial: boolean;
  } | null;
  /** How much cheaper the yearly plan is than 12 monthly payments, in whole percent; null when it isn't. */
  yearlySavingsPercent: number | null;
  onSelect: (planName: string) => void;
  className?: string;
  loading: boolean;
};

/**
 * PayFast counterpart of routes/editSubscription/subscriptionPlanItem: the same card, layout, states
 * and wording (and the same translation ids), fed by PayFast data. Differences forced by PayFast:
 * prices are in ZAR, and the free trial notice only shows while on the free plan, because a PayFast
 * trial starts with the first checkout and a later plan change has none.
 */
export const PayfastSubscriptionPlanItem = ({
  plan,
  subscription,
  yearlySavingsPercent,
  onSelect,
  className,
  loading,
}: PayfastSubscriptionPlanItemProps) => {
  const intl = useIntl();
  const formatZar = useFormatZar();
  const name = useSubscriptionPlanDisplayName(plan.name as SubscriptionPlanName);

  // The same example features as the Stripe card (hooks/useSubscriptionPlanDetails).
  const exampleFeature = intl.formatMessage({
    id: 'Subscription plan example feature / Free',
    defaultMessage: 'Lorem ipsum dolor sit amet',
  });
  const features = times(() => exampleFeature, 5);

  const isFree = plan.name === SubscriptionPlanName.FREE;
  const isPremium = plan.name === SubscriptionPlanName.YEARLY;
  const isMonthly = plan.name === SubscriptionPlanName.MONTHLY;
  const isOnFreePlan = subscription?.effectivePlan === SubscriptionPlanName.FREE;
  // As on Stripe: the plan of the current period is active unless it has been cancelled.
  const isActive = subscription?.effectivePlan === plan.name && !subscription?.cancelAtPeriodEnd;
  // As on Stripe: the next period's plan is "scheduled" (a pending change, or Free after cancelling).
  const isScheduledForNextPeriod =
    subscription?.pendingPlan === plan.name || (isFree && Boolean(subscription?.cancelAtPeriodEnd) && !isOnFreePlan);
  const isTrialEligible = Boolean(subscription?.canActivateTrial) && isOnFreePlan;

  const handleSelect = () => onSelect(plan.name);

  const getButtonText = () => {
    if (isActive) {
      return <FormattedMessage defaultMessage="Current plan" id="Change plan item / Current plan" />;
    }
    if (isScheduledForNextPeriod) {
      return <FormattedMessage defaultMessage="Scheduled" id="Change plan item / Scheduled" />;
    }
    if (isFree) {
      return <FormattedMessage defaultMessage="Free plan" id="Change plan item / Free plan button" />;
    }
    return <FormattedMessage defaultMessage="Select plan" id="Change plan item / Select plan" />;
  };

  return (
    <Card
      data-plan={plan.name}
      className={cn(
        'relative overflow-hidden transition-all duration-200 hover:shadow-lg',
        {
          'ring-2 ring-primary border-primary shadow-md': isActive,
          'border-amber-200 dark:border-amber-800 bg-gradient-to-b from-amber-50/50 to-transparent dark:from-amber-950/20':
            isPremium && !isActive,
          'border-blue-200 dark:border-blue-800 bg-gradient-to-b from-blue-50/30 to-transparent dark:from-blue-950/20':
            isMonthly && !isActive,
          'bg-muted/30': isFree && !isActive,
        },
        className
      )}
    >
      {isPremium && !isActive && (
        <div className="absolute top-0 right-0">
          <div className="bg-gradient-to-r from-amber-500 to-amber-600 text-white text-xs font-semibold px-3 py-1 rounded-bl-lg shadow-sm flex items-center gap-1">
            <Sparkles className="h-3 w-3" />
            <FormattedMessage defaultMessage="Best value" id="Change plan item / Best value" />
          </div>
        </div>
      )}

      <CardHeader className="pb-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div
              className={cn('p-2 rounded-lg', {
                'bg-primary/10 text-primary': isActive,
                'bg-amber-100 text-amber-600 dark:bg-amber-900 dark:text-amber-400': isPremium && !isActive,
                'bg-blue-100 text-blue-600 dark:bg-blue-900 dark:text-blue-400': isMonthly && !isActive,
                'bg-muted text-muted-foreground': isFree && !isActive,
              })}
            >
              {isFree ? <Gift className="h-5 w-5" /> : isPremium ? <Crown className="h-5 w-5" /> : <Zap className="h-5 w-5" />}
            </div>
            <CardTitle className="text-xl">{name}</CardTitle>
          </div>

          <div className="flex gap-1.5">
            {isActive && (
              <Badge variant="success" className="gap-1">
                <Check className="h-3 w-3" />
                <FormattedMessage defaultMessage="Active" id="Change plan item / Active badge" />
              </Badge>
            )}
            {isScheduledForNextPeriod && !isActive && (
              <Badge variant="info" className="gap-1">
                <Clock className="h-3 w-3" />
                <FormattedMessage defaultMessage="Scheduled" id="Change plan item / Scheduled badge" />
              </Badge>
            )}
            {isFree && !isActive && (
              <Badge variant="muted">
                <FormattedMessage defaultMessage="Free" id="Change plan item / Free badge" />
              </Badge>
            )}
          </div>
        </div>

        <CardDescription className="mt-2">
          {isFree ? (
            <FormattedMessage defaultMessage="Get started with basic features" id="Change plan item / Free plan description" />
          ) : isPremium ? (
            <FormattedMessage defaultMessage="Best value for committed users" id="Change plan item / Premium plan description" />
          ) : (
            <FormattedMessage defaultMessage="Flexible monthly subscription" id="Change plan item / Monthly plan description" />
          )}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex items-baseline gap-1">
          {isFree ? (
            <span className="text-3xl font-bold text-muted-foreground">
              <FormattedMessage defaultMessage="Free" id="Change plan item / Free price" />
            </span>
          ) : (
            <>
              <span
                className={cn('text-4xl font-bold', {
                  'text-primary': isActive,
                  'text-amber-600 dark:text-amber-400': isPremium && !isActive,
                })}
              >
                {formatZar(plan.amount)}
              </span>
              <span className="text-muted-foreground text-sm">
                /{' '}
                {plan.interval === 'year' ? (
                  <FormattedMessage defaultMessage="year" id="Change plan item / year" />
                ) : (
                  <FormattedMessage defaultMessage="month" id="Change plan item / month" />
                )}
              </span>
            </>
          )}
        </div>

        {/* Stripe hard-codes 17%; PayFast prices come from settings, so the saving is calculated. */}
        {isPremium && yearlySavingsPercent !== null && (
          <Badge variant="success" className="text-xs">
            <FormattedMessage
              defaultMessage="Save {percent}% vs monthly"
              id="PayFast / Change plan item / Yearly savings"
              values={{ percent: yearlySavingsPercent }}
            />
          </Badge>
        )}

        {isTrialEligible && !isFree && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-950/50 border border-blue-200 dark:border-blue-800">
            <Clock className="h-4 w-4 text-blue-600 dark:text-blue-400 flex-shrink-0" />
            <span className="text-sm text-blue-700 dark:text-blue-300">
              <FormattedMessage defaultMessage="Start with a free trial" id="Change plan item / Trial eligible notice" />
            </span>
          </div>
        )}

        <Button
          onClick={handleSelect}
          disabled={isScheduledForNextPeriod || isFree || loading || isActive}
          variant={isActive ? 'outline' : 'default'}
          className={cn('w-full', {
            'bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 text-white border-0':
              isPremium && !isActive && !isScheduledForNextPeriod,
          })}
          size="lg"
        >
          {loading ? <FormattedMessage defaultMessage="Loading..." id="Change plan item / Loading" /> : getButtonText()}
        </Button>

        <div className="pt-4 border-t">
          <p className="text-sm font-medium mb-3 text-foreground">
            <FormattedMessage defaultMessage="Includes:" id="Change plan item / Features header" />
          </p>
          <ul className="space-y-2.5">
            {features.map((feature, index) => (
              <li key={[feature, index].join()} className="flex items-start gap-2">
                <div
                  className={cn('mt-0.5 rounded-full p-0.5', {
                    'bg-primary/10 text-primary': isActive,
                    'bg-amber-100 text-amber-600 dark:bg-amber-900/50 dark:text-amber-400': isPremium && !isActive,
                    'bg-blue-100 text-blue-600 dark:bg-blue-900/50 dark:text-blue-400': isMonthly && !isActive,
                    'bg-muted text-muted-foreground': isFree && !isActive,
                  })}
                >
                  <Check className="h-3.5 w-3.5" />
                </div>
                <span className="text-sm text-muted-foreground">{feature}</span>
              </li>
            ))}
          </ul>
        </div>
      </CardContent>
    </Card>
  );
};
