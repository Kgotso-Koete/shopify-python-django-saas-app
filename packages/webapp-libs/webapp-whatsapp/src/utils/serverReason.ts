import { extractGraphQLErrors } from '@sb/webapp-api-client/api';

type Reason = { message?: string; code?: string };

/**
 * The reason the backend gave for refusing a request. apps/whatsapp/schema.py raises
 * GraphQlValidationError({field: [{message, code}]}), with Meta's explanation already in the message,
 * so it's the first message under any field. Any other error gives its own message.
 */
export const serverReason = (error: unknown): string | undefined => {
  for (const graphQLError of extractGraphQLErrors(error) ?? []) {
    for (const reasons of Object.values(graphQLError.extensions ?? {})) {
      const first = (Array.isArray(reasons) ? reasons[0] : undefined) as Reason | undefined;
      if (first?.message) return first.message;
    }
    if (graphQLError.message && graphQLError.message !== 'GraphQlValidationError') return graphQLError.message;
  }
  return undefined;
};
