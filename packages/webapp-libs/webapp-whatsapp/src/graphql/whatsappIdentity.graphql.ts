import { gql } from '@sb/webapp-api-client/graphql';

// The logged-in user's own WhatsApp links (WhatsApp plan Steps 1.7c, 1.14 and 1.17, user stories 1
// and 3): one per organization of theirs with an internal communications number. Only ever the user's
// own: no field names a user, and each names the organization by its id.

export const whatsAppLinksQuery = gql(/* GraphQL */ `
  query whatsAppLinksQuery {
    whatsAppLinks {
      tenantId
      organizationName
      internalNumber
      linked
      maskedNumber
      conversationMode
      linkedAt
    }
  }
`);

export const startWhatsAppLinkMutation = gql(/* GraphQL */ `
  mutation startWhatsAppLinkMutation($input: StartWhatsAppLinkInput!) {
    startWhatsAppLink(input: $input) {
      code
      link
      maskedNumber
      expiresAt
    }
  }
`);

export const updateWhatsAppConversationModeMutation = gql(/* GraphQL */ `
  mutation updateWhatsAppConversationModeMutation($input: UpdateWhatsAppConversationModeInput!) {
    updateWhatsAppConversationMode(input: $input) {
      link {
        tenantId
        organizationName
        internalNumber
        linked
        maskedNumber
        conversationMode
        linkedAt
      }
    }
  }
`);

export const disconnectWhatsAppMutation = gql(/* GraphQL */ `
  mutation disconnectWhatsAppMutation($input: DisconnectWhatsAppInput!) {
    disconnectWhatsApp(input: $input) {
      link {
        tenantId
        organizationName
        internalNumber
        linked
        maskedNumber
        conversationMode
        linkedAt
      }
    }
  }
`);
