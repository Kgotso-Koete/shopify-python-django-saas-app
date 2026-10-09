const assert = require('node:assert/strict');
const { parseMatrixLibs, findMissingLibs } = require('./check-test-lib-matrix');

const workflow = `
      matrix:
        node-version: [ 22, 24 ]
        webapp-lib-name:
          - webapp-core
          - webapp-tenants
    steps:
      - uses: actions/checkout@v3
`;

// Reads only the list under webapp-lib-name:, and stops at the next key
assert.deepEqual(parseMatrixLibs(workflow), ['webapp-core', 'webapp-tenants']);

// No webapp-lib-name: key -> nothing listed
assert.deepEqual(parseMatrixLibs('jobs:\n  build:\n'), []);

// Every library with tests is listed -> nothing missing
assert.deepEqual(findMissingLibs(['webapp-core', 'webapp-tenants'], ['webapp-core', 'webapp-tenants']), []);

// A library with tests that the matrix leaves out is reported
assert.deepEqual(findMissingLibs(['webapp-sso', 'webapp-core'], ['webapp-core']), ['webapp-sso']);

// An allowed exception is not reported
assert.deepEqual(findMissingLibs(['webapp-shopify'], [], { 'webapp-shopify': 'no tests yet' }), []);

console.log('check-test-lib-matrix.test.js: all assertions passed');
