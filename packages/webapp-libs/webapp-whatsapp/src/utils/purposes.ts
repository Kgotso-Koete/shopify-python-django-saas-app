import { AccountPurpose } from '@sb/webapp-api-client/graphql';

// Whom a number serves (WhatsApp plan Step 2.7), as apps/whatsapp/constants.py's AccountPurpose says:
// the team, the customers, or both.

export const servesTeam = (purpose: AccountPurpose) =>
  purpose === AccountPurpose.INTERNAL_COMMUNICATIONS || purpose === AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS;

export const servesCustomers = (purpose: AccountPurpose) =>
  purpose === AccountPurpose.EXTERNAL_COMMUNICATIONS || purpose === AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS;
