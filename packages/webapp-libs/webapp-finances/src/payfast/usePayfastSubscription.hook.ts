import { useQuery } from '@apollo/client/react';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';

import { payfastActiveSubscriptionQuery } from './payfast.graphql';

/** The current tenant's PayFast subscription (plan, status, dates), and the tenant id for mutations. */
export const usePayfastSubscription = () => {
  const { data: currentTenant } = useCurrentTenant();
  const tenantId = currentTenant?.id ?? '';

  const { data, loading } = useQuery(payfastActiveSubscriptionQuery, {
    variables: { tenantId },
    skip: !tenantId,
    fetchPolicy: 'cache-and-network',
  });

  const subscription = data?.payfastActiveSubscription ?? null;
  const isPaid = Boolean(subscription && subscription.effectivePlan !== 'free_plan');

  return { subscription, isPaid, loading, tenantId };
};
