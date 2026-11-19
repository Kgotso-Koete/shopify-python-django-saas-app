/**
 * Tests for which Docker Compose services `pnpm saas up` starts (WhatsApp plan Step 4.6): the five it has
 * always started, plus the ngrok tunnel (a service in docker-compose.local.yml) when NGROK_DOMAIN is set in
 * the root .env. NGROK_DOMAIN is the one switch; a domain without the authtoken is a mistake to name
 * before anything starts, not a tunnel that fails later.
 *
 * Kind of test: unit (agents.md section 2.5). Why: one pure function of the environment it's given;
 * nothing is faked, and neither Docker nor any .env file is touched. It runs against the compiled CLI in
 * dist/, so the package's test script builds first: `pnpm --filter @sb/cli test`.
 */

const { describe, test } = require('node:test');
const assert = require('node:assert/strict');

const ALWAYS = [
  'backend',
  'workers',
  'celery_default',
  'celery_beat',
  'mcp-server',
];
// What upstream's .env.shared lists; the ngrok service lives in docker-compose.local.yml.
const COMPOSE_FILE = 'docker-compose.yml:docker-compose.local.yml';

function composeServices(env) {
  // Required here, not at the top, so a missing module fails each test instead of the whole file.
  return require('../dist/lib/composeServices').composeServices(env);
}

describe('without a tunnel', () => {
  test('no NGROK_DOMAIN starts the five services', () => {
    assert.deepEqual(composeServices({ COMPOSE_FILE }), ALWAYS);
  });

  test('an empty or blank NGROK_DOMAIN counts as none, and needs no authtoken', () => {
    assert.deepEqual(
      composeServices({ COMPOSE_FILE, NGROK_DOMAIN: '' }),
      ALWAYS,
    );
    assert.deepEqual(
      composeServices({ COMPOSE_FILE, NGROK_DOMAIN: '  ' }),
      ALWAYS,
    );
  });
});

describe('with a tunnel', () => {
  test('NGROK_DOMAIN adds ngrok after the five, with COMPOSE_FILE as upstream ships it', () => {
    const env = {
      COMPOSE_FILE,
      NGROK_DOMAIN: 'example.ngrok-free.app',
      NGROK_AUTHTOKEN: 'token',
    };

    assert.deepEqual(composeServices(env), [...ALWAYS, 'ngrok']);
  });

  test('a domain without the authtoken is refused, naming the setting', () => {
    const env = {
      COMPOSE_FILE,
      NGROK_DOMAIN: 'example.ngrok-free.app',
      NGROK_AUTHTOKEN: ' ',
    };

    assert.throws(() => composeServices(env), /NGROK_AUTHTOKEN/);
  });
});
