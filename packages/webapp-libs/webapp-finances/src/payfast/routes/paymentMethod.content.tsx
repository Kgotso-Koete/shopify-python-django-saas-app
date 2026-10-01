import { useQuery } from '@apollo/client/react';
import { ButtonVariant } from '@sb/webapp-core/components/buttons';
import { buttonVariants } from '@sb/webapp-core/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { useGenerateTenantPath, usePermissionCheck } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { CreditCard, Wallet } from 'lucide-react';
import { FormattedMessage } from 'react-intl';

import { RoutesConfig } from '../../config/routes';
import { payfastCardUpdateUrlQuery } from '../payfast.graphql';

/**
 * PayFast counterpart of routes/subscriptions/paymentMethod.content.tsx: the same tab and layout.
 * PayFast holds the card, so instead of card details and an "Edit payment methods" page, the tab
 * links to PayFast's own card update page (https://developers.payfast.co.za/docs#recurring_card_update),
 * which sends the buyer back here.
 */
export const PayfastPaymentMethodContent = () => {
  const { data: currentTenant } = useCurrentTenant();
  const generateTenantPath = useGenerateTenantPath();
  const { hasPermission: canManageBilling } = usePermissionCheck('billing.manage');
  const tenantId = currentTenant?.id ?? '';

  const { data } = useQuery(payfastCardUpdateUrlQuery, {
    variables: { tenantId, returnPath: generateTenantPath(RoutesConfig.subscriptions.paymentMethods.index) },
    skip: !tenantId,
  });
  const subscription = data?.payfastActiveSubscription;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CreditCard className="h-5 w-5" />
            <FormattedMessage defaultMessage="Payment methods" id="My subscription / Payment methods header" />
          </CardTitle>
          <CardDescription>
            <FormattedMessage
              defaultMessage="Manage your payment methods in application"
              id="My subscription / Payment methods subheader"
            />
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {subscription?.hasCard && (
            <Card>
              <CardHeader>
                <CardTitle>
                  <FormattedMessage defaultMessage="Current method:" id="My subscription / Current method" />
                </CardTitle>
                <CardDescription>
                  <FormattedMessage defaultMessage="Credit card" id="My subscription / Credit card" />
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="p-2 border rounded-md bg-secondary text-sm">
                  <FormattedMessage
                    defaultMessage="Your card is stored securely by PayFast."
                    id="PayFast / Payment method / Card on file"
                  />
                </div>
              </CardContent>
            </Card>
          )}

          {subscription && !subscription.hasCard && (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <div className="rounded-full bg-muted p-4 mb-4">
                <Wallet className="h-8 w-8 text-muted-foreground" />
              </div>
              <h3 className="text-lg font-medium mb-2">
                <FormattedMessage defaultMessage="No payment methods" id="My subscription / No payment methods title" />
              </h3>
              <p className="text-sm text-muted-foreground max-w-sm">
                <FormattedMessage
                  defaultMessage="You don't have a card on file. A card is added when you subscribe to a paid plan."
                  id="PayFast / Payment method / No card"
                />
              </p>
            </div>
          )}

          {canManageBilling && subscription?.hasCard && subscription.cardUpdateUrl && (
            <div>
              <a href={subscription.cardUpdateUrl} className={buttonVariants({ variant: ButtonVariant.PRIMARY })}>
                <FormattedMessage defaultMessage="Update card" id="PayFast / Payment method / Update card" />
              </a>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default PayfastPaymentMethodContent;
