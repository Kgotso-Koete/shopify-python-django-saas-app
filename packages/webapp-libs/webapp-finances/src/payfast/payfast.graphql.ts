import { gql } from '@sb/webapp-api-client/graphql';

/**
 * GraphQL documents for PayFast billing (backend: packages/backend/apps/payfast/schema.py).
 * They are always in the schema; the server only acts on them when PAYMENT_BACKEND=payfast.
 */

export const paymentConfigQuery = gql(/* GraphQL */ `
  query paymentConfigQuery {
    paymentConfig {
      backend
      currency
    }
  }
`);

export const payfastActiveSubscriptionQuery = gql(/* GraphQL */ `
  query payfastActiveSubscriptionQuery($tenantId: ID!) {
    payfastActiveSubscription(tenantId: $tenantId) {
      plan
      effectivePlan
      pendingPlan
      pendingAmount
      status
      amount
      currentPeriodEnd
      trialEnd
      cancelAtPeriodEnd
      canActivateTrial
      hasCard
    }
  }
`);

export const payfastCardUpdateUrlQuery = gql(/* GraphQL */ `
  query payfastCardUpdateUrlQuery($tenantId: ID!, $returnPath: String) {
    payfastActiveSubscription(tenantId: $tenantId) {
      hasCard
      cardUpdateUrl(returnPath: $returnPath)
    }
  }
`);

export const payfastSubscriptionPlansQuery = gql(/* GraphQL */ `
  query payfastSubscriptionPlansQuery {
    payfastSubscriptionPlans {
      name
      amount
      currency
      interval
    }
  }
`);

export const payfastDonationAmountsQuery = gql(/* GraphQL */ `
  query payfastDonationAmountsQuery {
    payfastDonationAmounts
  }
`);

export const payfastPaymentsQuery = gql(/* GraphQL */ `
  query payfastPaymentsQuery($tenantId: ID!) {
    payfastPayments(tenantId: $tenantId) {
      edges {
        node {
          id
          pfPaymentId
          kind
          plan
          amountGross
          itemName
          createdAt
        }
      }
    }
  }
`);

export const payfastCheckoutStatusQuery = gql(/* GraphQL */ `
  query payfastCheckoutStatusQuery($tenantId: ID!, $mPaymentId: ID!) {
    payfastCheckoutStatus(tenantId: $tenantId, mPaymentId: $mPaymentId)
  }
`);

export const payfastCreateCheckoutMutation = gql(/* GraphQL */ `
  mutation payfastCreateCheckoutMutation($input: PayFastCreateCheckoutMutationInput!) {
    payfastCreateCheckout(input: $input) {
      checkout {
        actionUrl
        fields
        mPaymentId
      }
    }
  }
`);

export const payfastCreateDonationCheckoutMutation = gql(/* GraphQL */ `
  mutation payfastCreateDonationCheckoutMutation($input: PayFastCreateDonationCheckoutMutationInput!) {
    payfastCreateDonationCheckout(input: $input) {
      checkout {
        actionUrl
        fields
        mPaymentId
      }
    }
  }
`);

export const payfastCancelSubscriptionMutation = gql(/* GraphQL */ `
  mutation payfastCancelSubscriptionMutation($input: PayFastCancelSubscriptionMutationInput!) {
    payfastCancelSubscription(input: $input) {
      activeSubscription {
        plan
        effectivePlan
        pendingPlan
        status
        amount
        currentPeriodEnd
        trialEnd
        cancelAtPeriodEnd
        canActivateTrial
        hasCard
      }
    }
  }
`);
