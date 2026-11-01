import { useMutation } from '@apollo/client/react';
import { AccountPurpose, ConversationMode } from '@sb/webapp-api-client/graphql';
import { Button, ButtonVariant } from '@sb/webapp-core/components/buttons';
import { ConfirmDialog } from '@sb/webapp-core/components/confirmDialog';
import { Input } from '@sb/webapp-core/components/forms';
import { useToast } from '@sb/webapp-core/toast';
import { CheckCircle2, Circle, Phone, Store, Unplug, Wrench, XCircle } from 'lucide-react';
import { FormEvent, ReactNode, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import {
  changeWhatsAppNumberPurposeMutation,
  disconnectWhatsAppAccountMutation,
  sendWhatsAppTestMessageMutation,
} from '../../graphql/whatsappAccounts.graphql';
import { chooseWhatsAppStoreMutation, setWhatsAppStorefrontModeMutation } from '../../graphql/whatsappStorefronts.graphql';
import { serverReason } from '../../utils/serverReason';
import { TroubleshootPanel } from './troubleshootPanel.component';

export type WhatsAppAccount = {
  id: string;
  // Whom the number serves: the team, the customers, or both (WhatsApp plan Step 2.7).
  purpose: AccountPurpose;
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
  // External numbers only (Step 2.1b): the store the number sells from, null while none is chosen,
  // and the stores the picker offers. Undefined for the internal number, which never sells.
  store?: string | null;
  stores?: string[];
  // Menus or the assistant for the number's customers (phase 2, decision 2); null while no store is chosen.
  mode?: ConversationMode | null;
};

/**
 * One of the organization's numbers: the three proofs the connect form tracks (Meta accepted the
 * credentials, our app is subscribed to its WhatsApp Business account, a message arrived), and for
 * whatsapp.manage, a test message, the troubleshooting panel (Step 1.6b) and Disconnect. An external
 * number also shows the store it sells from, which whatsapp.manage can change (Step 2.1b).
 */
export const AccountRow = ({ account, tenantId, canManage, onChanged, store, stores, mode }: AccountRowProps) => {
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
            <p className="text-xs font-medium" data-testid={`whatsapp-purpose-${account.id}`}>
              <PurposeLabel purpose={account.purpose} />
            </p>
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

      {/* A disconnected number gets no messages, so the store it sells from doesn't matter until it's
          reconnected; its link is kept. */}
      {store !== undefined && account.isActive && (
        <StoreLine
          tenantId={tenantId}
          accountId={account.id}
          store={store}
          stores={canManage ? (stores ?? []) : undefined}
          onChanged={onChanged}
        />
      )}
      {store && account.isActive && mode && (
        <ModeSetting
          tenantId={tenantId}
          accountId={account.id}
          purpose={account.purpose}
          mode={mode}
          canManage={canManage}
          onChanged={onChanged}
        />
      )}

      {canManage && account.isActive && (
        <PurposeChanger tenantId={tenantId} account={account} onChanged={onChanged} />
      )}

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

type StoreLineProps = {
  tenantId: string;
  accountId: string;
  store: string | null;
  // The picker's stores, for whatsapp.manage; undefined shows the store without a picker.
  stores?: string[];
  onChanged: () => void;
};

/**
 * The store an external number sells from, or that none is chosen yet (Step 2.1b, user story 25), and
 * for whatsapp.manage, a picker to change it, which saves with the same mutation the connect form uses.
 */
const StoreLine = ({ tenantId, accountId, store, stores, onChanged }: StoreLineProps) => {
  const intl = useIntl();
  const { toast } = useToast();
  const [chosen, setChosen] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const [chooseStore, { loading }] = useMutation(chooseWhatsAppStoreMutation);
  // The stores to switch to: every one offered but the current.
  const others = (stores ?? []).filter((domain) => domain !== store);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setProblem(null);
    try {
      await chooseStore({ variables: { input: { tenantId, accountId, shopDomain: chosen } } });
      // Saved straight away, so the admin is told it was (WhatsApp plan Step 2.8, finding 14).
      toast({
        description: intl.formatMessage(
          { defaultMessage: 'This number now sells from {store}.', id: 'WhatsAppSettings / Store / Saved' },
          { store: chosen }
        ),
        variant: 'success',
      });
      setChosen('');
      onChanged();
    } catch (error) {
      setProblem(
        serverReason(error) ??
          intl.formatMessage({
            defaultMessage: "The store couldn't be saved. Please try again.",
            id: 'WhatsAppSettings / Store / Generic error',
          })
      );
    }
  };

  return (
    <div className="flex flex-wrap items-end justify-between gap-4" data-testid={`whatsapp-store-${accountId}`}>
      <p className="flex items-center gap-2 text-sm">
        <Store className="h-4 w-4 text-muted-foreground" />
        {store ? (
          <FormattedMessage
            defaultMessage="Sells from {store}"
            id="WhatsAppSettings / Store / Sells from"
            values={{ store: <strong key="store">{store}</strong> }}
          />
        ) : (
          <FormattedMessage
            defaultMessage="No store chosen: its customers get no reply until one is."
            id="WhatsAppSettings / Store / None"
          />
        )}
      </p>
      {stores && others.length > 0 && (
        <form className="flex flex-wrap items-end gap-2" onSubmit={onSubmit}>
          <div className="space-y-2">
            <label htmlFor={`whatsapp-store-picker-${accountId}`} className="text-sm font-medium">
              <FormattedMessage defaultMessage="Change store" id="WhatsAppSettings / Store / Change" />
            </label>
            <select
              id={`whatsapp-store-picker-${accountId}`}
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
              className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">
                {intl.formatMessage({ defaultMessage: 'Choose a store', id: 'WhatsAppSettings / Store / Choose' })}
              </option>
              {others.map((domain) => (
                <option key={domain} value={domain}>
                  {domain}
                </option>
              ))}
            </select>
          </div>
          <Button type="submit" variant={ButtonVariant.SECONDARY} disabled={loading || !chosen}>
            <FormattedMessage defaultMessage="Save store" id="WhatsAppSettings / Store / Save" />
          </Button>
          {problem && <p className="w-full text-sm text-destructive">{problem}</p>}
        </form>
      )}
    </div>
  );
};

/** Whom a number serves, in the words the connect form uses. */
const PurposeLabel = ({ purpose }: { purpose: AccountPurpose }) => {
  if (purpose === AccountPurpose.INTERNAL_COMMUNICATIONS) {
    return <FormattedMessage defaultMessage="Your team" id="WhatsAppSettings / Purpose / Team" />;
  }
  if (purpose === AccountPurpose.EXTERNAL_COMMUNICATIONS) {
    return <FormattedMessage defaultMessage="Your customers" id="WhatsAppSettings / Purpose / Customers" />;
  }
  return <FormattedMessage defaultMessage="Your team and your customers" id="WhatsAppSettings / Purpose / Both" />;
};

type PurposeChangerProps = { tenantId: string; account: WhatsAppAccount; onChanged: () => void };

/**
 * Change whom a connected number serves (WhatsApp plan Step 2.7, decisions 2 and 3), after a
 * confirmation that says what changes. The backend keeps one number for the team, and refuses with
 * the reason otherwise.
 */
const PurposeChanger = ({ tenantId, account, onChanged }: PurposeChangerProps) => {
  const intl = useIntl();
  const { toast } = useToast();
  const [chosen, setChosen] = useState<AccountPurpose>(account.purpose);
  const [problem, setProblem] = useState<string | null>(null);
  const [change, { loading }] = useMutation(changeWhatsAppNumberPurposeMutation);
  const selectId = `whatsapp-purpose-picker-${account.id}`;

  const options = [
    {
      value: AccountPurpose.INTERNAL_COMMUNICATIONS,
      label: intl.formatMessage({ defaultMessage: 'Your team', id: 'WhatsAppSettings / Purpose / Team' }),
    },
    {
      value: AccountPurpose.EXTERNAL_COMMUNICATIONS,
      label: intl.formatMessage({ defaultMessage: 'Your customers', id: 'WhatsAppSettings / Purpose / Customers' }),
    },
    {
      value: AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS,
      label: intl.formatMessage({
        defaultMessage: 'Your team and your customers',
        id: 'WhatsAppSettings / Purpose / Both',
      }),
    },
  ];

  const onChange = async () => {
    setProblem(null);
    try {
      await change({ variables: { input: { tenantId, accountId: account.id, purpose: chosen } } });
      // Step 2.8, finding 14, in the words the options use.
      const serves = options.find(({ value }) => value === chosen)?.label.toLowerCase();
      toast({
        description: intl.formatMessage(
          { defaultMessage: '{number} now serves {serves}.', id: 'WhatsAppSettings / Purpose / Saved' },
          { number: account.displayPhoneNumber, serves }
        ),
        variant: 'success',
      });
      onChanged();
    } catch (error) {
      setProblem(
        serverReason(error) ??
          intl.formatMessage({
            defaultMessage: "Whom the number serves couldn't be changed. Please try again.",
            id: 'WhatsAppSettings / Purpose / Generic error',
          })
      );
    }
  };

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="space-y-2">
        <label htmlFor={selectId} className="text-sm font-medium">
          <FormattedMessage defaultMessage="Who texts this number" id="WhatsAppSettings / Purpose / Label" />
        </label>
        <select
          id={selectId}
          value={chosen}
          onChange={(event) => setChosen(event.target.value as AccountPurpose)}
          className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
        >
          {options.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      <ConfirmDialog
        title={intl.formatMessage(
          { defaultMessage: 'Change whom {number} serves?', id: 'WhatsAppSettings / Purpose / Confirm title' },
          { number: account.displayPhoneNumber }
        )}
        description={intl.formatMessage({
          defaultMessage:
            "If it stops serving your team, members linked on it are unlinked, and they're customers there from then on. If it stops serving your customers, its store is kept for when it serves them again. Its history is kept.",
          id: 'WhatsAppSettings / Purpose / Confirm description',
        })}
        continueLabel={intl.formatMessage({
          defaultMessage: 'Change whom it serves',
          id: 'WhatsAppSettings / Purpose / Confirm continue',
        })}
        onContinue={onChange}
      >
        <Button variant={ButtonVariant.SECONDARY} disabled={loading || chosen === account.purpose}>
          <FormattedMessage defaultMessage="Change" id="WhatsAppSettings / Purpose / Change" />
        </Button>
      </ConfirmDialog>
      {problem && <p className="w-full text-sm text-destructive">{problem}</p>}
    </div>
  );
};

type ModeSettingProps = {
  tenantId: string;
  accountId: string;
  purpose: AccountPurpose;
  mode: ConversationMode;
  canManage: boolean;
  onChanged: () => void;
};

/**
 * Whether the number's customers get menus or the AI assistant (WhatsApp plan phase 2, decision 2):
 * the number's own setting, since the assistant costs money per message. whatsapp.manage changes it.
 */
const ModeSetting = ({ tenantId, accountId, purpose, mode, canManage, onChanged }: ModeSettingProps) => {
  const intl = useIntl();
  const { toast } = useToast();
  const [problem, setProblem] = useState<string | null>(null);

  // On a number serving both, a linked member's own profile setting decides their mode; this setting
  // is for everyone else (WhatsApp plan Step 2.8, finding 2).
  const membersChoose = purpose === AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS && (
    <p className="text-xs text-muted-foreground">
      <FormattedMessage
        defaultMessage="Members who linked their phone choose their own on their profile page."
        id="WhatsAppSettings / Mode / Members choose"
      />
    </p>
  );
  const [setMode, { loading }] = useMutation(setWhatsAppStorefrontModeMutation);

  const labels = {
    [ConversationMode.WHATSAPP_FORM]: intl.formatMessage({
      defaultMessage: 'Menus',
      id: 'WhatsAppSettings / Mode / Menus',
    }),
    [ConversationMode.AGENTIC]: intl.formatMessage({
      defaultMessage: 'AI assistant',
      id: 'WhatsAppSettings / Mode / Assistant',
    }),
  };

  if (!canManage) {
    return (
      <div className="space-y-1" data-testid={`whatsapp-mode-${accountId}`}>
        <p className="text-sm text-muted-foreground">
          {mode === ConversationMode.AGENTIC ? (
            <FormattedMessage defaultMessage="Customers get the AI assistant." id="WhatsAppSettings / Mode / Gets assistant" />
          ) : (
            <FormattedMessage defaultMessage="Customers get menus." id="WhatsAppSettings / Mode / Gets menus" />
          )}
        </p>
        {membersChoose}
      </div>
    );
  }

  const onChoose = async (chosen: ConversationMode) => {
    setProblem(null);
    try {
      await setMode({ variables: { input: { tenantId, accountId, mode: chosen } } });
      // Saved as soon as it's chosen, so the admin is told it was (WhatsApp plan Step 2.8, finding 14).
      toast({
        description:
          chosen === ConversationMode.AGENTIC
            ? intl.formatMessage({
                defaultMessage: 'Customers now get the AI assistant.',
                id: 'WhatsAppSettings / Mode / Saved assistant',
              })
            : intl.formatMessage({ defaultMessage: 'Customers now get menus.', id: 'WhatsAppSettings / Mode / Saved menus' }),
        variant: 'success',
      });
      onChanged();
    } catch (error) {
      setProblem(
        serverReason(error) ??
          intl.formatMessage({
            defaultMessage: "The setting couldn't be saved. Please try again.",
            id: 'WhatsAppSettings / Mode / Generic error',
          })
      );
    }
  };

  return (
    <fieldset className="space-y-2" data-testid={`whatsapp-mode-${accountId}`}>
      <legend className="text-sm font-medium">
        <FormattedMessage defaultMessage="Customers get" id="WhatsAppSettings / Mode / Legend" />
      </legend>
      <div className="flex flex-wrap gap-4">
        {[ConversationMode.WHATSAPP_FORM, ConversationMode.AGENTIC].map((value) => (
          <label key={value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`whatsapp-mode-${accountId}`}
              value={value}
              checked={mode === value}
              disabled={loading}
              onChange={() => onChoose(value)}
            />
            {labels[value]}
          </label>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        <FormattedMessage
          defaultMessage="The AI assistant calls OpenAI for every customer message, which costs money. Buttons and menu still work with it on."
          id="WhatsAppSettings / Mode / Cost"
        />
      </p>
      {membersChoose}
      {problem && <p className="text-sm text-destructive">{problem}</p>}
    </fieldset>
  );
};

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
