#!/usr/bin/env node
/*
 * Fork addition (WhatsApp plan, 2026-11-07): counts each user story's passing frontend tests, by kind of
 * test, for the "Tests passing" column of the plan's user stories file (docs/superpowers/plans/user-stories/).
 * The backend's counts come from packages/backend/tests/user_stories.py.
 *
 * A Jest test names its story at the start of its title or of a describe around it, such as
 * `describe('WA.D3.OM.J1.A3 the store an external number sells from', …)`. Its kind comes from the
 * "Kind of test:" comment at the top of its file (agents.md section 2.5): frontend unit (FU) or
 * integration (FI).
 *
 * Usage: Jest writes its results with `--json --outputFile=<absolute path>`; pass one or more such files:
 *
 *   node scripts/user-story-tests.js logs/jest-webapp-whatsapp.json logs/jest-webapp-finances.json
 *
 * It prints one line per story, such as `WA.D3.OM.J1.A3: 0/0 (FU), 14/14 (FI)`, passed out of run.
 * A failed test counts in the total, not in passed; a skipped or todo test counts in neither.
 *
 * Test-support code, so it has no tests of its own (agents.md section 2.1).
 */

const fs = require('fs');

const STORY = /WA\.D\d+\.[A-Z]{2}\.J\d+\.A\d+/g;
const KIND = /Kind of test:\s*(unit|integration)/i;
const LETTERS = { unit: 'FU', integration: 'FI' };

const counts = {}; // story id -> kind letter -> [passed, run]
const kinds = {}; // test file -> kind letter

function kindOf(file) {
  if (!(file in kinds)) {
    const match = KIND.exec(fs.readFileSync(file, 'utf8').slice(0, 2000));
    kinds[file] = match ? LETTERS[match[1].toLowerCase()] : '?';
  }
  return kinds[file];
}

for (const resultsFile of process.argv.slice(2)) {
  const results = JSON.parse(fs.readFileSync(resultsFile, 'utf8'));
  for (const testFile of results.testResults) {
    for (const test of testFile.assertionResults) {
      if (test.status !== 'passed' && test.status !== 'failed') continue;
      const names = [...test.ancestorTitles, test.title].join(' ');
      const stories = new Set(names.match(STORY) || []);
      if (stories.size === 0) continue;
      const kind = kindOf(testFile.name);
      for (const story of stories) {
        counts[story] = counts[story] || {};
        counts[story][kind] = counts[story][kind] || [0, 0];
        counts[story][kind][1] += 1;
        if (test.status === 'passed') counts[story][kind][0] += 1;
      }
    }
  }
}

for (const story of Object.keys(counts).sort()) {
  const parts = ['FU', 'FI', '?']
    .filter((kind) => counts[story][kind])
    .map((kind) => `${counts[story][kind][0]}/${counts[story][kind][1]} (${kind})`);
  console.log(`${story}: ${parts.join(', ')}`);
}
