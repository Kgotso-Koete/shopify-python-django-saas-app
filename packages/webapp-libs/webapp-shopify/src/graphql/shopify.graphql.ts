import { gql } from '@sb/webapp-api-client/graphql';

export const shopifyConfigQuery = gql(/* GraphQL */ `
  query shopifyConfigQuery {
    shopifyConfig {
      enabled
    }
  }
`);

export const shopifyShopsQuery = gql(/* GraphQL */ `
  query shopifyShopsQuery($tenantId: ID!) {
    shopifyShops(tenantId: $tenantId) {
      shopDomain
      scopes
      installedAt
      uninstalledAt
      needsReinstall
    }
  }
`);

export const shopifyClaimQuery = gql(/* GraphQL */ `
  query shopifyClaimQuery($claim: String!) {
    shopifyClaim(claim: $claim) {
      shopDomain
    }
  }
`);

export const shopifyStartInstallMutation = gql(/* GraphQL */ `
  mutation shopifyStartInstallMutation($input: ShopifyStartInstallInput!) {
    shopifyStartInstall(input: $input) {
      authorizeUrl
    }
  }
`);

export const shopifyLinkShopMutation = gql(/* GraphQL */ `
  mutation shopifyLinkShopMutation($input: ShopifyLinkShopInput!) {
    shopifyLinkShop(input: $input) {
      shop {
        shopDomain
        scopes
        installedAt
      }
    }
  }
`);

export const shopifyDisconnectShopMutation = gql(/* GraphQL */ `
  mutation shopifyDisconnectShopMutation($input: ShopifyDisconnectShopInput!) {
    shopifyDisconnectShop(input: $input) {
      ok
    }
  }
`);
