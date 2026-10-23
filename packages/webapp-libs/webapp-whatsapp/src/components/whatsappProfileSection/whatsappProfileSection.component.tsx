import type { ApolloCache } from '@apollo/client';
import { useMutation, useQuery } from '@apollo/client/react';
import { ConversationMode } from '@sb/webapp-api-client/graphql';
import { Button, ButtonVariant } from '@sb/webapp-core/components/buttons';
import { ConfirmDialog } from '@sb/webapp-core/components/confirmDialog';
import { Input } from '@sb/webapp-core/components/forms';
import { AlertTriangle, CheckCircle2, ExternalLink } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { FormattedDate, FormattedMessage, FormattedTime, useIntl } from 'react-intl';

import {
  disconnectWhatsAppMutation,
  startWhatsAppLinkMutation,
  updateWhatsAppConversationModeMutation,
  whatsAppLinksQuery,
} from '../../graphql/whatsappIdentity.graphql';
import { serverReason } from '../../utils/serverReason';

type StartedLink = { code: string; link: string; maskedNumber: string; expiresAt: unknown };

type Link = {
  tenantId: string;
  organizationName: string;
  internalNumber: string;
  linked: boolean;
  maskedNumber?: string | null;
  conversationMode?: ConversationMode | null;
  linkedAt?: unknown;
};

/**
 * The WhatsApp section of the profile page (WhatsApp plan Steps 1.14 and 1.17, user stories 1 and 3):
 * one block per organization of the user's whose team texts an internal communications number.
 *
 * Linking takes two proofs at once: this logged-in page asks for a code for the number typed, and the
 * code must then be sent from that number, as "link 123456", to the organization's internal number.
 * Once linked, the user picks menus and forms or the AI assistant there, and can unlink, which also
 * forgets the conversation on that number.
 */
export const WhatsAppProfileSection = () => {
  const { data, loading, error, refetch } = useQuery(whatsAppLinksQuery);

  if (loading && !data) {
    return <div className="h-24 animate-pulse rounded bg-muted" />;
  }
  if (error || !data) {
    // A failed load must not look like "not linked".
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="whatsapp-identity-error">
        <AlertTriangle className="h-4 w-4 text-amber-500" />
        <FormattedMessage
          defaultMessage="Couldn't load your WhatsApp links. Please refresh the page."
          id="WhatsAppProfile / Load error"
        />
      </p>
    );
  }

  const links = data.whatsAppLinks;
  if (links.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        <FormattedMessage
          defaultMessage="Use this app from WhatsApp once one of your organizations connects its internal communications number. An admin connects it on the organization's WhatsApp page."
          id="WhatsAppProfile / No internal number"
        />
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {links.map((link) => (
        <section key={link.tenantId} className="space-y-3 rounded-md border p-4" data-testid={`whatsapp-link-${link.tenantId}`}>
          <p className="text-sm">
            {/* Elements passed as values reach React as a list, so each needs a key (Step 1.21). */}
            <FormattedMessage
              defaultMessage="{organization}: its team texts {number}."
              id="WhatsAppProfile / Organization"
              values={{
                organization: <strong key="organization">{link.organizationName}</strong>,
                number: <strong key="number">{link.internalNumber}</strong>,
              }}
            />
          </p>
          {link.linked ? <LinkedNumber link={link} /> : <LinkANumber tenantId={link.tenantId} onCheckAgain={() => void refetch()} />}
        </section>
      ))}
    </div>
  );
};

/** Put the link the server sent back in the cached list, in place of the organization's old one. */
const replaceLink = (cache: ApolloCache, updated: Link | undefined) => {
  if (!updated) return;
  cache.updateQuery({ query: whatsAppLinksQuery }, (cached) =>
    cached
      ? {
          whatsAppLinks: cached.whatsAppLinks.map((link) => (link.tenantId === updated.tenantId ? updated : link)),
        }
      : cached
  );
};

