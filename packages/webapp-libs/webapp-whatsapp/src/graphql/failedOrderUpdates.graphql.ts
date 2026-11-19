import { gql } from '@sb/webapp-api-client/graphql';

// The order updates WhatsApp couldn't deliver, and sending one again (WhatsApp plan Step 4.7, user story
// WA.D3.OM.J2.A3), from apps/whatsapp_shop/schema.py. Listing needs whatsapp.view; Send again needs
// whatsapp.manage, and asks Shopify for the order to build the update fresh (decided 2026-11-08).

export const whatsAppFailedOrderUpdatesQuery = gql(/* GraphQL */ `
  query whatsAppFailedOrderUpdatesQuery($tenantId: ID!) {
    whatsAppFailedOrderUpdates(tenantId: $tenantId) {
      checkoutId
      stage
      accountId
      number
      customer
      failedAt
      errorCode
      reason
    }
  }
`);

export const sendWhatsAppOrderUpdateAgainMutation = gql(/* GraphQL */ `
  mutation sendWhatsAppOrderUpdateAgainMutation($input: SendWhatsAppOrderUpdateAgainInput!) {
    sendWhatsAppOrderUpdateAgain(input: $input) {
      checkoutId
      stage
    }
  }
`);
