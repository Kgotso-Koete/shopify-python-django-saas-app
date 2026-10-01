import { useQuery } from '@apollo/client/react';

import { paymentConfigQuery } from './payfast.graphql';

export type PaymentBackend = 'stripe' | 'payfast';

/**
 * Which payment backend the server uses (PAYMENT_BACKEND on the backend), or undefined while loading.
 * Read at runtime instead of from a build-time env var, so one web app build works with either
 * backend and can never disagree with the server. The server always answers (with "payfast" by
 * default). Only if the request itself fails does this fall back to Stripe, the boilerplate's original
 * behaviour, which the boilerplate's Stripe page tests rely on (they don't mock paymentConfig).
 */
export const usePaymentBackend = (): PaymentBackend | undefined => {
  const { data, error } = useQuery(paymentConfigQuery, { fetchPolicy: 'cache-first' });

  if (error) return 'stripe';
  if (!data) return undefined;
  return data.paymentConfig.backend === 'payfast' ? 'payfast' : 'stripe';
};
