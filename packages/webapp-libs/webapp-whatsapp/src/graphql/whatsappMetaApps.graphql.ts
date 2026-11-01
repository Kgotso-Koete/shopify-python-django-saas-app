import { gql } from '@sb/webapp-api-client/graphql';

// The organization's own Meta apps (WhatsApp plan Step 2.9): each registered once, with the webhook
// address and verify token the service made for it, to paste into the app's webhook settings in Meta's
// App Dashboard. The App secret never comes back. Everything here needs whatsapp.manage.

export const whatsAppMetaAppsQuery = gql(/* GraphQL */ `
  query whatsAppMetaAppsQuery($tenantId: ID!) {
    whatsAppMetaApps(tenantId: $tenantId) {
      id
      appId
      webhookUrl
      verifyToken
      createdAt
    }
  }
`);

export const registerWhatsAppMetaAppMutation = gql(/* GraphQL */ `
  mutation registerWhatsAppMetaAppMutation($input: RegisterWhatsAppMetaAppInput!) {
    registerWhatsAppMetaApp(input: $input) {
      metaApp {
        id
        appId
        webhookUrl
        verifyToken
        createdAt
      }
    }
  }
`);

export const updateWhatsAppMetaAppSecretMutation = gql(/* GraphQL */ `
  mutation updateWhatsAppMetaAppSecretMutation($input: UpdateWhatsAppMetaAppSecretInput!) {
    updateWhatsAppMetaAppSecret(input: $input) {
      metaApp {
        id
      }
    }
  }
`);

export const regenerateWhatsAppMetaAppVerifyTokenMutation = gql(/* GraphQL */ `
  mutation regenerateWhatsAppMetaAppVerifyTokenMutation($input: RegenerateWhatsAppMetaAppVerifyTokenInput!) {
    regenerateWhatsAppMetaAppVerifyToken(input: $input) {
      metaApp {
        id
        verifyToken
      }
    }
  }
`);

export const removeWhatsAppMetaAppMutation = gql(/* GraphQL */ `
  mutation removeWhatsAppMetaAppMutation($input: RemoveWhatsAppMetaAppInput!) {
    removeWhatsAppMetaApp(input: $input) {
      ok
    }
  }
`);

// The app a connected number is in, changed without reconnecting it (decision 5); a null metaAppId puts
// it back on this service's app.
export const setWhatsAppNumberMetaAppMutation = gql(/* GraphQL */ `
  mutation setWhatsAppNumberMetaAppMutation($input: SetWhatsAppNumberMetaAppInput!) {
    setWhatsAppNumberMetaApp(input: $input) {
      account {
        id
        metaAppId
      }
    }
  }
`);
