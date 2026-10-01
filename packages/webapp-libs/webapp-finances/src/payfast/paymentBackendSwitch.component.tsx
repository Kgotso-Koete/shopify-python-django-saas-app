import { ComponentType, ReactNode } from 'react';

import { usePaymentBackend } from './usePaymentBackend.hook';

export type PaymentBackendSwitchProps = {
  stripe: ReactNode;
  payfast: ReactNode;
};

/**
 * Renders `stripe` or `payfast` depending on the server's payment backend. Renders nothing until the
 * backend is known, so a Stripe page (and its Stripe queries) never mounts on a PayFast deployment.
 */
export const PaymentBackendSwitch = ({ stripe, payfast }: PaymentBackendSwitchProps) => {
  const backend = usePaymentBackend();

  if (!backend) return null;
  return <>{backend === 'payfast' ? payfast : stripe}</>;
};

/**
 * Wrap a Stripe route component and its PayFast counterpart into one component with the same name,
 * so the app's route definitions don't need to know which backend is active.
 */
export const withPaymentBackend = <P extends object>(Stripe: ComponentType<P>, Payfast: ComponentType<P>) => {
  const PaymentBackendRoute = (props: P) => (
    <PaymentBackendSwitch stripe={<Stripe {...props} />} payfast={<Payfast {...props} />} />
  );
  return PaymentBackendRoute;
};
