import { useQuery } from '@apollo/client/react';
import { gql } from '@sb/webapp-api-client/graphql';
import { useCallback } from 'react';

import { useCurrentTenant } from '../../providers';

/**
 * Which features the current organization's plan unlocks (WhatsApp plan phase 3, decision 8), from
 * apps/entitlements/schema.py: only feature names, such as ["SHOPIFY", "WHATSAPP"], so any member may
 * read it, a Member included, without seeing what the organization pays.
 */
export const organizationFeaturesQuery = gql(/* GraphQL */ `
  query organizationFeaturesQuery($tenantId: ID!) {
    organizationFeatures(tenantId: $tenantId)
  }
`);

export type OrganizationFeature = 'SHOPIFY' | 'WHATSAPP';

/**
 * Whether a feature is unlocked for the current organization, to show its page working or read-only
 * (decision 5). It's for display only: the backend checks every action itself, so while the answer is
 * loading, or if it can't be loaded, a feature counts as unlocked rather than locking a page by mistake.
 *
 * @example
 * const { isUnlocked } = useOrganizationFeatures();
 * const canChange = canManage && isUnlocked('WHATSAPP');
 */
export const useOrganizationFeatures = () => {
  const { data: currentTenant } = useCurrentTenant();
  const tenantId = currentTenant?.id ?? '';
  const { data, loading } = useQuery(organizationFeaturesQuery, {
    variables: { tenantId },
    skip: !tenantId,
  });
  const features = data?.organizationFeatures;

  const isUnlocked = useCallback(
    (feature: OrganizationFeature) => (features ? features.includes(feature) : true),
    [features]
  );

  return { isUnlocked, loading };
};
