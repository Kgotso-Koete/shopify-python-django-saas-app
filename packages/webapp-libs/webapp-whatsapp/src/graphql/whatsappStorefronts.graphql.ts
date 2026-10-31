import { gql } from '@sb/webapp-api-client/graphql';

// Which Shopify store each external communications number sells from (WhatsApp plan Step 2.1b, user
// story 25), from apps/whatsapp_shop/schema.py. Reading each number's store needs whatsapp.view; the
// picker's list of stores and choosing one need whatsapp.manage. The connect form connects the number
// first, then chooses its store with chooseWhatsAppStore (Step 2.1b, decision 5). Each number's
// customers get menus or the AI assistant, set with setWhatsAppStorefrontMode (phase 2, decision 2).

export const whatsAppStorefrontsQuery = gql(/* GraphQL */ `
  query whatsAppStorefrontsQuery($tenantId: ID!) {
    whatsAppStorefronts(tenantId: $tenantId) {
      accountId
      shopDomain
      conversationMode
    }
  }
`);

export const whatsAppEligibleStoresQuery = gql(/* GraphQL */ `
  query whatsAppEligibleStoresQuery($tenantId: ID!) {
    whatsAppEligibleStores(tenantId: $tenantId)
  }
`);

export const chooseWhatsAppStoreMutation = gql(/* GraphQL */ `
  mutation chooseWhatsAppStoreMutation($input: ChooseWhatsAppStoreInput!) {
    chooseWhatsAppStore(input: $input) {
      storefront {
        accountId
        shopDomain
      }
    }
  }
`);

export const setWhatsAppStorefrontModeMutation = gql(/* GraphQL */ `
  mutation setWhatsAppStorefrontModeMutation($input: SetWhatsAppStorefrontModeInput!) {
    setWhatsAppStorefrontMode(input: $input) {
      storefront {
        accountId
        shopDomain
        conversationMode
      }
    }
  }
`);
