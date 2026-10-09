// Fails when a webapp library with a `test` target (one where `pnpm nx run <library>:test` exists,
// from its project.json targets or its package.json scripts) is missing from the `test-lib` matrix in
// webapp.yml. The matrix is a hand-written list, so a new library used to go untested in CI without
// anyone noticing (docs/superpowers/plans/2026-10-07-restore-green-test-suite-plan.md, step 7.4).
//
// Run from the repository root: node .github/workflows/scripts/check-test-lib-matrix.js

const fs = require('node:fs');
const path = require('node:path');

// Libraries allowed to be missing, each with the reason. Remove an entry once the reason is gone.
const ALLOWED_MISSING = {
  // No tests yet; added to the matrix by the Shopify work
  // (docs/superpowers/plans/2026-10-03-shopify-app-installation-plan.md, step 9).
  'webapp-shopify': 'no tests yet',
};

// The folder names listed under `webapp-lib-name:` in the workflow file.
function parseMatrixLibs(workflowText) {
  const lines = workflowText.split('\n');
  const start = lines.findIndex((line) => line.trim() === 'webapp-lib-name:');
  if (start === -1) return [];
  const libs = [];
  for (const line of lines.slice(start + 1)) {
    const match = line.match(/^\s+-\s+(\S+)\s*$/);
    if (!match) break;
    libs.push(match[1]);
  }
  return libs;
}

// A library has a `test` target if its project.json defines one or its package.json has a `test` script.
function hasTestTarget(libDir) {
  const read = (file) => {
    const full = path.join(libDir, file);
    return fs.existsSync(full) ? JSON.parse(fs.readFileSync(full, 'utf8')) : {};
  };
  return Boolean(read('project.json').targets?.test || read('package.json').scripts?.test);
}

function findMissingLibs(libsWithTests, matrixLibs, allowedMissing = {}) {
  return libsWithTests.filter((lib) => !matrixLibs.includes(lib) && !(lib in allowedMissing)).sort();
}

function main(repoRoot = process.cwd()) {
  const libsRoot = path.join(repoRoot, 'packages', 'webapp-libs');
  const libsWithTests = fs
    .readdirSync(libsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && hasTestTarget(path.join(libsRoot, entry.name)))
    .map((entry) => entry.name);
  const workflow = fs.readFileSync(path.join(repoRoot, '.github', 'workflows', 'webapp.yml'), 'utf8');
  const missing = findMissingLibs(libsWithTests, parseMatrixLibs(workflow), ALLOWED_MISSING);

  if (missing.length > 0) {
    console.error(`Missing from the test-lib matrix in .github/workflows/webapp.yml: ${missing.join(', ')}`);
    return 1;
  }
  const excused = libsWithTests.filter((lib) => lib in ALLOWED_MISSING);
  const excusedText = excused.map((lib) => `${lib} (${ALLOWED_MISSING[lib]})`).join(', ');
  console.log(
    `All ${libsWithTests.length - excused.length} webapp libraries with a test target are in the test-lib matrix.` +
      (excused.length ? ` Allowed to be missing: ${excusedText}.` : '')
  );
  return 0;
}

if (require.main === module) {
  process.exitCode = main();
}

module.exports = { parseMatrixLibs, findMissingLibs, ALLOWED_MISSING };
