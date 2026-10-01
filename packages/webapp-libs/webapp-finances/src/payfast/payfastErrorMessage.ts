import { extractGraphQLErrors } from '@sb/webapp-api-client/api';

// What GraphQlValidationError and GraphQlMutationError put in `message`: the class name, not a reason.
const CLASS_NAME_MESSAGES = new Set(['GraphQlValidationError', 'GraphQlMutationError']);

/**
 * The message to show a user for a failed PayFast query or mutation. The backend raises
 * GraphQlValidationError({"non_field_errors": [reason]}) (apps/payfast/schema.py), so the reason is in
 * the first error's `extensions.non_field_errors`; the top-level message is only the error class name.
 */
export const payfastErrorMessage = (error: unknown, fallback: string): string => {
  const graphQLErrors = extractGraphQLErrors(error) ?? [];
  for (const graphQLError of graphQLErrors) {
    const reasons = (graphQLError.extensions?.['non_field_errors'] ?? []) as Array<{ message?: string }>;
    if (reasons[0]?.message) return reasons[0].message;
  }

  const message = graphQLErrors[0]?.message ?? (error as Error | undefined)?.message;
  return message && !CLASS_NAME_MESSAGES.has(message) ? message : fallback;
};
