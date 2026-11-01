/**
 * The generated GraphQL client keeps the repo's patch, so a query missing from the generated list
 * fails loudly instead of returning {} (restore-green plan section 9). `pnpm saas up` starts a
 * watcher that regenerated gql.ts without the patch, and on 2026-10-31 it nearly went into a commit
 * that way.
 */
import config from '../../../graphql/codegen';
import { gql } from '../__generated/gql/gql';

describe('Generated GraphQL types', () => {
  it("type generation patches gql.ts after every write, the watcher's included", () => {
    // The code generator runs afterAllFileWrite hooks after it writes, in the one-off run and in
    // watch mode alike: https://the-guild.dev/graphql/codegen/docs/config-reference/lifecycle-hooks
    const hooks = config.hooks?.afterAllFileWrite;
    const commands = Array.isArray(hooks) ? hooks : [hooks];

    expect(commands.some((command) => typeof command === 'string' && command.includes('scripts/patch-gql.js'))).toBe(
      true
    );
  });

  it("the generated gql() throws for a query it doesn't know", () => {
    // The committed file itself: CI fails if an unpatched gql.ts is ever committed.
    expect(() => gql('query notInTheGeneratedList { nothing }')).toThrow(/GraphQL query not found/);
  });
});
