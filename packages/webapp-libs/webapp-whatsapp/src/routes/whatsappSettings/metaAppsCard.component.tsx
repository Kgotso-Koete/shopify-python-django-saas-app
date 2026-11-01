import { useMutation } from '@apollo/client/react';
import { extractGraphQLErrors } from '@sb/webapp-api-client/api';
import { useApiForm } from '@sb/webapp-api-client/hooks';
import { Button, ButtonVariant } from '@sb/webapp-core/components/buttons';
import { ConfirmDialog } from '@sb/webapp-core/components/confirmDialog';
import { Input } from '@sb/webapp-core/components/forms';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { useToast } from '@sb/webapp-core/toast';
import { Copy, KeyRound, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import {
  regenerateWhatsAppMetaAppVerifyTokenMutation,
  registerWhatsAppMetaAppMutation,
  removeWhatsAppMetaAppMutation,
  updateWhatsAppMetaAppSecretMutation,
} from '../../graphql/whatsappMetaApps.graphql';
import { serverReason } from '../../utils/serverReason';

/** One of the organization's own Meta apps, as whatsAppMetaAppsQuery lists it: never its App secret. */
export type MetaApp = {
  id: string;
  appId: string;
  webhookUrl: string;
  verifyToken: string;
};

type MetaAppsCardProps = {
  tenantId: string;
  apps: MetaApp[];
  onChanged: () => void;
};

/**
 * "Your Meta apps" (WhatsApp plan Step 2.9, decisions 1 to 4), for whatsapp.manage only: the backend
 * checks the same permission, since the list holds each app's verify token. A business whose numbers are
 * in a Meta app of its own registers the app once here; the service gives it a callback URL and a verify
 * token of its own, to paste into the app's WhatsApp webhook settings in Meta's App Dashboard. Numbers
 * in this service's app need nothing here.
 */
export const MetaAppsCard = ({ tenantId, apps, onChanged }: MetaAppsCardProps) => (
  <Card data-testid="whatsapp-meta-apps">
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <KeyRound className="h-5 w-5" />
        <FormattedMessage defaultMessage="Your Meta apps" id="WhatsAppSettings / Meta apps / Title" />
      </CardTitle>
      <CardDescription>
        <FormattedMessage
          defaultMessage="For numbers in a Meta app of your own. Register the app once with its App ID and App secret, from its Basic settings in Meta's App Dashboard. Then paste its callback URL and verify token below into the app's WhatsApp webhook settings, and choose the app when you connect a number. Numbers in this service's app need nothing here."
          id="WhatsAppSettings / Meta apps / Description"
        />
      </CardDescription>
    </CardHeader>
    <CardContent className="space-y-6">
      <RegisterForm tenantId={tenantId} onRegistered={onChanged} />
      {apps.length > 0 && (
        <ul className="divide-y rounded-md border">
          {apps.map((app) => (
            <MetaAppRow key={app.id} tenantId={tenantId} app={app} onChanged={onChanged} />
          ))}
        </ul>
      )}
    </CardContent>
  </Card>
);

type RegisterFields = { appId: string; appSecret: string };

const RegisterForm = ({ tenantId, onRegistered }: { tenantId: string; onRegistered: () => void }) => {
  const intl = useIntl();
  const { form, genericError, handleSubmit, setApolloGraphQLResponseErrors, setGenericError } =
    useApiForm<RegisterFields>({ defaultValues: { appId: '', appSecret: '' } });
  const {
    register,
    reset,
    formState: { errors },
  } = form;
  const [registerApp, { loading }] = useMutation(registerWhatsAppMetaAppMutation);

  const onSubmit = handleSubmit(async (values) => {
    try {
      await registerApp({ variables: { input: { tenantId, ...values } } });
      // The App secret leaves the page as soon as it's saved.
      reset({ appId: '', appSecret: '' });
      onRegistered();
    } catch (error) {
      const graphQLErrors = extractGraphQLErrors(error);
      if (graphQLErrors) {
        setApolloGraphQLResponseErrors(graphQLErrors);
      } else {
        setGenericError(
          intl.formatMessage({
            defaultMessage: "The app couldn't be registered. Please try again.",
            id: 'WhatsAppSettings / Meta apps / Register / Generic error',
          })
        );
      }
    }
  });

  const required = (message: string) => ({ required: { value: true, message } });

  return (
    <form className="grid gap-4 rounded-md border p-4 sm:grid-cols-2" onSubmit={onSubmit} noValidate>
      <p className="flex items-center gap-2 text-sm font-medium sm:col-span-2">
        <Plus className="h-4 w-4" />
        <FormattedMessage defaultMessage="Register a Meta app" id="WhatsAppSettings / Meta apps / Register / Title" />
      </p>
      <Input
        {...register(
          'appId',
          required(
            intl.formatMessage({ defaultMessage: 'App ID is required', id: 'WhatsAppSettings / Meta apps / App ID required' })
          )
        )}
        label={intl.formatMessage({ defaultMessage: 'App ID', id: 'WhatsAppSettings / Meta apps / App ID' })}
        error={errors.appId?.message}
        autoComplete="off"
      />
      <Input
        {...register(
          'appSecret',
          required(
            intl.formatMessage({
              defaultMessage: 'App secret is required',
              id: 'WhatsAppSettings / Meta apps / App secret required',
            })
          )
        )}
        type="password"
        label={intl.formatMessage({ defaultMessage: 'App secret', id: 'WhatsAppSettings / Meta apps / App secret' })}
        error={errors.appSecret?.message}
        autoComplete="off"
      />
      {genericError && <p className="text-sm text-destructive sm:col-span-2">{genericError}</p>}
      <div className="sm:col-span-2">
        <Button type="submit" disabled={loading}>
          <FormattedMessage defaultMessage="Register app" id="WhatsAppSettings / Meta apps / Register / Submit" />
        </Button>
      </div>
    </form>
  );
};

type MetaAppRowProps = { tenantId: string; app: MetaApp; onChanged: () => void };

/** One registered app: what to paste into Meta, and Update secret, Regenerate token and Remove. */
const MetaAppRow = ({ tenantId, app, onChanged }: MetaAppRowProps) => {
  const intl = useIntl();
  const [problem, setProblem] = useState<string | null>(null);
  const [regenerate] = useMutation(regenerateWhatsAppMetaAppVerifyTokenMutation);
  const [remove] = useMutation(removeWhatsAppMetaAppMutation);

  const run = async (call: () => Promise<unknown>, fallback: string) => {
    setProblem(null);
    try {
      await call();
      onChanged();
    } catch (error) {
      setProblem(serverReason(error) ?? fallback);
    }
  };

  const onRegenerate = () =>
    run(
      () => regenerate({ variables: { input: { tenantId, metaAppId: app.id } } }),
      intl.formatMessage({
        defaultMessage: "The token couldn't be regenerated. Please try again.",
        id: 'WhatsAppSettings / Meta apps / Regenerate / Generic error',
      })
    );

  const onRemove = () =>
    run(
      () => remove({ variables: { input: { tenantId, metaAppId: app.id } } }),
      intl.formatMessage({
        defaultMessage: "The app couldn't be removed. Please try again.",
        id: 'WhatsAppSettings / Meta apps / Remove / Generic error',
      })
    );

  return (
    <li className="space-y-4 px-6 py-4" data-testid={`whatsapp-meta-app-${app.id}`}>
      <p className="text-sm font-medium">
        <FormattedMessage
          defaultMessage="App {appId}"
          id="WhatsAppSettings / Meta apps / App"
          values={{ appId: app.appId }}
        />
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <CopyValue
          id={`whatsapp-meta-app-url-${app.id}`}
          label={intl.formatMessage({ defaultMessage: 'Callback URL', id: 'WhatsAppSettings / Meta apps / Callback URL' })}
          copyLabel={intl.formatMessage({
            defaultMessage: 'Copy callback URL',
            id: 'WhatsAppSettings / Meta apps / Copy callback URL',
          })}
          value={app.webhookUrl}
        />
        <CopyValue
          id={`whatsapp-meta-app-token-${app.id}`}
          label={intl.formatMessage({ defaultMessage: 'Verify token', id: 'WhatsAppSettings / Meta apps / Verify token' })}
          copyLabel={intl.formatMessage({
            defaultMessage: 'Copy verify token',
            id: 'WhatsAppSettings / Meta apps / Copy verify token',
          })}
          value={app.verifyToken}
        />
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <UpdateSecretForm tenantId={tenantId} app={app} />
        <ConfirmDialog
          title={intl.formatMessage(
            { defaultMessage: 'Regenerate the verify token of app {appId}?', id: 'WhatsAppSettings / Meta apps / Regenerate / Title' },
            { appId: app.appId }
          )}
          description={intl.formatMessage({
            defaultMessage:
              "Messages keep arriving: Meta asks for the verify token only when the app's webhook settings are saved. Paste the new one there the next time you save them.",
            id: 'WhatsAppSettings / Meta apps / Regenerate / Description',
          })}
          continueLabel={intl.formatMessage({
            defaultMessage: 'Regenerate verify token',
            id: 'WhatsAppSettings / Meta apps / Regenerate / Continue',
          })}
          onContinue={onRegenerate}
        >
          <Button variant={ButtonVariant.SECONDARY}>
            <RefreshCw className="mr-1 h-4 w-4" />
            <FormattedMessage defaultMessage="Regenerate token" id="WhatsAppSettings / Meta apps / Regenerate / Button" />
          </Button>
        </ConfirmDialog>
        <ConfirmDialog
          title={intl.formatMessage(
            { defaultMessage: 'Remove app {appId}?', id: 'WhatsAppSettings / Meta apps / Remove / Title' },
            { appId: app.appId }
          )}
          description={intl.formatMessage({
            defaultMessage:
              'Its App secret, callback URL and verify token are deleted. An app is removed only once none of your connected numbers is in it.',
            id: 'WhatsAppSettings / Meta apps / Remove / Description',
          })}
          continueLabel={intl.formatMessage({
            defaultMessage: 'Remove app',
            id: 'WhatsAppSettings / Meta apps / Remove / Continue',
          })}
          variant="destructive"
          onContinue={onRemove}
        >
          <Button variant={ButtonVariant.GHOST}>
            <Trash2 className="mr-1 h-4 w-4" />
            <FormattedMessage defaultMessage="Remove" id="WhatsAppSettings / Meta apps / Remove / Button" />
          </Button>
        </ConfirmDialog>
      </div>
      {problem && <p className="text-sm text-destructive">{problem}</p>}
    </li>
  );
};

/** Update secret: a small form, opened on demand, for a secret reset in Meta's App Dashboard. */
const UpdateSecretForm = ({ tenantId, app }: { tenantId: string; app: MetaApp }) => {
  const intl = useIntl();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [secret, setSecret] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [update, { loading }] = useMutation(updateWhatsAppMetaAppSecretMutation);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setProblem(null);
    try {
      await update({ variables: { input: { tenantId, metaAppId: app.id, appSecret: secret } } });
      toast({
        description: intl.formatMessage(
          { defaultMessage: "App {appId}'s App secret is updated.", id: 'WhatsAppSettings / Meta apps / Secret / Saved' },
          { appId: app.appId }
        ),
        variant: 'success',
      });
      setSecret('');
      setOpen(false);
    } catch (error) {
      setProblem(
        serverReason(error) ??
          intl.formatMessage({
            defaultMessage: "The App secret couldn't be updated. Please try again.",
            id: 'WhatsAppSettings / Meta apps / Secret / Generic error',
          })
      );
    }
  };

  if (!open) {
    return (
      <Button variant={ButtonVariant.SECONDARY} onClick={() => setOpen(true)}>
        <KeyRound className="mr-1 h-4 w-4" />
        <FormattedMessage defaultMessage="Update secret" id="WhatsAppSettings / Meta apps / Secret / Button" />
      </Button>
    );
  }

  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={onSubmit}>
      <div className="min-w-[14rem]">
        <Input
          type="password"
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
          label={intl.formatMessage({ defaultMessage: 'New App secret', id: 'WhatsAppSettings / Meta apps / Secret / Label' })}
          autoComplete="off"
        />
      </div>
      <Button type="submit" variant={ButtonVariant.SECONDARY} disabled={loading || !secret}>
        <FormattedMessage defaultMessage="Save secret" id="WhatsAppSettings / Meta apps / Secret / Save" />
      </Button>
      {problem && <p className="w-full text-sm text-destructive">{problem}</p>}
    </form>
  );
};

type CopyValueProps = { id: string; label: string; copyLabel: string; value: string };

/** A value to paste into Meta, read-only, with a button that copies it (as the SSO card's token does). */
const CopyValue = ({ id, label, copyLabel, value }: CopyValueProps) => {
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    void navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex gap-2">
        <input
          id={id}
          readOnly
          value={value}
          className="flex h-10 w-full rounded-md border border-input bg-muted px-3 font-mono text-xs"
        />
        <Button type="button" variant={ButtonVariant.SECONDARY} onClick={onCopy} aria-label={copyLabel}>
          {copied ? (
            <FormattedMessage defaultMessage="Copied" id="WhatsAppSettings / Meta apps / Copied" />
          ) : (
            <Copy className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  );
};
