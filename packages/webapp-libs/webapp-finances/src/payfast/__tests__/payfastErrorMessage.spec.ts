import { GraphQLError } from 'graphql';

import { payfastErrorMessage } from '../payfastErrorMessage';

// The backend raises GraphQlValidationError({"non_field_errors": [message]}) (apps/payfast/schema.py), so the
// user-facing reason is in the error's extensions; the top-level message is only the class name.
describe('payfastErrorMessage', () => {
  it('returns the reason from non_field_errors', () => {
    const error = {
      errors: [
        new GraphQLError('GraphQlValidationError', {
          extensions: {
            non_field_errors: [{ message: 'PayFast could not process the request. Please try again later.', code: 'invalid' }],
          },
        }),
      ],
      message: 'GraphQlValidationError',
    };

    expect(payfastErrorMessage(error, 'fallback')).toBe('PayFast could not process the request. Please try again later.');
  });

  it('falls back to the GraphQL message when there is no reason', () => {
    const error = { errors: [new GraphQLError('permission_denied')], message: 'permission_denied' };

    expect(payfastErrorMessage(error, 'fallback')).toBe('permission_denied');
  });

  it('never shows the bare class name', () => {
    const error = { errors: [new GraphQLError('GraphQlValidationError')], message: 'GraphQlValidationError' };

    expect(payfastErrorMessage(error, 'Something went wrong')).toBe('Something went wrong');
  });

  it('uses the fallback for network errors without GraphQL errors', () => {
    expect(payfastErrorMessage(new Error(''), 'Something went wrong')).toBe('Something went wrong');
  });
});
