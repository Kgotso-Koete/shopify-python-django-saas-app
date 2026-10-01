import { screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';

import { render } from '../../tests/utils/rendering';
import { PayfastSubscriptionPlanItem, PayfastSubscriptionPlanItemProps } from '../routes/subscriptionPlanItem.component';
import { freeSubscription, monthlySubscription } from '../tests/fixtures';

// Mirrors the Stripe plan card's spec (routes/editSubscription/subscriptionPlanItem/__tests__): the
// PayFast card has the same layout and states, fed by PayFast data.
const freePlan = { name: 'free_plan', amount: '0.00', interval: null };
const monthlyPlan = { name: 'monthly_plan', amount: '199.00', interval: 'month' };
const yearlyPlan = { name: 'yearly_plan', amount: '1990.00', interval: 'year' };

const renderItem = (props: Partial<PayfastSubscriptionPlanItemProps>) =>
  render(
    <PayfastSubscriptionPlanItem
      plan={monthlyPlan}
      subscription={freeSubscription}
      yearlySavingsPercent={17}
      onSelect={jest.fn()}
      loading={false}
      {...props}
    />
  );

describe('PayFast SubscriptionPlanItem', () => {
  describe('should render without errors', () => {
    it('should render name', async () => {
      renderItem({});

      expect(await screen.findByText('Monthly')).toBeInTheDocument();
    });

    it('should render the ZAR plan price and interval', async () => {
      renderItem({});

      expect(await screen.findByText(/199\.00/)).toBeInTheDocument();
      expect(screen.getByText(/^\/\s*month$/)).toBeInTheDocument();
    });

    it('should render the features list', async () => {
      renderItem({});

      expect(await screen.findByText(/includes:/i)).toBeInTheDocument();
      expect(screen.getAllByText('Lorem ipsum dolor sit amet')).toHaveLength(5);
    });
  });

  describe('button is clicked', () => {
    it('should call onSelect with the plan name for another plan', async () => {
      const onSelect = jest.fn();
      renderItem({ onSelect, subscription: monthlySubscription, plan: yearlyPlan });

      await userEvent.click(await screen.findByRole('button', { name: /select plan/i }));

      expect(onSelect).toHaveBeenCalledWith('yearly_plan');
    });

    it('should not call onSelect for the current plan', async () => {
      const onSelect = jest.fn();
      renderItem({ onSelect, subscription: monthlySubscription, plan: monthlyPlan });

      const button = await screen.findByRole('button', { name: /current plan/i });
      expect(button).toBeDisabled();
      expect(screen.getByText('Active')).toBeInTheDocument();
      await userEvent.click(button);
      expect(onSelect).not.toHaveBeenCalled();
    });

    it('should not call onSelect for a plan already scheduled for the next period', async () => {
      const onSelect = jest.fn();
      renderItem({ onSelect, subscription: { ...monthlySubscription, pendingPlan: 'yearly_plan' }, plan: yearlyPlan });

      const button = await screen.findByRole('button', { name: /scheduled/i });
      expect(button).toBeDisabled();
    });
  });

  describe('free plan', () => {
    it('is the active, current plan of a free organisation', async () => {
      renderItem({ plan: freePlan, subscription: freeSubscription });

      expect(await screen.findByRole('button', { name: /current plan/i })).toBeDisabled();
      expect(screen.getByText('Active')).toBeInTheDocument();
      expect(screen.getByText(/get started with basic features/i)).toBeInTheDocument();
    });

    it('cannot be selected by a paying organisation (they cancel instead), as on Stripe', async () => {
      renderItem({ plan: freePlan, subscription: monthlySubscription });

      expect(await screen.findByRole('button', { name: /free plan/i })).toBeDisabled();
    });

    it('is scheduled for the next period after cancelling', async () => {
      renderItem({ plan: freePlan, subscription: { ...monthlySubscription, cancelAtPeriodEnd: true } });

      expect(await screen.findAllByText(/scheduled/i)).not.toHaveLength(0);
    });
  });

  describe('yearly plan', () => {
    it('shows the best value ribbon and the savings', async () => {
      renderItem({ plan: yearlyPlan });

      expect(await screen.findByText(/best value$/i)).toBeInTheDocument();
      expect(screen.getByText(/save 17% vs monthly/i)).toBeInTheDocument();
    });

    it('hides the savings badge when there is no saving', async () => {
      renderItem({ plan: yearlyPlan, yearlySavingsPercent: null });

      expect(await screen.findByText('Yearly')).toBeInTheDocument();
      expect(screen.queryByText(/vs monthly/i)).not.toBeInTheDocument();
    });
  });

  describe('free trial notice', () => {
    it('shows on paid plans for a free organisation that has not used its trial', async () => {
      renderItem({ plan: monthlyPlan, subscription: freeSubscription });

      expect(await screen.findByText(/start with a free trial/i)).toBeInTheDocument();
    });

    it('does not show for a paying organisation, because a PayFast plan change has no trial', async () => {
      renderItem({ plan: yearlyPlan, subscription: { ...monthlySubscription, canActivateTrial: true } });

      expect(await screen.findByText('Yearly')).toBeInTheDocument();
      expect(screen.queryByText(/start with a free trial/i)).not.toBeInTheDocument();
    });

    it('does not show on the free plan', async () => {
      renderItem({ plan: freePlan, subscription: freeSubscription });

      expect(await screen.findByText(/get started with basic features/i)).toBeInTheDocument();
      expect(screen.queryByText(/start with a free trial/i)).not.toBeInTheDocument();
    });
  });

  it('shows loading on the button while a change is in progress', async () => {
    renderItem({ loading: true });

    expect(await screen.findByRole('button', { name: /loading/i })).toBeDisabled();
  });
});
