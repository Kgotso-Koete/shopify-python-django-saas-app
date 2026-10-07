import { TooltipProvider } from '@sb/webapp-core/components/ui/tooltip';
import { Locale } from '@sb/webapp-core/config/i18n';
import { useLocales, useAvailableLocales } from '@sb/webapp-core/hooks';
import { ResponsiveThemeProvider, DynamicIntlProvider } from '@sb/webapp-core/providers';
import { Toaster } from '@sb/webapp-core/toast';
import { CurrentTenantProvider } from '@sb/webapp-tenants/providers';
import { useEffect } from 'react';
import { Helmet } from 'react-helmet-async';
import { useIntl } from 'react-intl';
import { Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';

import { Layout } from '../../../shared/components/layout';
import { withLocale } from './withLocale';

/**
 * Component to render the page title using useIntl (must be inside IntlProvider)
 */
const PageTitle = () => {
  const intl = useIntl();
  const pageTitle = intl.formatMessage({
    defaultMessage: 'Apptension Boilerplate',
    id: 'App / Page title',
  });

  return <Helmet titleTemplate={`%s - ${pageTitle}`} defaultTitle={pageTitle} />;
};

/**
 * Provides validated routes context with locale, theme, and tenant providers.
 */
export const ValidRoutesProviders = () => {
  const params = useParams();
  const navigate = useNavigate();

  const {
    locales: { language },
    setLanguage,
  } = useLocales();

  // Get the dynamic default locale from the API
  const { locales, defaultLocale, isLoading: localesLoading } = useAvailableLocales();
  const location = useLocation();
  const routeLocale = params.lang;
  const isValidRouteLocale = !!routeLocale && locales.some(({ code }) => code === routeLocale);

  useEffect(() => {
    // Wait for locales to load before redirecting
    if (localesLoading) return;

    // A route without a locale (for example /shopify/link) is parsed as if its
    // first segment were the optional locale. Only accept actual locale codes.
    if (!isValidRouteLocale) {
      const targetLocale = defaultLocale;

      // Also set the language in context
      setLanguage(targetLocale as Locale);

      navigate(withLocale(targetLocale, location.pathname, location.search), { replace: true });
      return;
    }

    setLanguage(routeLocale as Locale);
  }, [routeLocale, location, isValidRouteLocale, navigate, defaultLocale, localesLoading, setLanguage]);

  // Show nothing while loading locales or if no language is set
  if (localesLoading || !language) {
    return null;
  }

  return (
    <DynamicIntlProvider locale={language as Locale}>
      <>
        <PageTitle />

        <ResponsiveThemeProvider>
          <CurrentTenantProvider>
            <TooltipProvider>
              <Layout>
                <Outlet />
              </Layout>
            </TooltipProvider>
          </CurrentTenantProvider>
        </ResponsiveThemeProvider>

        <Toaster />
      </>
    </DynamicIntlProvider>
  );
};
