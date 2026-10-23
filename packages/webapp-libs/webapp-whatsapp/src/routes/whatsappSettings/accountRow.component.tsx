import { useMutation } from '@apollo/client/react';
import { Button, ButtonVariant } from '@sb/webapp-core/components/buttons';
import { ConfirmDialog } from '@sb/webapp-core/components/confirmDialog';
import { Input } from '@sb/webapp-core/components/forms';
import { CheckCircle2, Circle, Phone, Unplug, Wrench, XCircle } from 'lucide-react';
import { FormEvent, ReactNode, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import {
  disconnectWhatsAppAccountMutation,
  sendWhatsAppTestMessageMutation,
} from '../../graphql/whatsappAccounts.graphql';
import { serverReason } from '../../utils/serverReason';
import { TroubleshootPanel } from './troubleshootPanel.component';

export type WhatsAppAccount = {
  id: string;
  displayPhoneNumber: string;
  verifiedName: string;
  isActive: boolean;
  credentialsVerifiedAt?: unknown;
  subscribedAt?: unknown;
  lastMessageReceivedAt?: unknown;
};

type AccountRowProps = {
  account: WhatsAppAccount;
  tenantId: string;
  canManage: boolean;
  onChanged: () => void;
};

/**
 * One of the organization's numbers: the three proofs the connect form tracks (Meta accepted the
 * credentials, our app is subscribed to its WhatsApp Business account, a message arrived), and for
 * whatsapp.manage, a test message, the troubleshooting panel (Step 1.6b) and Disconnect.
 */
export const AccountRow = ({ account, tenantId, canManage, onChanged }: AccountRowProps) => {
  const intl = useIntl();
  const [disconnect] = useMutation(disconnectWhatsAppAccountMutation);
  const [troubleshooting, setTroubleshooting] = useState(false);

  const onDisconnect = async () => {
    await disconnect({ variables: { input: { tenantId, accountId: account.id } } });
    onChanged();
  };

  return (
    <li className="space-y-4 px-6 py-4" data-testid={`whatsapp-account-${account.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Phone className="h-5 w-5 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">{account.displayPhoneNumber}</p>
            <p className="text-xs text-muted-foreground">{account.verifiedName}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {account.isActive ? (
            <>
              <Proof done={!!account.credentialsVerifiedAt}>
                {account.credentialsVerifiedAt ? (
                  <FormattedMessage defaultMessage="Credentials verified" id="WhatsAppSettings / Proof / Credentials" />
                ) : (
                  <FormattedMessage defaultMessage="Credentials not verified" id="WhatsAppSettings / Proof / No credentials" />
                )}
              </Proof>
              <Proof done={!!account.subscribedAt}>
                {account.subscribedAt ? (
                  <FormattedMessage defaultMessage="App subscribed" id="WhatsAppSettings / Proof / Subscribed" />
                ) : (
                  <FormattedMessage defaultMessage="App not subscribed" id="WhatsAppSettings / Proof / Not subscribed" />
                )}
              </Proof>
              <Proof done={!!account.lastMessageReceivedAt}>
                {account.lastMessageReceivedAt ? (
                  <FormattedMessage defaultMessage="Message received" id="WhatsAppSettings / Proof / Message" />
                ) : (
                  <FormattedMessage defaultMessage="No message yet" id="WhatsAppSettings / Proof / No message" />
                )}
              </Proof>
            </>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400">
              <XCircle className="h-3 w-3" />
              <FormattedMessage defaultMessage="Disconnected" id="WhatsAppSettings / Disconnected" />
            </span>
          )}
        </div>
      </div>

      {canManage && account.isActive && (
        <div className="flex flex-wrap items-end justify-between gap-4">
          <TestMessageForm tenantId={tenantId} accountId={account.id} />
          <Button
            variant={ButtonVariant.GHOST}
            aria-expanded={troubleshooting}
            onClick={() => setTroubleshooting((open) => !open)}
          >
            <Wrench className="mr-1 h-4 w-4" />
            <FormattedMessage defaultMessage="Troubleshoot" id="WhatsAppSettings / Troubleshoot / Button" />
          </Button>
          <ConfirmDialog
            title={intl.formatMessage(
              { defaultMessage: 'Disconnect {number}?', id: 'WhatsAppSettings / Disconnect / Title' },
              { number: account.displayPhoneNumber }
            )}
            description={intl.formatMessage({
              defaultMessage:
                'Its access token is deleted, and it stops answering messages. Its message history is kept.',
              id: 'WhatsAppSettings / Disconnect / Description',
            })}
            continueLabel={intl.formatMessage({
              defaultMessage: 'Disconnect number',
              id: 'WhatsAppSettings / Disconnect / Continue',
            })}
            variant="destructive"
            onContinue={onDisconnect}
          >
            <Button variant={ButtonVariant.SECONDARY}>
              <Unplug className="mr-1 h-4 w-4" />
              <FormattedMessage defaultMessage="Disconnect" id="WhatsAppSettings / Disconnect / Button" />
            </Button>
          </ConfirmDialog>
        </div>
      )}

      {/* Every tool, Meta's status included, needs whatsapp.manage on the backend (Step 1.5b). */}
      {canManage && account.isActive && troubleshooting && <TroubleshootPanel tenantId={tenantId} accountId={account.id} />}
    </li>
  );
};

const Proof = ({ done, children }: { done: boolean; children: ReactNode }) => (
  <span
    className={
      done
        ? 'inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400'
        : 'inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground'
    }
  >
    {done ? <CheckCircle2 className="h-3 w-3" /> : <Circle className="h-3 w-3" />}
    {children}
  </span>
);

/** Meta's hello_world template, sent straight from the number, so Meta's answer shows here. */
const TestMessageForm = ({ tenantId, accountId }: { tenantId: string; accountId: string }) => {
  const intl = useIntl();
  const [to, setTo] = useState('');
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [send, { loading }] = useMutation(sendWhatsAppTestMessageMutation);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setResult(null);
    try {
      const { data } = await send({ variables: { input: { tenantId, accountId, to } } });
      const messageId = data?.sendWhatsAppTestMessage?.messageId ?? '';
      setResult({
        ok: true,
        text: intl.formatMessage(
          { defaultMessage: "Sent. Meta's message id: {messageId}", id: 'WhatsAppSettings / Test message / Sent' },
          { messageId }
        ),
      });
    } catch (error) {
      setResult({
        ok: false,
        text:
          serverReason(error) ??
          intl.formatMessage({
            defaultMessage: "The test message couldn't be sent. Please try again.",
            id: 'WhatsAppSettings / Test message / Generic error',
          }),
      });
    }
  };

  return (
    <form className="flex flex-1 flex-wrap items-end gap-2" onSubmit={onSubmit}>
      <div className="min-w-[14rem] flex-1">
        <Input
          value={to}
          onChange={(event) => setTo(event.target.value)}
          label={intl.formatMessage({
            defaultMessage: 'Send a test message to',
            id: 'WhatsAppSettings / Test message / To',
          })}
          placeholder="083 123 4567"
        />
      </div>
      <Button type="submit" variant={ButtonVariant.SECONDARY} disabled={loading || !to}>
        <FormattedMessage defaultMessage="Send test message" id="WhatsAppSettings / Test message / Send" />
      </Button>
      {result && (
        <p className={result.ok ? 'w-full text-sm text-green-700' : 'w-full text-sm text-destructive'}>{result.text}</p>
      )}
    </form>
  );
};
