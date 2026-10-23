import { gql } from '@sb/webapp-api-client/graphql';

// The number troubleshooting tools (WhatsApp plan D18, Steps 1.5b and 1.6b, user story 23). Every one,
// Meta's status included, needs whatsapp.manage, and every repair is written to the action log.

export const whatsAppNumberStatusQuery = gql(/* GraphQL */ `
  query whatsAppNumberStatusQuery($tenantId: ID!, $accountId: ID!) {
    whatsAppNumberStatus(tenantId: $tenantId, accountId: $accountId) {
      status
      codeVerificationStatus
      qualityRating
      nameStatus
      verifiedName
      displayPhoneNumber
    }
  }
`);

export const requestWhatsAppVerificationCodeMutation = gql(/* GraphQL */ `
  mutation requestWhatsAppVerificationCodeMutation($input: RequestWhatsAppVerificationCodeInput!) {
    requestWhatsAppVerificationCode(input: $input) {
      ok
    }
  }
`);

export const verifyWhatsAppNumberMutation = gql(/* GraphQL */ `
  mutation verifyWhatsAppNumberMutation($input: VerifyWhatsAppNumberInput!) {
    verifyWhatsAppNumber(input: $input) {
      ok
    }
  }
`);

export const registerWhatsAppNumberMutation = gql(/* GraphQL */ `
  mutation registerWhatsAppNumberMutation($input: RegisterWhatsAppNumberInput!) {
    registerWhatsAppNumber(input: $input) {
      ok
    }
  }
`);

export const subscribeWhatsAppAppMutation = gql(/* GraphQL */ `
  mutation subscribeWhatsAppAppMutation($input: SubscribeWhatsAppAppInput!) {
    subscribeWhatsAppApp(input: $input) {
      ok
    }
  }
`);
