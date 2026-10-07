import { withLocale } from '../withLocale';

describe('withLocale', () => {
  it('prefixes a path that has no locale', () => {
    expect(withLocale('en', '/shopify/link', '?claim=abc')).toBe('/en/shopify/link?claim=abc');
  });

  it('keeps every segment of a tenant path', () => {
    // React Router reads "VGVuYW50" as the optional locale and "shopify" as the tenant id here,
    // so a path rebuilt from route params loses "shopify". The full pathname must be kept.
    expect(withLocale('en', '/VGVuYW50/shopify', '?connected=store.myshopify.com')).toBe(
      '/en/VGVuYW50/shopify?connected=store.myshopify.com'
    );
  });

  it('turns the root path into the locale root', () => {
    expect(withLocale('en', '/', '')).toBe('/en/');
  });
});
