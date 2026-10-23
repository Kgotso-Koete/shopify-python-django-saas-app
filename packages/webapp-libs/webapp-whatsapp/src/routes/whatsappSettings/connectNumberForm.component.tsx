import { useMutation } from '@apollo/client/react';
import { extractGraphQLErrors } from '@sb/webapp-api-client/api';
import { AccountPurpose } from '@sb/webapp-api-client/graphql';
import { useApiForm } from '@sb/webapp-api-client/hooks';
import { Button } from '@sb/webapp-core/components/buttons';
import { Input } from '@sb/webapp-core/components/forms';
import { CheckCircle2, Plus } from 'lucide-react';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { connectWhatsAppAccountMutation } from '../../graphql/whatsappAccounts.graphql';

type ConnectNumberFields = {
  phoneNumberId: string;
  wabaId: string;
  accessToken: string;
};

type ConnectNumberFormProps = {
  tenantId: string;
  // What the number is for: the team's internal communications number, or an external one.
  purpose: AccountPurpose;
  onConnected: () => void;
};

/**
 * The form that connects one of the organization's own WhatsApp numbers for one purpose (WhatsApp plan
 * Steps 1.5, 1.17 and 1.18, user story 11). Every number is on our one Meta app, so the form takes no
 * App secret and there's no webhook for the organization to set up. The backend asks Meta about the
 * number and subscribes our app to its WhatsApp Business account before saving anything; a refusal
 * comes back under the field at fault, such as Meta's rejection of the access token, or as a general
 * reason, such as a second internal number.
 */
export const ConnectNumberForm = ({ tenantId, purpose, onConnected }: ConnectNumberFormProps) => {
  const intl = useIntl();
  const [connectedNumber, setConnectedNumber] = useState<string | null>(null);
  const { form, genericError, handleSubmit, setApolloGraphQLResponseErrors, setGenericError } =
    useApiForm<ConnectNumberFields>({
      defaultValues: { phoneNumberId: '', wabaId: '', accessToken: '' },
    });
  const {
    register,
    reset,
    formState: { errors },
  } = form;
  const [connect, { loading }] = useMutation(connectWhatsAppAccountMutation);

  const required = (message: string) => ({ required: { value: true, message } });

  const onSubmit = handleSubmit(async (values) => {
    try {
      const { data } = await connect({ variables: { input: { tenantId, purpose, ...values } } });
      const result = data?.connectWhatsAppAccount;
      if (!result) return;
      setConnectedNumber(result.account.displayPhoneNumber);
      // The access token leaves the page as soon as it's saved.
      reset();
      onConnected();
    } catch (error) {
      const graphQLErrors = extractGraphQLErrors(error);
      if (graphQLErrors) {
        setApolloGraphQLResponseErrors(graphQLErrors);
      } else {
        setGenericError(
          intl.formatMessage({
            defaultMessage: "The number couldn't be connected. Please try again.",
            id: 'WhatsAppSettings / Connect / Generic error',
          })
        );
      }
    }
  });

  return (
    <div className="space-y-4 rounded-md border p-4">
      <div className="space-y-1">
        <p className="flex items-center gap-2 text-sm font-medium">
          <Plus className="h-4 w-4" />
          <FormattedMessage defaultMessage="Connect a number" id="WhatsAppSettings / Connect / Title" />
        </p>
        <p className="text-sm text-muted-foreground">
          <FormattedMessage
            defaultMessage="The three values from Meta's WhatsApp Manager or API Setup page."
            id="WhatsAppSettings / Connect / Description"
          />
        </p>
      </div>
      <div className="space-y-6">
        {connectedNumber && (
          <p
            className="flex items-center gap-2 rounded-md border border-green-200 bg-green-50 p-4 text-sm font-medium dark:border-green-900 dark:bg-green-950/30"
            data-testid="whatsapp-connected"
          >
            <CheckCircle2 className="h-4 w-4 text-green-600" />
            <FormattedMessage
              defaultMessage="{number} is connected: messages to it now reach this app."
              id="WhatsAppSettings / Connect / Connected"
              values={{ number: connectedNumber }}
            />
          </p>
        )}

        <form className="grid gap-4 sm:grid-cols-2" onSubmit={onSubmit} data-testid="whatsapp-connect-form" noValidate>
          <Input
            {...register(
              'phoneNumberId',
              required(
                intl.formatMessage({
                  defaultMessage: 'Phone number ID is required',
                  id: 'WhatsAppSettings / Connect / Phone number ID required',
                })
              )
            )}
            label={intl.formatMessage({ defaultMessage: 'Phone number ID', id: 'WhatsAppSettings / Connect / Phone number ID' })}
            error={errors.phoneNumberId?.message}
            autoComplete="off"
          />
          <Input
            {...register(
              'wabaId',
              required(
                intl.formatMessage({
                  defaultMessage: 'WhatsApp Business Account ID is required',
                  id: 'WhatsAppSettings / Connect / WABA ID required',
                })
              )
            )}
            label={intl.formatMessage({
              defaultMessage: 'WhatsApp Business Account ID',
              id: 'WhatsAppSettings / Connect / WABA ID',
            })}
            error={errors.wabaId?.message}
            autoComplete="off"
          />
          <Input
            {...register(
              'accessToken',
              required(
                intl.formatMessage({
                  defaultMessage: 'Access token is required',
                  id: 'WhatsAppSettings / Connect / Access token required',
                })
              )
            )}
            type="password"
            label={intl.formatMessage({ defaultMessage: 'Access token', id: 'WhatsAppSettings / Connect / Access token' })}
            error={errors.accessToken?.message}
            autoComplete="off"
          />
          {genericError && <p className="text-sm text-destructive sm:col-span-2">{genericError}</p>}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={loading}>
              <FormattedMessage defaultMessage="Connect number" id="WhatsAppSettings / Connect / Submit" />
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
