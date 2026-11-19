import { gql } from '@sb/webapp-api-client/graphql';

// The logged-in user's own WhatsApp links (WhatsApp plan Steps 1.7c, 1.14 and 1.17, user stories WA.D1.OM.J1.A2
// and WA.D2.OM.J1.A1): one per organization of theirs with an internal communications number. Only ever the user's
// own: no field names a user, and each names the organization by its id. Since phase 7 (user story WA.D1.OM.J1.A3)
// the code can instead be sent to the phone from the team number and typed here (confirmWhatsAppLink); a phone
// that hasn't written to the team number yet waits, linked once it does.

export const whatsAppLinksQuery = gql(/* GraphQL */ `
  query whatsAppLinksQuery {
    whatsAppLinks {
      tenantId
      organizationName
      internalNumber
      linked
      waiting
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
      channel
    }
  }
`);

export const confirmWhatsAppLinkMutation = gql(/* GraphQL */ `
  mutation confirmWhatsAppLinkMutation($input: ConfirmWhatsAppLinkInput!) {
    confirmWhatsAppLink(input: $input) {
      waiting
      link {
        tenantId
        organizationName
        internalNumber
        linked
        waiting
        maskedNumber
        conversationMode
        linkedAt
      }
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
        waiting
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
        waiting
        maskedNumber
        conversationMode
        linkedAt
      }
    }
  }
`);
