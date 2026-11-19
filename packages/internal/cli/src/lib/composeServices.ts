/**
 * Fork addition (WhatsApp plan Step 4.6): the Docker Compose services `saas up` starts.
 *
 * Always the five upstream starts; plus `ngrok`, the tunnel in docker-compose.local.yml that lets Meta's
 * and Shopify's webhooks reach this machine, when NGROK_DOMAIN is set in the root .env. NGROK_DOMAIN is
 * the one switch. A domain without its authtoken is refused here with the setting to fix, rather than
 * leaving a tunnel that fails after everything has started.
 *
 * Kept free of other CLI modules (config/env.ts reads the root .env when imported) so it can be tested
 * as a pure function: test/composeServices.test.js.
 */

const ALWAYS = [
  'backend',
  'workers',
  'celery_default',
  'celery_beat',
  'mcp-server',
];

export function composeServices(env: NodeJS.ProcessEnv): string[] {
  if (!env.NGROK_DOMAIN?.trim()) {
    return [...ALWAYS];
  }

  if (!env.NGROK_AUTHTOKEN?.trim()) {
    throw new Error(
      'NGROK_DOMAIN is set but NGROK_AUTHTOKEN is empty. Add your authtoken to the root .env ' +
        '(https://dashboard.ngrok.com/get-started/your-authtoken), or empty NGROK_DOMAIN to run without the tunnel.',
    );
  }

  return [...ALWAYS, 'ngrok'];
}
