import { useQuery } from '@apollo/client/react';
import { PageLayout } from '@sb/webapp-core/components/pageLayout';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { RoutesConfig as CoreRoutesConfig } from '@sb/webapp-core/config/routes';
import { useToast } from '@sb/webapp-core/toast/useToast';
import { useGenerateTenantPath } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Helmet } from 'react-helmet-async';
import { FormattedMessage, useIntl } from 'react-intl';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { RoutesConfig } from '../../config/routes';
import { payfastCheckoutStatusQuery } from '../payfast.graphql';

// PayFast notifies our backend (the ITN) before it sends the buyer back here, but that notification
// can take a moment to be processed, so the page checks every 2 seconds for up to a minute.
const POLL_INTERVAL_MS = 2000;
const GIVE_UP_AFTER_MS = 60000;

/**
 * Where PayFast sends the buyer after paying (the checkout's return_url, with `m` = our checkout id
 * and `kind` = subscription or donation). Only the ITN confirms a payment, never this redirect, so
 * the page waits until the backend reports the checkout complete.
 */
export const PayfastReturn = () => {
  const intl = useIntl();
  const { toast } = useToast();
  const navigate = useNavigate();
  const generateTenantPath = useGenerateTenantPath();
  const { data: currentTenant } = useCurrentTenant();
  const [searchParams] = useSearchParams();
  const [timedOut, setTimedOut] = useState(false);
  const handled = useRef(false);

  const mPaymentId = searchParams.get('m') ?? '';
  const isDonation = searchParams.get('kind') === 'donation';
  const tenantId = currentTenant?.id ?? '';

  const { data, stopPolling } = useQuery(payfastCheckoutStatusQuery, {
    variables: { tenantId, mPaymentId },
    skip: !tenantId || !mPaymentId,
    pollInterval: POLL_INTERVAL_MS,
    fetchPolicy: 'network-only',
  });
  const isComplete = data?.payfastCheckoutStatus === 'complete';

  useEffect(() => {
    const timer = setTimeout(() => {
      stopPolling();
      setTimedOut(true);
    }, GIVE_UP_AFTER_MS);
    return () => clearTimeout(timer);
  }, [stopPolling]);

  useEffect(() => {
    if (!isComplete || handled.current) return;
    handled.current = true;
    stopPolling();
    toast({
      description: intl.formatMessage({ defaultMessage: 'Payment successful', id: 'PayFast / Return / Success' }),
      variant: 'success',
    });
    // Like the Stripe donation page, a donation goes home; a subscription shows its new plan.
    navigate(
      isDonation ? generateTenantPath(CoreRoutesConfig.home) : generateTenantPath(RoutesConfig.subscriptions.index),
      { replace: true }
    );
  }, [isComplete, isDonation, navigate, generateTenantPath, stopPolling, toast, intl]);

  return (
    <PageLayout>
      <Helmet title={intl.formatMessage({ defaultMessage: 'Payment', id: 'PayFast / Return / page title' })} />
      <div className="mx-auto w-full max-w-xl">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {!timedOut && <Loader2 className="h-5 w-5 animate-spin" />}
              {timedOut ? (
                <FormattedMessage defaultMessage="Still waiting for PayFast" id="PayFast / Return / Timed out title" />
              ) : (
                <FormattedMessage defaultMessage="Confirming your payment…" id="PayFast / Return / Waiting title" />
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Paragraph>
              {timedOut && isDonation ? (
                <FormattedMessage
                  defaultMessage="PayFast hasn't confirmed your donation yet. It will appear in your transaction history as soon as it does; you don't need to pay again."
                  id="PayFast / Return / Timed out donation description"
                />
              ) : timedOut ? (
                <FormattedMessage
                  defaultMessage="PayFast hasn't confirmed your payment yet. It will appear on your subscription page as soon as it does; you don't need to pay again."
                  id="PayFast / Return / Timed out description"
                />
              ) : (
                <FormattedMessage
                  defaultMessage="Please wait while PayFast confirms your payment. This usually takes a few seconds."
                  id="PayFast / Return / Waiting description"
                />
              )}
            </Paragraph>
            {timedOut &&
              (isDonation ? (
                <Link to={generateTenantPath(CoreRoutesConfig.home)} className="underline">
                  <FormattedMessage defaultMessage="Go to home" id="PayFast / Return / Go home" />
                </Link>
              ) : (
                <Link to={generateTenantPath(RoutesConfig.subscriptions.index)} className="underline">
                  <FormattedMessage defaultMessage="Go to my subscription" id="PayFast / Return / Go to subscription" />
                </Link>
              ))}
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
};

export default PayfastReturn;
