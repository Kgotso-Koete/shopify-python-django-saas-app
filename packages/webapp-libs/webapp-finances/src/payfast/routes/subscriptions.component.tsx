import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Tabs, TabsList, TabsTrigger } from '@sb/webapp-core/components/ui/tabs';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { CreditCard } from 'lucide-react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { Link, Outlet, useLocation } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';

/**
 * PayFast counterpart of routes/subscriptions/currentSubscription.component.tsx: the subscription
 * page with its three tabs. Unlike the Stripe layout it loads no Stripe data; each PayFast tab
 * queries what it needs.
 */
export const PayfastSubscriptions = () => {
  const intl = useIntl();
  const location = useLocation();
  const generateTenantPath = useGenerateTenantPath();

  const tabs = [
    {
      path: generateTenantPath(RoutesConfig.subscriptions.index),
      label: <FormattedMessage defaultMessage="Current subscription" id="PayFast / My subscription / Current tab" />,
    },
    {
      path: generateTenantPath(RoutesConfig.subscriptions.paymentMethods.index),
      label: <FormattedMessage defaultMessage="Payment methods" id="PayFast / My subscription / Payment methods tab" />,
    },
    {
      path: generateTenantPath(RoutesConfig.subscriptions.transactionHistory.index),
      label: <FormattedMessage defaultMessage="Transaction history" id="PayFast / My subscription / History tab" />,
    },
  ];

  return (
    <PageLayout>
      <Helmet
        title={intl.formatMessage({ defaultMessage: 'Subscription plan', id: 'PayFast / My subscription / page title' })}
      />

      <div className="mx-auto w-full max-w-5xl space-y-8">
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <CreditCard className="h-6 w-6 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">
              <FormattedMessage defaultMessage="Subscription plan" id="PayFast / My subscription / Heading" />
            </h1>
          </div>
          <Paragraph className="text-lg text-muted-foreground">
            <FormattedMessage
              defaultMessage="An example of a subscription management page powered by PayFast. You can select a subscription plan, update your card, and view payment history."
              id="PayFast / My subscription / Subheading"
            />
          </Paragraph>
        </div>

        <Tabs value={location.pathname} className="space-y-6">
          <TabsList className="flex flex-col gap-2 sm:flex-row sm:gap-2 h-full sm:h-10 sm:w-fit w-full">
            {tabs.map((tab) => (
              <Link key={tab.path} to={tab.path} replace>
                <TabsTrigger value={tab.path}>{tab.label}</TabsTrigger>
              </Link>
            ))}
          </TabsList>

          <div className="mt-6">
            <Outlet />
          </div>
        </Tabs>
      </div>
    </PageLayout>
  );
};

export default PayfastSubscriptions;
