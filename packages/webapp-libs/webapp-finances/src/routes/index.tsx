import { asyncComponent } from '@sb/webapp-core/utils/asyncComponent';

import { withPaymentBackend } from '../payfast/paymentBackendSwitch.component';

// Each route renders the Stripe page or its PayFast counterpart, depending on the server's
// PAYMENT_BACKEND (see payfast/paymentBackendSwitch.component.tsx). The Stripe pages are unchanged.
export const PaymentConfirm = withPaymentBackend(
  asyncComponent(() => import('./paymentConfirm')),
  asyncComponent(() => import('../payfast/routes/paymentConfirm.component'))
);
export const Subscriptions = withPaymentBackend(
  asyncComponent(() => import('./subscriptions')),
  asyncComponent(() => import('../payfast/routes/subscriptions.component'))
);
export const EditSubscription = withPaymentBackend(
  asyncComponent(() => import('./editSubscription')),
  asyncComponent(() => import('../payfast/routes/editSubscription.component'))
);
// PayFast keeps the card itself, so its "edit payment method" is the payment method tab's link to PayFast.
export const EditPaymentMethod = withPaymentBackend(
  asyncComponent(() => import('./editPaymentMethod')),
  asyncComponent(() => import('../payfast/routes/paymentMethod.content'))
);
export const CancelSubscription = withPaymentBackend(
  asyncComponent(() => import('./cancelSubscription')),
  asyncComponent(() => import('../payfast/routes/cancelSubscription.component'))
);
export const TransactionHistory = withPaymentBackend(
  asyncComponent(() => import('./transactionHistory')),
  asyncComponent(() => import('../payfast/routes/transactionHistory.component'))
);
export const CurrentSubscriptionContent = withPaymentBackend(
  asyncComponent(() => import('./subscriptions/subscriptions.content')),
  asyncComponent(() => import('../payfast/routes/currentSubscription.content'))
);
export const PaymentMethodContent = withPaymentBackend(
  asyncComponent(() => import('./subscriptions/paymentMethod.content')),
  asyncComponent(() => import('../payfast/routes/paymentMethod.content'))
);
export const TransactionsHistoryContent = withPaymentBackend(
  asyncComponent(() => import('./subscriptions/transactionsHistory.content')),
  asyncComponent(() => import('../payfast/routes/transactionsHistory.content'))
);
// PayFast only: where PayFast sends the buyer back after paying.
export const PayfastReturn = asyncComponent(() => import('../payfast/routes/payfastReturn.component'));
