import { nestedPath } from '@sb/webapp-core/utils';

export const RoutesConfig = {
  finances: nestedPath('finances', {
    paymentConfirm: 'payment-confirm',
    // Where PayFast sends the buyer back after paying (PayFast checkouts only).
    payfastReturn: 'payfast-return',
  }),
  subscriptions: nestedPath('subscriptions', {
    currentSubscription: nestedPath('current-subscription', {
      edit: 'edit',
      cancel: 'cancel',
    }),
    paymentMethods: nestedPath('payment-methods', {
      edit: 'edit',
    }),
    transactionHistory: nestedPath('transaction-history', {
      history: 'history',
    }),
  }),
};
