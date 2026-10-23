// Tests for the WhatsApp section of the profile page (WhatsApp plan Steps 1.14 and 1.17, user stories 1
// and 3): one link per organization of the user's with an internal communications number, each with
// its own code, mode and Unlink.
//
// Kind of test: integration (agents.md section 2.5). Why: the section renders with the real Apollo hooks;
// the backend is Apollo's MockedProvider, answering with the shapes apps/whatsapp/schema.py sends, its
// errors included.
import type { MockedResponse } from '@apollo/client/testing';
import { ConversationMode } from '@sb/webapp-api-client/graphql';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { render } from '@sb/webapp-tenants/tests/utils/rendering';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { GraphQLError } from 'graphql';

import {
  disconnectWhatsAppMutation,
  startWhatsAppLinkMutation,
  updateWhatsAppConversationModeMutation,
  whatsAppLinksQuery,
} from '../../../graphql/whatsappIdentity.graphql';
import { WhatsAppProfileSection } from '../whatsappProfileSection.component';

type Link = {
  tenantId: string;
  organizationName: string;
  internalNumber: string;
  linked: boolean;
  maskedNumber?: string | null;
  conversationMode?: ConversationMode | null;
  linkedAt?: string | null;
};

const link = (overrides: Partial<Link> = {}) => ({
  tenantId: 'acme-id',
  organizationName: 'Acme',
  internalNumber: '+27 00 000 0805',
  linked: false,
  maskedNumber: null,
  conversationMode: null,
  linkedAt: null,
  __typename: 'WhatsAppLinkType',
  ...overrides,
});

const LINKED = link({
  linked: true,
  maskedNumber: '*******4567',
  conversationMode: ConversationMode.WHATSAPP_FORM,
  linkedAt: '2026-10-19T08:30:00+00:00',
});

const STARTED = {
  code: '123456',
  link: 'https://wa.me/27000000805?text=link%20123456',
  maskedNumber: '*******4567',
  expiresAt: '2026-10-20T09:10:00+00:00',
  __typename: 'StartWhatsAppLink',
};

const linksMock = (links: ReturnType<typeof link>[]) =>
  composeMockedQueryResult(whatsAppLinksQuery, { data: { whatsAppLinks: links } });

const renderSection = (mocks: MockedResponse[]) =>
  render(<WhatsAppProfileSection />, { apolloMocks: [fillCommonQueryWithUser(currentUserFactory()), ...mocks] });

const organization = (tenantId = 'acme-id') => screen.findByTestId(`whatsapp-link-${tenantId}`);

