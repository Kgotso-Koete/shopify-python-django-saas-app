import { composeMockedQueryResult, mapRelayEdges } from '@sb/webapp-api-client/tests/utils';

import {
  payfastActiveSubscriptionQuery,
  payfastCardUpdateUrlQuery,
  payfastCheckoutStatusQuery,
  payfastDonationAmountsQuery,
  payfastPaymentsQuery,
  payfastSubscriptionPlansQuery,
  paymentConfigQuery,
} from '../payfast.graphql';

/** Apollo mocks for the PayFast GraphQL API, shaped like the backend's responses (apps/payfast/schema.py). */

export const fillPaymentConfigQuery = (backend: 'stripe' | 'payfast') =>
  composeMockedQueryResult(paymentConfigQuery, {
    data: {
      paymentConfig: {
        backend,
        currency: backend === 'payfast' ? 'ZAR' : 'USD',
        __typename: 'PaymentConfigType',
      },
    },
  });

export type PayfastSubscriptionMock = {
  plan: string;
  effectivePlan: string;
  pendingPlan: string | null;
  pendingAmount: string | null;
  status: string;
  amount: string;
  currentPeriodEnd: string | null;
  trialEnd: string | null;
  cancelAtPeriodEnd: boolean;
  canActivateTrial: boolean;
  hasCard: boolean;
};

export const freeSubscription: PayfastSubscriptionMock = {
  plan: 'free_plan',
  effectivePlan: 'free_plan',
  pendingPlan: null,
  pendingAmount: null,
  status: 'active',
  amount: '0.00',
  currentPeriodEnd: null,
  trialEnd: null,
  cancelAtPeriodEnd: false,
  canActivateTrial: true,
  hasCard: false,
};

export const monthlySubscription: PayfastSubscriptionMock = {
  plan: 'monthly_plan',
  effectivePlan: 'monthly_plan',
  pendingPlan: null,
  pendingAmount: null,
  status: 'active',
  amount: '199.00',
  currentPeriodEnd: '2099-01-31T10:00:00+00:00',
  trialEnd: null,
  cancelAtPeriodEnd: false,
  canActivateTrial: false,
  hasCard: true,
};

export const fillPayfastSubscriptionQuery = (subscription: Partial<PayfastSubscriptionMock>, tenantId = 'tenantId') =>
  composeMockedQueryResult(payfastActiveSubscriptionQuery, {
    variables: { tenantId },
    data: {
      payfastActiveSubscription: { ...freeSubscription, ...subscription, __typename: 'PayFastSubscriptionType' },
    },
  });

export const fillPayfastCardUpdateUrlQuery = (
  { hasCard, cardUpdateUrl }: { hasCard: boolean; cardUpdateUrl: string | null },
  returnPath: string,
  tenantId = 'tenantId'
) =>
  composeMockedQueryResult(payfastCardUpdateUrlQuery, {
    variables: { tenantId, returnPath },
    data: { payfastActiveSubscription: { hasCard, cardUpdateUrl, __typename: 'PayFastSubscriptionType' } },
  });

export const fillPayfastPlansQuery = () =>
  composeMockedQueryResult(payfastSubscriptionPlansQuery, {
    data: {
      payfastSubscriptionPlans: [
        { name: 'free_plan', amount: '0.00', currency: 'ZAR', interval: null, __typename: 'PayFastPlanType' },
        { name: 'monthly_plan', amount: '199.00', currency: 'ZAR', interval: 'month', __typename: 'PayFastPlanType' },
        { name: 'yearly_plan', amount: '1990.00', currency: 'ZAR', interval: 'year', __typename: 'PayFastPlanType' },
      ],
    },
  });

export const fillDonationAmountsQuery = () =>
  composeMockedQueryResult(payfastDonationAmountsQuery, {
    data: { payfastDonationAmounts: ['50.00', '100.00', '150.00'] },
  });

export const fillPayfastPaymentsQuery = (
  payments: Array<{ pfPaymentId: string; kind: string; plan: string; amountGross: string; createdAt: string }>,
  tenantId = 'tenantId'
) =>
  composeMockedQueryResult(payfastPaymentsQuery, {
    variables: { tenantId },
    data: {
      payfastPayments: mapRelayEdges(
        payments.map((payment) => ({ id: `id-${payment.pfPaymentId}`, itemName: '', ...payment })),
        'PayFastPaymentType'
      ),
    },
  });

export const fillCheckoutStatusQuery = (status: string | null, mPaymentId: string, tenantId = 'tenantId') =>
  composeMockedQueryResult(payfastCheckoutStatusQuery, {
    variables: { tenantId, mPaymentId },
    data: { payfastCheckoutStatus: status },
  });

export const checkoutResponse = {
  actionUrl: 'https://sandbox.payfast.co.za/eng/process',
  fields: { merchant_id: '10000100', amount: '0.00', signature: 'abc' },
  mPaymentId: 'm-123',
  __typename: 'PayFastCheckoutType',
};
