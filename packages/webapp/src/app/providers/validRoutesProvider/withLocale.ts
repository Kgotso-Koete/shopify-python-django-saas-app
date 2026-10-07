/**
 * Builds the URL for a path that has no locale yet, keeping the whole pathname and query.
 *
 * The path is not rebuilt from route params: React Router shares one params object across
 * nested routes, so each splat (`*`) overwrites the one above it, and segments go missing.
 */
export const withLocale = (locale: string, pathname: string, search: string) =>
  `/${locale}${pathname}${search}`;
