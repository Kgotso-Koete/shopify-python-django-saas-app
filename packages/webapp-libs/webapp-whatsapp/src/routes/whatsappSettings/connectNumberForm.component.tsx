import { useMutation } from '@apollo/client/react';
import { extractGraphQLErrors } from '@sb/webapp-api-client/api';
import { AccountPurpose } from '@sb/webapp-api-client/graphql';
import { useApiForm } from '@sb/webapp-api-client/hooks';
import { Button } from '@sb/webapp-core/components/buttons';
import { Input } from '@sb/webapp-core/components/forms';
import { CheckCircle2, Plus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { connectWhatsAppAccountMutation } from '../../graphql/whatsappAccounts.graphql';
import { chooseWhatsAppStoreMutation } from '../../graphql/whatsappStorefronts.graphql';
import { servesCustomers } from '../../utils/purposes';
import { serverReason } from '../../utils/serverReason';

type ConnectNumberFields = {
  // Whom the number serves: the team, the customers, or both (WhatsApp plan Step 2.7); empty until chosen.
  purpose: AccountPurpose | '';
  phoneNumberId: string;
  wabaId: string;
  accessToken: string;
  // Numbers serving customers only: the store the number sells from (Step 2.1b).
  shopDomain: string;
};

type ConnectNumberFormProps = {
  tenantId: string;
  onConnected: () => void;
  // The organization's stores that can sell on WhatsApp, and whether that list has arrived.
  stores: string[];
  storesLoaded: boolean;
};

const EMPTY: ConnectNumberFields = { purpose: '', phoneNumberId: '', wabaId: '', accessToken: '', shopDomain: '' };

/**
 * The form that connects one of the organization's own WhatsApp numbers for one purpose (WhatsApp plan
 * Steps 1.5, 1.17 and 1.18, user story 11). Every number is on our one Meta app, so the form takes no
 * App secret and there's no webhook for the organization to set up. The backend asks Meta about the
 * number and subscribes our app to its WhatsApp Business account before saving anything; a refusal
 * comes back under the field at fault, such as Meta's rejection of the access token, or as a general
 * reason, such as a second number for the team.
 *
 * It first asks who texts the number (Step 2.7, decision 4): the team, the customers, or both. A number
 * serving customers also needs the store it sells from (Step 2.1b, user story 25), chosen here and
 * saved by a second call once the number is connected (decision 5): apps.whatsapp, which connects
 * numbers, knows nothing about Shopify. If that second call fails, the number stays connected, and its
 * row offers the store picker.
 */
export const ConnectNumberForm = ({ tenantId, onConnected, stores, storesLoaded }: ConnectNumberFormProps) => {
  const intl = useIntl();
  const [connectedNumber, setConnectedNumber] = useState<string | null>(null);
  const [storeProblem, setStoreProblem] = useState<string | null>(null);
  const { form, genericError, handleSubmit, setApolloGraphQLResponseErrors, setGenericError } =
    useApiForm<ConnectNumberFields>({ defaultValues: EMPTY });
  const {
    register,
    reset,
    getValues,
    setValue,
    watch,
    formState: { errors },
  } = form;
  const purpose = watch('purpose');
  const sellsFromAStore = purpose !== '' && servesCustomers(purpose);
  const [connect, { loading }] = useMutation(connectWhatsAppAccountMutation);
  const [chooseStore] = useMutation(chooseWhatsAppStoreMutation);

  // The organization's only store is chosen for the admin; with several, they pick one.
  const onlyStore = stores.length === 1 ? stores[0] : '';
  useEffect(() => {
    if (sellsFromAStore && onlyStore && !getValues('shopDomain')) setValue('shopDomain', onlyStore);
  }, [sellsFromAStore, onlyStore, getValues, setValue]);
  // No store can sell on WhatsApp yet: the admin connects one on the Shopify page first.
  const noStore = sellsFromAStore && storesLoaded && stores.length === 0;

  const required = (message: string) => ({ required: { value: true, message } });

  const audiences = [
    {
      value: AccountPurpose.INTERNAL_COMMUNICATIONS,
      label: intl.formatMessage({ defaultMessage: 'Your team', id: 'WhatsAppSettings / Connect / Who / Team' }),
    },
    {
      value: AccountPurpose.EXTERNAL_COMMUNICATIONS,
      label: intl.formatMessage({ defaultMessage: 'Your customers', id: 'WhatsAppSettings / Connect / Who / Customers' }),
    },
    {
      value: AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS,
      label: intl.formatMessage({
        defaultMessage: 'Both: your team and your customers',
        id: 'WhatsAppSettings / Connect / Who / Both',
      }),
    },
  ];

  const onSubmit = handleSubmit(async ({ shopDomain, purpose: chosen, ...values }) => {
    setStoreProblem(null);
    if (chosen === '') return;
    try {
      const { data } = await connect({ variables: { input: { tenantId, purpose: chosen, ...values } } });
      const result = data?.connectWhatsAppAccount;
      if (!result) return;
      setConnectedNumber(result.account.displayPhoneNumber);
      if (sellsFromAStore && shopDomain) {
        try {
          await chooseStore({ variables: { input: { tenantId, accountId: result.account.id, shopDomain } } });
        } catch (error) {
          setStoreProblem(
            serverReason(error) ??
              intl.formatMessage({
                defaultMessage: "The number is connected, but its store wasn't saved. Choose it on the number's row.",
                id: 'WhatsAppSettings / Connect / Store not saved',
              })
          );
        }
      }
      // The access token leaves the page as soon as it's saved.
      reset(EMPTY);
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
        {storeProblem && <p className="text-sm text-destructive">{storeProblem}</p>}

        <form className="grid gap-4 sm:grid-cols-2" onSubmit={onSubmit} data-testid="whatsapp-connect-form" noValidate>
          <fieldset className="space-y-2 sm:col-span-2">
            <legend className="text-sm font-medium">
              <FormattedMessage defaultMessage="Who texts this number?" id="WhatsAppSettings / Connect / Who" />
            </legend>
            <div className="flex flex-wrap gap-4">
              {audiences.map(({ value, label }) => (
                <label key={value} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    value={value}
                    {...register(
                      'purpose',
                      required(
                        intl.formatMessage({
                          defaultMessage: 'Choose who texts this number',
                          id: 'WhatsAppSettings / Connect / Who required',
                        })
                      )
                    )}
                  />
                  {label}
                </label>
              ))}
            </div>
            {errors.purpose?.message && <p className="text-sm text-destructive">{errors.purpose.message}</p>}
          </fieldset>
          {noStore && (
            <p className="text-sm text-muted-foreground sm:col-span-2" data-testid="whatsapp-connect-no-store">
              <FormattedMessage
                defaultMessage="Connect a Shopify store on the Shopify page first: a number your customers text sells from one of your stores, which must allow selling on WhatsApp."
                id="WhatsAppSettings / Connect / No store"
              />
            </p>
          )}
          {sellsFromAStore && !noStore && (
            <div className="space-y-2 sm:col-span-2">
              <label htmlFor="whatsapp-connect-store" className="text-sm font-medium">
                <FormattedMessage defaultMessage="Store" id="WhatsAppSettings / Connect / Store" />
              </label>
              <select
                id="whatsapp-connect-store"
                {...register(
                  'shopDomain',
                  required(
                    intl.formatMessage({
                      defaultMessage: 'Choose the store this number sells from',
                      id: 'WhatsAppSettings / Connect / Store required',
                    })
                  )
                )}
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">
                  {intl.formatMessage({ defaultMessage: 'Choose a store', id: 'WhatsAppSettings / Connect / Choose store' })}
                </option>
                {stores.map((store) => (
                  <option key={store} value={store}>
                    {store}
                  </option>
                ))}
              </select>
              {errors.shopDomain?.message && <p className="text-sm text-destructive">{errors.shopDomain.message}</p>}
            </div>
          )}
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
            <Button type="submit" disabled={loading || noStore}>
              <FormattedMessage defaultMessage="Connect number" id="WhatsAppSettings / Connect / Submit" />
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};
