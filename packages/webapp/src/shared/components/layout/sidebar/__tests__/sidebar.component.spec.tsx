import { TenantType } from '@sb/webapp-api-client/constants';
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { useMediaQuery } from '@sb/webapp-core/hooks';
import { getLocalePath } from '@sb/webapp-core/utils';
import { currentUserPermissionsQuery } from '@sb/webapp-tenants/routes/tenantSettings/tenantRoles/tenantRoles.graphql';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import {
  createMockRouterProps,
  render as renderInTenant,
} from '@sb/webapp-tenants/tests/utils/rendering';
import { screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';

import { RoutesConfig } from '../../../../../app/config/routes';
import { Role } from '../../../../../modules/auth/auth.types';
import { render } from '../../../../../tests/utils/rendering';
import { LayoutContext } from '../../layout.context';
import { Sidebar } from '../sidebar.component';

jest.mock('@sb/webapp-core/hooks', () => {
  const requireActual = jest.requireActual('@sb/webapp-core/hooks');
  const useMediaQuery = jest.fn();
  useMediaQuery.mockImplementation(() => ({
    matches: true,
  }));
  return {
    ...requireActual,
    useMediaQuery,
  };
});

const mockedUseMediaQuery = useMediaQuery as jest.Mock;

const getApolloMocks = (role: Role = Role.USER) => [
  fillCommonQueryWithUser(
    currentUserFactory({
      roles: [role],
    })
  ),
];

describe('Sidebar: Component', () => {
  const Component = () => (
    <LayoutContext.Provider
      value={{
        isSidebarAvailable: true,
        isSideMenuOpen: true,
        isSidebarCollapsed: false,
        setSideMenuOpen: () => null,
        setSidebarCollapsed: () => null,
        toggleSidebar: () => null,
      }}
    >
      <Routes>
        <Route path="/" element={<Sidebar />} />
        <Route path={getLocalePath(RoutesConfig.home)} element={<span>Home mock route</span>} />
      </Routes>
    </LayoutContext.Provider>
  );
  describe('user is logged out', () => {
    it('should not show link to dashboard', async () => {
      const { waitForApolloMocks } = render(<Component />);
      await waitForApolloMocks();
      expect(screen.queryByText(/dashboard/i)).not.toBeInTheDocument();
    });

    it('should show link to privacy policy', async () => {
      render(<Component />);
      expect(await screen.findByText(/privacy policy/i)).toBeInTheDocument();
    });

    it('should not show link to admin page', async () => {
      const { waitForApolloMocks } = render(<Component />);
      await waitForApolloMocks();
      expect(screen.queryByText(/admin panel/i)).not.toBeInTheDocument();
    });
  });

  describe('user is logged in', () => {
    it('should open homepage when clicked on "home" link', async () => {
      const apolloMocks = getApolloMocks();
      const { waitForApolloMocks } = render(<Component />, { apolloMocks });
      await waitForApolloMocks();

      await userEvent.click(await screen.findByLabelText(/home/i));
      expect(screen.getByText('Home mock route')).toBeInTheDocument();
    });

    describe('with user role', () => {
      it('should show link to dashboard', async () => {
        const apolloMocks = getApolloMocks();
        render(<Component />, { apolloMocks });
        expect(await screen.findByText(/dashboard/i)).toBeInTheDocument();
      });

      it('should show link to privacy policy', async () => {
        const apolloMocks = getApolloMocks();
        render(<Component />, { apolloMocks });
        expect(await screen.findByText(/privacy policy/i)).toBeInTheDocument();
      });

      it('should not show link to admin page', async () => {
        const apolloMocks = getApolloMocks();
        const { waitForApolloMocks } = render(<Component />, { apolloMocks });
        await waitForApolloMocks();
        expect(screen.queryByText(/admin panel/i)).not.toBeInTheDocument();
      });

      describe('on desktop', () => {
        it('should not show profile and logout link in sidebar', async () => {
          const apolloMocks = getApolloMocks();
          const { waitForApolloMocks } = render(<Component />, { apolloMocks });
          await waitForApolloMocks();
          expect(screen.queryByText(/profile/i)).not.toBeInTheDocument();
          expect(screen.queryByText(/logout/i)).not.toBeInTheDocument();
        });
      });
    });

    describe('with admin role', () => {
      it('should show link to dashboard', async () => {
        const apolloMocks = getApolloMocks(Role.ADMIN);
        render(<Component />, { apolloMocks });
        expect(await screen.findByText(/dashboard/i)).toBeInTheDocument();
      });

      it('should show link to privacy policy', async () => {
        const apolloMocks = getApolloMocks(Role.ADMIN);
        render(<Component />, { apolloMocks });
        expect(await screen.findByText(/privacy policy/i)).toBeInTheDocument();
      });

      it('should show link to admin page', async () => {
        const apolloMocks = getApolloMocks(Role.ADMIN);
        render(<Component />, { apolloMocks });
        expect(await screen.findByText(/admin panel/i)).toBeInTheDocument();
      });
    });
  });

  // WhatsApp plan Step 1.19: the WhatsApp page has its own item, just under Shopify products, for
  // members with whatsapp.view (the same permission its route needs).
  describe('the WhatsApp item', () => {
    const tenantId = 'tenant-sidebar-whatsapp-1';

    const renderWithPermissions = (permissions: string[]) =>
      renderInTenant(
        <LayoutContext.Provider
          value={{
            isSidebarAvailable: true,
            isSideMenuOpen: true,
            isSidebarCollapsed: false,
            setSideMenuOpen: () => null,
            setSidebarCollapsed: () => null,
            toggleSidebar: () => null,
          }}
        >
          <Sidebar />
        </LayoutContext.Provider>,
        {
          apolloMocks: [
            fillCommonQueryWithUser(
              currentUserFactory({
                tenants: [tenantFactory({ id: tenantId, name: 'Test Org', type: TenantType.ORGANIZATION })],
              })
            ),
            composeMockedQueryResult(currentUserPermissionsQuery, {
              variables: { tenantId },
              data: { currentUserPermissions: permissions },
            }),
          ],
          routerProps: createMockRouterProps(RoutesConfig.home, { tenantId }),
        }
      );

    it('comes right after Shopify products and opens the WhatsApp page', async () => {
      renderWithPermissions(['shopify.view', 'whatsapp.view']);

      const whatsapp = await screen.findByRole('link', { name: /^whatsapp$/i });
      expect(whatsapp).toHaveAttribute('href', expect.stringMatching(new RegExp(`/${tenantId}/whatsapp$`)));
      const labels = screen.getAllByRole('link').map((link) => link.textContent);
      expect(labels[labels.indexOf('Shopify products') + 1]).toBe('WhatsApp');
    });

    it('is hidden without whatsapp.view', async () => {
      renderWithPermissions(['shopify.view']);

      expect(await screen.findByRole('link', { name: /shopify products/i })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /^whatsapp$/i })).not.toBeInTheDocument();
    });
  });
});
