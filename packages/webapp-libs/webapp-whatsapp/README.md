# webapp-whatsapp

The web app's WhatsApp screens (WhatsApp plan, Steps 1.6, 1.6b and 1.14):

- the WhatsApp tab in organization settings: connect a number with the form, see its status, send a test message, troubleshoot it, disconnect it
- the WhatsApp section on the profile page: link your own number, choose menus or the assistant, unlink

The plan is `docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md`.

## Running unit tests

Run `pnpm nx run webapp-whatsapp:test --watchAll=false` to execute the unit tests via [Jest](https://jestjs.io/).
