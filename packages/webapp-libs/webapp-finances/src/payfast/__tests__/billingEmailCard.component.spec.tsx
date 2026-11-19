// Tests for the organization's billing email on the PayFast Subscriptions page (WhatsApp plan, user story
// WA.D6.OM.J1.A1): PayFast bills the organization's email, so an Owner sets which one. It shows the billing email,
// or says the organization's creator is billed when none is set; members with org.settings.edit, the permission
// upstream's updateTenant mutation needs, can change it; anyone else sees it read-only.
//
// Kind of test: integration (agents.md section 2.5). Why: the card renders with the real Apollo hooks, router and
// translations; the backend is Apollo's MockedProvider, and the permission check is mocked per test.
import { currentUserFactory, fillCommonQueryWithUser } from '@sb/webapp-api-client/tests/factories';
import { composeMockedQueryResult } from '@sb/webapp-api-client/tests/utils';
import { tenantFactory } from '@sb/webapp-tenants/tests/factories/tenant';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RoutesConfig } from '../../config/routes';
import { createMockRouterProps, render } from '../../tests/utils/rendering';
import { payfastTenantBillingEmailQuery, payfastUpdateBillingEmailMutation } from '../payfast.graphql';
import { PayfastBillingEmailCard } from '../routes/billingEmailCard.component';

let mockCanEditSettings = true;
jest.mock('@sb/webapp-tenants/hooks', () => ({
  ...jest.requireActual('@sb/webapp-tenants/hooks'),
  usePermissionCheck: (code: string) => ({
    hasPermission: code === 'org.settings.edit' ? mockCanEditSettings : true,
    loading: false,
  }),
}));

const tenantId = 'tenantId';
const tenantMock = () =>
  fillCommonQueryWithUser(currentUserFactory({ tenants: [tenantFactory({ id: tenantId, name: 'Acme' })] }));
const billingEmailMock = (billingEmail: string) =>
  composeMockedQueryResult(payfastTenantBillingEmailQuery, {
    variables: { id: tenantId },
    data: { tenant: { id: tenantId, billingEmail, __typename: 'TenantType' } },
  });
// The request names the organization with tenantId too: the backend's tenant middleware finds it only from an
// explicit tenantId, never a plain id, so without it the save finds no organization (human check J3.3, 2026-11-19;
// apps/payfast/tests/test_billing_email.py proves it through the real GraphQL view). The mock matches these exact
// variables, so a request without tenantId gets no answer.
const saveMock = (billingEmail: string) =>
  composeMockedQueryResult(payfastUpdateBillingEmailMutation, {
    variables: { input: { id: tenantId, tenantId, name: 'Acme', billingEmail } },
    data: {
      updateTenant: {
        tenant: { id: tenantId, name: 'Acme', billingEmail, __typename: 'TenantType' },
        __typename: 'UpdateTenantMutationPayload',
      },
    },
  });

const renderCard = (mocks: ReturnType<typeof composeMockedQueryResult>[]) =>
  render(<PayfastBillingEmailCard />, {
    routerProps: createMockRouterProps(RoutesConfig.subscriptions.index, { tenantId }),
    apolloMocks: [tenantMock(), ...mocks],
  });

const CREATOR_IS_BILLED = /None set, so PayFast bills the email of the person who created the organization/;

describe('WA.D6.OM.J1.A1 Billing email on the PayFast Subscriptions page', () => {
  beforeEach(() => {
    mockCanEditSettings = true;
  });

  it('shows the billing email read-only to a member without org.settings.edit', async () => {
    mockCanEditSettings = false;
    renderCard([billingEmailMock('accounts@acme.example')]);

    expect(await screen.findByText('accounts@acme.example')).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save/i })).not.toBeInTheDocument();
  });

  it('says the organization creator is billed when no billing email is set', async () => {
    mockCanEditSettings = false;
    renderCard([billingEmailMock('')]);

    expect(await screen.findByText(CREATOR_IS_BILLED)).toBeInTheDocument();
  });

  it('lets a member with org.settings.edit save a new billing email', async () => {
    const user = userEvent.setup();
    const save = saveMock('accounts@acme.example');
    renderCard([billingEmailMock(''), save]);

    const input = await screen.findByRole('textbox', { name: /billing email/i });
    await user.type(input, 'accounts@acme.example');
    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(save.result).toHaveBeenCalled());
    expect(await screen.findByText(/Saved\. PayFast bills accounts@acme\.example from now on\./)).toBeInTheDocument();
  });
});
