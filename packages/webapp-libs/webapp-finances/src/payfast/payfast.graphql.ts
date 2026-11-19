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

// The organization's invoices (WhatsApp plan phase 4, Step 4.5a): each matched to its payment's row in the
// transaction history by paymentId, for billing.view. The PDF itself is fetched from /api/invoicing/<id>/pdf/.
export const payfastInvoicesQuery = gql(/* GraphQL */ `
  query payfastInvoicesQuery($tenantId: ID!) {
    invoices(tenantId: $tenantId) {
      id
      number
      paymentId
    }
  }
`);

// The organization's billing email (WhatsApp plan, user story WA.D6.OM.J1.A1), which PayFast bills: empty means
// the organization's creator's. Any member can read it; the web app's current-tenant query doesn't select it.
export const payfastTenantBillingEmailQuery = gql(/* GraphQL */ `
  query payfastTenantBillingEmailQuery($id: ID!) {
    tenant(id: $id) {
      id
      billingEmail
    }
  }
`);

// Saves it through upstream's updateTenant mutation (org.settings.edit), which needs the name too; asking for
// billingEmail back lets Apollo's cache update the card above.
export const payfastUpdateBillingEmailMutation = gql(/* GraphQL */ `
  mutation payfastUpdateBillingEmailMutation($input: UpdateTenantMutationInput!) {
    updateTenant(input: $input) {
      tenant {
        id
        name
        billingEmail
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
