import { useMutation, useQuery } from '@apollo/client/react';
import { Button, ButtonVariant } from '@sb/webapp-core/components/buttons';
import { Input } from '@sb/webapp-core/components/forms';
import { AlertTriangle } from 'lucide-react';
import { FormEvent, ReactNode, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import {
  registerWhatsAppNumberMutation,
  requestWhatsAppVerificationCodeMutation,
  subscribeWhatsAppAppMutation,
  verifyWhatsAppNumberMutation,
  whatsAppNumberStatusQuery,
} from '../../graphql/numberTools.graphql';
import { serverReason } from '../../utils/serverReason';

// Meta's two-step verification PIN is exactly six digits.
const PIN_PATTERN = /^\d{6}$/;
// Links in the backend's explanations, which end with Meta's page for the error.
const URL_PATTERN = /(https?:\/\/\S+)/;

type Outcome = { ok: boolean; text: string } | null;

type TroubleshootPanelProps = { tenantId: string; accountId: string };

/**
 * The last-resort repairs for a number stuck with Meta (WhatsApp plan D18, user story 23): Meta's own
 * status for it, a verification code by SMS or voice call, registration with the two-step PIN, and
 * re-subscribing the app to the WhatsApp Business account. Each acts on Meta's side and is written to
 * the action log; the PIN is passed straight to Meta and never stored.
 */
export const TroubleshootPanel = ({ tenantId, accountId }: TroubleshootPanelProps) => {
  const intl = useIntl();
  const variables = { tenantId, accountId };
  const { data, error: statusError } = useQuery(whatsAppNumberStatusQuery, { variables, fetchPolicy: 'network-only' });
  const [requestCode, requesting] = useMutation(requestWhatsAppVerificationCodeMutation);
  const [verifyCode, verifying] = useMutation(verifyWhatsAppNumberMutation);
  const [register, registering] = useMutation(registerWhatsAppNumberMutation);
  const [subscribe, subscribing] = useMutation(subscribeWhatsAppAppMutation);

  const [code, setCode] = useState('');
  const [pin, setPin] = useState('');
  const [codeOutcome, setCodeOutcome] = useState<Outcome>(null);
  const [registerOutcome, setRegisterOutcome] = useState<Outcome>(null);
  const [subscribeOutcome, setSubscribeOutcome] = useState<Outcome>(null);

  const genericError = intl.formatMessage({
    defaultMessage: "That didn't work. Please try again.",
    id: 'WhatsAppSettings / Troubleshoot / Generic error',
  });

  /** Run one repair and show its outcome, or the backend's explained error. */
  const attempt = async (run: () => Promise<unknown>, show: (outcome: Outcome) => void, success: string) => {
    show(null);
    try {
      await run();
      show({ ok: true, text: success });
    } catch (error) {
      show({ ok: false, text: serverReason(error) ?? genericError });
    }
  };

  const onRequestCode = (method: 'SMS' | 'VOICE') =>
    attempt(
      () => requestCode({ variables: { input: { ...variables, method } } }),
      setCodeOutcome,
      intl.formatMessage({
        defaultMessage: 'Code requested. Enter it below when it arrives.',
        id: 'WhatsAppSettings / Troubleshoot / Code requested',
      })
    );

  const onVerify = (event: FormEvent) => {
    event.preventDefault();
    return attempt(
      () => verifyCode({ variables: { input: { ...variables, code } } }),
      setCodeOutcome,
      intl.formatMessage({ defaultMessage: 'Number verified.', id: 'WhatsAppSettings / Troubleshoot / Verified' })
    );
  };

  const onRegister = (event: FormEvent) => {
    event.preventDefault();
    return attempt(
      () => register({ variables: { input: { ...variables, pin } } }),
      setRegisterOutcome,
      intl.formatMessage({ defaultMessage: 'Number registered.', id: 'WhatsAppSettings / Troubleshoot / Registered' })
    ).then(() => setPin(''));
  };

  const onSubscribe = () =>
    attempt(
      () => subscribe({ variables: { input: variables } }),
      setSubscribeOutcome,
      intl.formatMessage({ defaultMessage: 'App subscribed.', id: 'WhatsAppSettings / Troubleshoot / Subscribed' })
    );

  const status = data?.whatsAppNumberStatus;

  return (
    <div className="space-y-6 rounded-md border p-4" data-testid={`whatsapp-troubleshoot-${accountId}`}>
      <section className="space-y-2">
        <h4 className="text-sm font-semibold">
          <FormattedMessage defaultMessage="Meta's status for this number" id="WhatsAppSettings / Troubleshoot / Status" />
        </h4>
        {statusError ? (
          <OutcomeText outcome={{ ok: false, text: serverReason(statusError) ?? genericError }} />
        ) : !status ? (
          <div className="h-16 animate-pulse rounded bg-muted" />
        ) : (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
            <StatusField label={intl.formatMessage({ defaultMessage: 'Status', id: 'WhatsAppSettings / Troubleshoot / Field status' })} value={status.status} />
            <StatusField
              label={intl.formatMessage({ defaultMessage: 'Code verification', id: 'WhatsAppSettings / Troubleshoot / Field code verification' })}
              value={status.codeVerificationStatus}
            />
            <StatusField
              label={intl.formatMessage({ defaultMessage: 'Quality rating', id: 'WhatsAppSettings / Troubleshoot / Field quality' })}
              value={status.qualityRating}
            />
            <StatusField
              label={intl.formatMessage({ defaultMessage: 'Display name review', id: 'WhatsAppSettings / Troubleshoot / Field name status' })}
              value={status.nameStatus}
            />
            <StatusField
              label={intl.formatMessage({ defaultMessage: 'Verified name', id: 'WhatsAppSettings / Troubleshoot / Field verified name' })}
              value={status.verifiedName}
            />
            <StatusField
              label={intl.formatMessage({ defaultMessage: 'Display number', id: 'WhatsAppSettings / Troubleshoot / Field display number' })}
              value={status.displayPhoneNumber}
            />
          </dl>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="text-sm font-semibold">
          <FormattedMessage defaultMessage="Verify the number" id="WhatsAppSettings / Troubleshoot / Verify title" />
        </h4>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant={ButtonVariant.SECONDARY} disabled={requesting.loading} onClick={() => onRequestCode('SMS')}>
            <FormattedMessage defaultMessage="Request a code by SMS" id="WhatsAppSettings / Troubleshoot / Request SMS" />
          </Button>
          <Button type="button" variant={ButtonVariant.SECONDARY} disabled={requesting.loading} onClick={() => onRequestCode('VOICE')}>
            <FormattedMessage defaultMessage="Request a code by voice call" id="WhatsAppSettings / Troubleshoot / Request voice" />
          </Button>
        </div>
        <form className="flex flex-wrap items-end gap-2" onSubmit={onVerify}>
          <div className="min-w-[10rem]">
            <Input
              value={code}
              onChange={(event) => setCode(event.target.value)}
              label={intl.formatMessage({ defaultMessage: 'Verification code', id: 'WhatsAppSettings / Troubleshoot / Code' })}
              inputMode="numeric"
              autoComplete="one-time-code"
            />
          </div>
          <Button type="submit" variant={ButtonVariant.SECONDARY} disabled={verifying.loading || !code}>
            <FormattedMessage defaultMessage="Verify code" id="WhatsAppSettings / Troubleshoot / Verify" />
          </Button>
        </form>
        <OutcomeText outcome={codeOutcome} />
      </section>

      <section className="space-y-2">
        <h4 className="text-sm font-semibold">
          <FormattedMessage defaultMessage="Register the number" id="WhatsAppSettings / Troubleshoot / Register title" />
        </h4>
        <p className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-400">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <FormattedMessage
            defaultMessage="Meta allows 10 registration attempts per number in 72 hours. Register only when Meta's status says the number isn't registered."
            id="WhatsAppSettings / Troubleshoot / Register warning"
          />
        </p>
        <form className="flex flex-wrap items-end gap-2" onSubmit={onRegister}>
          <div className="min-w-[10rem]">
            <Input
              value={pin}
              onChange={(event) => setPin(event.target.value)}
              type="password"
              label={intl.formatMessage({
                defaultMessage: 'Two-step verification 6-digit PIN',
                id: 'WhatsAppSettings / Troubleshoot / PIN',
              })}
              inputMode="numeric"
              autoComplete="off"
            />
          </div>
          <Button type="submit" variant={ButtonVariant.SECONDARY} disabled={registering.loading || !PIN_PATTERN.test(pin)}>
            <FormattedMessage defaultMessage="Register number" id="WhatsAppSettings / Troubleshoot / Register" />
          </Button>
        </form>
        <OutcomeText outcome={registerOutcome} />
      </section>

      <section className="space-y-2">
        <h4 className="text-sm font-semibold">
          <FormattedMessage defaultMessage="Webhook subscription" id="WhatsAppSettings / Troubleshoot / Subscribe title" />
        </h4>
        <Button type="button" variant={ButtonVariant.SECONDARY} disabled={subscribing.loading} onClick={onSubscribe}>
          <FormattedMessage defaultMessage="Re-subscribe the app" id="WhatsAppSettings / Troubleshoot / Subscribe" />
        </Button>
        <OutcomeText outcome={subscribeOutcome} />
      </section>
    </div>
  );
};

const StatusField = ({ label, value }: { label: string; value?: string | null }) => (
  <div>
    <dt className="text-xs text-muted-foreground">{label}</dt>
    <dd className="font-medium">{value || '—'}</dd>
  </div>
);

/** An outcome, with any link in the backend's explanation (Meta's page for the error) made clickable. */
const OutcomeText = ({ outcome }: { outcome: Outcome }) => {
  if (!outcome) return null;
  const parts: ReactNode[] = outcome.text.split(URL_PATTERN).map((part, index) =>
    URL_PATTERN.test(part) ? (
      <a key={index} href={part} target="_blank" rel="noopener noreferrer" className="underline">
        {part}
      </a>
    ) : (
      part
    )
  );
  return <p className={outcome.ok ? 'text-sm text-green-700' : 'text-sm text-destructive'}>{parts}</p>;
};