const LinkANumber = ({ tenantId, onCheckAgain }: { tenantId: string; onCheckAgain: () => void }) => {
  const intl = useIntl();
  const [phoneNumber, setPhoneNumber] = useState('');
  const [problem, setProblem] = useState<string>();
  const [started, setStarted] = useState<StartedLink | null>(null);
  const [startLink, { loading }] = useMutation(startWhatsAppLinkMutation);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setProblem(undefined);
    try {
      const { data } = await startLink({ variables: { input: { tenantId, phoneNumber } } });
      if (data?.startWhatsAppLink) setStarted(data.startWhatsAppLink);
    } catch (error) {
      setProblem(
        serverReason(error) ??
          intl.formatMessage({
            defaultMessage: "Couldn't start linking. Please try again.",
            id: 'WhatsAppProfile / Link / Generic error',
          })
      );
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        <FormattedMessage
          defaultMessage="Use this organization from WhatsApp: its items and products, with menus or the AI assistant."
          id="WhatsAppProfile / Link / Explanation"
        />
      </p>
      <form className="flex flex-wrap items-end gap-2" onSubmit={onSubmit}>
        <div className="min-w-[14rem] flex-1">
          <Input
            value={phoneNumber}
            onChange={(event) => setPhoneNumber(event.target.value)}
            label={intl.formatMessage({ defaultMessage: 'Your WhatsApp number', id: 'WhatsAppProfile / Link / Number' })}
            placeholder="083 123 4567"
            error={problem}
            autoComplete="tel"
          />
        </div>
        <Button type="submit" disabled={loading || !phoneNumber}>
          <FormattedMessage defaultMessage="Get a link code" id="WhatsAppProfile / Link / Submit" />
        </Button>
      </form>

      {started && (
        <div className="space-y-3 rounded-md border p-4">
          <p className="text-sm">
            <FormattedMessage
              defaultMessage="From {number}, send this code on WhatsApp to the number above, as {message}. It works once, until {time}."
              id="WhatsAppProfile / Link / Instructions"
              values={{
                number: <strong key="number">{started.maskedNumber}</strong>,
                message: <code key="message">link {started.code}</code>,
                time: <FormattedTime key="time" value={String(started.expiresAt)} />,
              }}
            />
          </p>
          <p className="text-3xl font-semibold tracking-widest">{started.code}</p>
          <div className="flex flex-wrap gap-2">
            <a
              href={started.link}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              <ExternalLink className="h-4 w-4" />
              <FormattedMessage defaultMessage="Open WhatsApp" id="WhatsAppProfile / Link / Open" />
            </a>
            <Button type="button" variant={ButtonVariant.SECONDARY} onClick={onCheckAgain}>
              <FormattedMessage defaultMessage="I've sent it" id="WhatsAppProfile / Link / Check again" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

const LinkedNumber = ({ link }: { link: Link }) => {
  const intl = useIntl();
  const { tenantId, linkedAt } = link;
  const maskedNumber = link.maskedNumber ?? '';
  const mode = link.conversationMode ?? null;
  const [problem, setProblem] = useState<string>();
  const [updateMode, { loading: savingMode }] = useMutation(updateWhatsAppConversationModeMutation, {
    // The saved link replaces the cached one, so the choice shows as soon as it's saved.
    update: (cache, { data }) => replaceLink(cache, data?.updateWhatsAppConversationMode?.link),
  });
  const [unlink] = useMutation(disconnectWhatsAppMutation, {
    update: (cache, { data }) => replaceLink(cache, data?.disconnectWhatsApp?.link),
  });

  const onChooseMode = async (chosen: ConversationMode) => {
    setProblem(undefined);
    try {
      await updateMode({ variables: { input: { tenantId, mode: chosen } } });
    } catch (error) {
      setProblem(serverReason(error));
    }
  };

  const modes = [
    {
      value: ConversationMode.WHATSAPP_FORM,
      label: intl.formatMessage({ defaultMessage: 'Menus and forms', id: 'WhatsAppProfile / Mode / Menus' }),
    },
    {
      value: ConversationMode.AGENTIC,
      label: intl.formatMessage({ defaultMessage: 'AI assistant', id: 'WhatsAppProfile / Mode / Assistant' }),
    },
  ];

  return (
    <div className="space-y-4">
      <p className="flex items-center gap-2 text-sm" data-testid="whatsapp-linked">
        <CheckCircle2 className="h-4 w-4 text-green-600" />
        <FormattedMessage
          defaultMessage="Linked to {number} since {date}."
          id="WhatsAppProfile / Linked"
          values={{
            number: <strong key="number">{maskedNumber}</strong>,
            date: <FormattedDate key="date" value={String(linkedAt)} dateStyle="medium" />,
          }}
        />
      </p>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">
          <FormattedMessage defaultMessage="How you talk to the app on WhatsApp" id="WhatsAppProfile / Mode / Legend" />
        </legend>
        {modes.map(({ value, label }) => (
          <label key={value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`whatsapp-conversation-mode-${tenantId}`}
              value={value}
              checked={mode === value}
              disabled={savingMode}
              onChange={() => onChooseMode(value)}
            />
            {label}
          </label>
        ))}
        {mode === null && (
          <p className="text-xs text-muted-foreground">
            <FormattedMessage
              defaultMessage="Not chosen yet, so the service's default applies. You can also switch in chat with mode menu or mode ai."
              id="WhatsAppProfile / Mode / Default"
            />
          </p>
        )}
        {problem && <p className="text-sm text-destructive">{problem}</p>}
      </fieldset>

      <ConfirmDialog
        title={intl.formatMessage({ defaultMessage: 'Unlink your WhatsApp number?', id: 'WhatsAppProfile / Unlink / Title' })}
        description={intl.formatMessage({
          defaultMessage:
            "The app stops answering this number, and your conversation there is forgotten, the assistant's history included.",
          id: 'WhatsAppProfile / Unlink / Description',
        })}
        continueLabel={intl.formatMessage({ defaultMessage: 'Unlink my number', id: 'WhatsAppProfile / Unlink / Continue' })}
        variant="destructive"
        onContinue={() => void unlink({ variables: { input: { tenantId } } })}
      >
        <Button variant={ButtonVariant.SECONDARY}>
          <FormattedMessage defaultMessage="Unlink" id="WhatsAppProfile / Unlink / Button" />
        </Button>
      </ConfirmDialog>
    </div>
  );
};
