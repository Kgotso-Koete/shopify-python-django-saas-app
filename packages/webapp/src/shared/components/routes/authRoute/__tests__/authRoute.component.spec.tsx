import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { screen } from '@testing-library/react';
import { Route, Routes, useSearchParams } from 'react-router-dom';

import { Role } from '../../../../../modules/auth/auth.types';
import { render } from '../../../../../tests/utils/rendering';
import { AuthRoute, AuthRouteProps } from '../authRoute.component';

describe('AuthRoute: Component', () => {
  const defaultProps: AuthRouteProps = {};

  const Component = (props: Partial<AuthRouteProps>) => (
    <Routes>
      <Route path="/" element={<AuthRoute {...defaultProps} {...props} />}>
        <Route index element={<span data-testid="content" />} />
      </Route>
      <Route path="/en/auth/login" element={<span data-testid="login-content" />} />
      <Route path="/en/404" element={<span data-testid="404-content" />} />
    </Routes>
  );

  describe('user profile is fetched', () => {
    describe('no allowedRoles prop is specified', () => {
      it('should render content', async () => {
        const apolloMocks = [
          fillCommonQueryWithUser(
            currentUserFactory({
              roles: [Role.ADMIN],
            })
          ),
        ];
        render(<Component />, { apolloMocks });
        expect(await screen.findByTestId('content')).toBeInTheDocument();
      });
    });

    describe('user has required role', () => {
      it('should render content', async () => {
        const apolloMocks = [
          fillCommonQueryWithUser(
            currentUserFactory({
              roles: [Role.ADMIN],
            })
          ),
        ];
        render(<Component allowedRoles={Role.ADMIN} />, { apolloMocks });
        expect(await screen.findByTestId('content')).toBeInTheDocument();
      });
    });

    describe('user doesnt have required role', () => {
      it('should redirect to not found page', async () => {
        const apolloMocks = [
          fillCommonQueryWithUser(
            currentUserFactory({
              roles: [Role.USER],
            })
          ),
        ];
        render(<Component allowedRoles={Role.ADMIN} />, { apolloMocks });
        expect(await screen.findByTestId('404-content')).toBeInTheDocument();
        expect(screen.queryByTestId('content')).not.toBeInTheDocument();
      });
    });

    describe('user is not logged in', () => {
      it('should redirect to login page', async () => {
        render(<Component allowedRoles={Role.ADMIN} />);
        expect(await screen.findByTestId('login-content')).toBeInTheDocument();
        expect(screen.queryByTestId('content')).not.toBeInTheDocument();
      });

      // Added in this fork: a link such as Shopify's /shopify/link?claim=… must survive the login, or
      // the merchant lands on the page without its claim
      // (docs/superpowers/plans/2026-10-03-shopify-app-installation-plan.md, section 4.2, decision E).
      it('should keep the query string in the redirect back after login', async () => {
        const LoginRedirectParam = () => {
          const [search] = useSearchParams();
          return <span data-testid="login-redirect">{search.get('redirect')}</span>;
        };

        render(
          <Routes>
            <Route path="/en/shopify/link" element={<AuthRoute />}>
              <Route index element={<span data-testid="content" />} />
            </Route>
            <Route path="/en/auth/login" element={<LoginRedirectParam />} />
          </Routes>,
          { routerProps: { initialEntries: ['/en/shopify/link?claim=abc123'] } }
        );

        expect(await screen.findByTestId('login-redirect')).toHaveTextContent('/en/shopify/link?claim=abc123');
      });
    });
  });
});