describe('WhatsAppProfileSection: Component', () => {
  it('says who connects a number when none of the user’s organizations has one', async () => {
    renderSection([linksMock([])]);

    expect(await screen.findByText(/an admin connects it on the organization's whatsapp tab/i)).toBeInTheDocument();
  });

  it('shows each organization, with the number its team texts', async () => {
    renderSection([
      linksMock([LINKED, link({ tenantId: 'beta-id', organizationName: 'Beta', internalNumber: '+27 00 000 0806' })]),
    ]);

    const acme = await organization('acme-id');
    expect(acme).toHaveTextContent('Acme');
    expect(acme).toHaveTextContent('+27 00 000 0805');
    expect(within(acme).getByTestId('whatsapp-linked')).toHaveTextContent('*******4567');
    const beta = await organization('beta-id');
    expect(beta).toHaveTextContent('Beta');
    expect(within(beta).getByLabelText(/your whatsapp number/i)).toBeInTheDocument();
  });

  describe('not linked', () => {
    it('shows the code and a link that opens WhatsApp with it typed, for that organization', async () => {
      const user = userEvent.setup();
      renderSection([
        linksMock([link()]),
        composeMockedQueryResult(startWhatsAppLinkMutation, {
          variables: { input: { tenantId: 'acme-id', phoneNumber: '083 123 4567' } },
          data: { startWhatsAppLink: STARTED },
        }),
      ]);

      const acme = within(await organization());
      await user.type(acme.getByLabelText(/your whatsapp number/i), '083 123 4567');
      await user.click(acme.getByRole('button', { name: /get a link code/i }));

      expect(await acme.findByText('123456')).toBeInTheDocument();
      expect(acme.getByText(/\*{7}4567/)).toBeInTheDocument();
      expect(acme.getByRole('link', { name: /open whatsapp/i })).toHaveAttribute('href', STARTED.link);
    });

    it("shows the backend's reason under the number", async () => {
      const user = userEvent.setup();
      const reason = "That doesn't look like a phone number.";
      renderSection([
        linksMock([link()]),
        composeMockedQueryResult(startWhatsAppLinkMutation, {
          variables: { input: { tenantId: 'acme-id', phoneNumber: 'call me' } },
          data: null,
          errors: [
            new GraphQLError('GraphQlValidationError', {
              extensions: { phone_number: [{ message: reason, code: 'invalid_phone_number' }] },
            }),
          ],
        }),
      ]);

      const acme = within(await organization());
      await user.type(acme.getByLabelText(/your whatsapp number/i), 'call me');
      await user.click(acme.getByRole('button', { name: /get a link code/i }));

      expect(await acme.findByText(reason)).toBeInTheDocument();
    });

    it('checks again for the link once the message is sent', async () => {
      const user = userEvent.setup();
      renderSection([
        linksMock([link()]),
        composeMockedQueryResult(startWhatsAppLinkMutation, {
          variables: { input: { tenantId: 'acme-id', phoneNumber: '083 123 4567' } },
          data: { startWhatsAppLink: STARTED },
        }),
        linksMock([LINKED]),
      ]);

      const acme = within(await organization());
      await user.type(acme.getByLabelText(/your whatsapp number/i), '083 123 4567');
      await user.click(acme.getByRole('button', { name: /get a link code/i }));
      await user.click(await acme.findByRole('button', { name: /i've sent it/i }));

      expect(await screen.findByTestId('whatsapp-linked')).toHaveTextContent('*******4567');
    });
  });

  describe('linked', () => {
    it('shows the masked number, when it was linked and the chosen mode', async () => {
      renderSection([linksMock([LINKED])]);

      const linked = await screen.findByTestId('whatsapp-linked');
      expect(linked).toHaveTextContent('*******4567');
      expect(linked).toHaveTextContent(/2026/);
      expect(screen.getByRole('radio', { name: /menus and forms/i })).toBeChecked();
      expect(screen.getByRole('radio', { name: /ai assistant/i })).not.toBeChecked();
    });

    it('saves a change of mode for that organization', async () => {
      const user = userEvent.setup();
      const modeMock = composeMockedQueryResult(updateWhatsAppConversationModeMutation, {
        variables: { input: { tenantId: 'acme-id', mode: ConversationMode.AGENTIC } },
        data: {
          updateWhatsAppConversationMode: {
            link: { ...LINKED, conversationMode: ConversationMode.AGENTIC },
            __typename: 'UpdateWhatsAppConversationMode',
          },
        },
      });
      renderSection([linksMock([LINKED]), modeMock]);

      await user.click(await screen.findByRole('radio', { name: /ai assistant/i }));

      await waitFor(() => expect(modeMock.result).toHaveBeenCalled());
      expect(await screen.findByRole('radio', { name: /ai assistant/i })).toBeChecked();
    });

    it('says when no mode is chosen, so the default applies', async () => {
      renderSection([linksMock([{ ...LINKED, conversationMode: null }])]);

      expect(await screen.findByText(/default applies/i)).toBeInTheDocument();
    });

    it('unlinks only after the user confirms', async () => {
      const user = userEvent.setup();
      const unlinkMock = composeMockedQueryResult(disconnectWhatsAppMutation, {
        variables: { input: { tenantId: 'acme-id' } },
        data: { disconnectWhatsApp: { link: link(), __typename: 'DisconnectWhatsApp' } },
      });
      renderSection([linksMock([LINKED]), unlinkMock]);

      await user.click(await screen.findByRole('button', { name: /^unlink$/i }));
      await user.click(await screen.findByRole('button', { name: /cancel/i }));
      expect(unlinkMock.result).not.toHaveBeenCalled();

      await user.click(screen.getByRole('button', { name: /^unlink$/i }));
      await user.click(await screen.findByRole('button', { name: /unlink my number/i }));

      expect(await screen.findByLabelText(/your whatsapp number/i)).toBeInTheDocument();
    });
  });

  it("says the links couldn't be loaded, rather than offering to link", async () => {
    renderSection([
      composeMockedQueryResult(whatsAppLinksQuery, { data: null, errors: [new GraphQLError('Something went wrong')] }),
    ]);

    expect(await screen.findByTestId('whatsapp-identity-error')).toBeInTheDocument();
    expect(screen.queryByLabelText(/your whatsapp number/i)).not.toBeInTheDocument();
  });
});
