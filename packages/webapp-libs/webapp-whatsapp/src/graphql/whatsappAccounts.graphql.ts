import { gql } from '@sb/webapp-api-client/graphql';

// The organization's WhatsApp numbers (WhatsApp plan Steps 1.5 and 1.17, user story 11), each with
// its purpose: the internal communications number its team texts, or an external communications
// number its store customers text. Every number is on our one Meta app (Step 1.18), so connecting
// takes no App secret. Reading needs whatsapp.view; connecting, testing and disconnecting need
// whatsapp.manage.

export const whatsAppAccountsQuery = gql(/* GraphQL */ `
  query whatsAppAccountsQuery($tenantId: ID!) {
    whatsAppAccounts(tenantId: $tenantId) {
      id
      purpose
      phoneNumberId
      wabaId
      displayPhoneNumber
      verifiedName
      connectionMethod
      isActive
      credentialsVerifiedAt
      subscribedAt
      lastMessageReceivedAt
    }
  }
`);

export const connectWhatsAppAccountMutation = gql(/* GraphQL */ `
  mutation connectWhatsAppAccountMutation($input: ConnectWhatsAppAccountInput!) {
    connectWhatsAppAccount(input: $input) {
      account {
        id
        purpose
        displayPhoneNumber
        verifiedName
        subscribedAt
      }
    }
  }
`);

export const sendWhatsAppTestMessageMutation = gql(/* GraphQL */ `
  mutation sendWhatsAppTestMessageMutation($input: SendWhatsAppTestMessageInput!) {
    sendWhatsAppTestMessage(input: $input) {
      messageId
    }
  }
`);

export const disconnectWhatsAppAccountMutation = gql(/* GraphQL */ `
  mutation disconnectWhatsAppAccountMutation($input: DisconnectWhatsAppAccountInput!) {
    disconnectWhatsAppAccount(input: $input) {
      account {
        id
        isActive
      }
    }
  }
`);

// Whom a connected number serves: the team, the customers, or both (WhatsApp plan Step 2.7). It keeps
// its credentials and history; leaving the team unlinks its members. Needs whatsapp.manage.
export const changeWhatsAppNumberPurposeMutation = gql(/* GraphQL */ `
  mutation changeWhatsAppNumberPurposeMutation($input: ChangeWhatsAppNumberPurposeInput!) {
    changeWhatsAppNumberPurpose(input: $input) {
      account {
        id
        purpose
      }
    }
  }
`);
