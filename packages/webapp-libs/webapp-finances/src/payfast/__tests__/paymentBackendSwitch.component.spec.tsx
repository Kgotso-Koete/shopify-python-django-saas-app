import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { screen } from '@testing-library/react';
import { GraphQLError } from 'graphql';

import { render } from '../../tests/utils/rendering';
import { paymentConfigQuery } from '../payfast.graphql';
import { PaymentBackendSwitch } from '../paymentBackendSwitch.component';
import { fillPaymentConfigQuery } from '../tests/fixtures';

// The web app asks the server which payment backend it uses (paymentConfig), so one build of the
// web app works with either PAYMENT_BACKEND setting.
describe('PaymentBackendSwitch', () => {
  const Component = () => <PaymentBackendSwitch stripe={<span>stripe page</span>} payfast={<span>payfast page</span>} />;

  it('renders the Stripe element when the backend is Stripe', async () => {
    render(<Component />, { apolloMocks: [fillPaymentConfigQuery('stripe')] });

    expect(await screen.findByText('stripe page')).toBeInTheDocument();
    expect(screen.queryByText('payfast page')).not.toBeInTheDocument();
  });

  it('renders the PayFast element when the backend is PayFast', async () => {
    render(<Component />, { apolloMocks: [fillPaymentConfigQuery('payfast')] });

    expect(await screen.findByText('payfast page')).toBeInTheDocument();
    expect(screen.queryByText('stripe page')).not.toBeInTheDocument();
  });

  it('falls back to the Stripe element when the query fails, as the Stripe page tests expect', async () => {
    const failingMock = composeMockedQueryResult(paymentConfigQuery, {
      data: { paymentConfig: null },
      errors: [new GraphQLError('Server error')],
    });
    render(<Component />, { apolloMocks: [failingMock] });

    expect(await screen.findByText('stripe page')).toBeInTheDocument();
    expect(screen.queryByText('payfast page')).not.toBeInTheDocument();
  });

  it('renders nothing until the backend is known, so no Stripe query runs on a PayFast deployment', () => {
    render(<Component />, { apolloMocks: [fillPaymentConfigQuery('payfast')] });

    expect(screen.queryByText('stripe page')).not.toBeInTheDocument();
    expect(screen.queryByText('payfast page')).not.toBeInTheDocument();
  });
});
