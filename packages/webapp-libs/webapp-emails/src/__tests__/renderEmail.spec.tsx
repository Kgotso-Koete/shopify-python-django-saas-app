// Kind of test: unit (agents.md section 2.5). Why: renderEmail renders one template to a subject and HTML on its
// own, with its built-in translations; nothing else is rendered, and nothing is faked.
import { renderEmail } from '../index';
import { EmailTemplateType } from '../types';

describe('renderEmail', () => {
  // WhatsApp plan, user story WA.D7.OP.J2.A2: the operator is told about Shopify webhooks the sweep gave up on,
  // each with its shop, topic and last error.
  test('WA.D7.OP.J2.A2 SHOPIFY_WEBHOOKS_UNHANDLED', () => {
    const result = renderEmail(
      EmailTemplateType.SHOPIFY_WEBHOOKS_UNHANDLED,
      {
        to: 'ops@example.com',
        deliveries: [
          {
            webhook_id: 'webhook-1',
            topic: 'orders/paid',
            shop_domain: 'acme.myshopify.com',
            received_at: '2026-11-05T10:00:00Z',
            last_error: 'RuntimeError: Shopify said no.',
          },
        ],
      },
      'en'
    );

    expect(result.subject).toContain("Shopify webhooks weren't handled");
    expect(result.html).toContain('acme.myshopify.com');
    expect(result.html).toContain('orders/paid');
    expect(result.html).toContain('RuntimeError: Shopify said no.');
    expect(result.html).toContain('Handle again');
  });

  // WhatsApp plan Step 4.7, user story WA.D7.OP.J2.A1: the operator is told about message templates a business
  // can't use, each with its business, number, template and Meta's reason.
  test('WA.D7.OP.J2.A1 WHATSAPP_TEMPLATES_REFUSED', () => {
    const result = renderEmail(
      EmailTemplateType.WHATSAPP_TEMPLATES_REFUSED,
      {
        to: 'ops@example.com',
        problems: [
          {
            organization: 'Acme Outdoor',
            number: '27000000777',
            template: 'shop_order_paid',
            reason: 'Meta rejected it: INVALID_FORMAT',
          },
        ],
      },
      'en'
    );

    expect(result.subject).toContain("WhatsApp templates can't be used");
    expect(result.html).toContain('Acme Outdoor');
    expect(result.html).toContain('27000000777');
    expect(result.html).toContain('shop_order_paid');
    expect(result.html).toContain('Meta rejected it: INVALID_FORMAT');
    expect(result.html).toContain('whatsapp_publish_order_templates');
  });

  test('ACCOUNT_ACTIVATION', () => {
    const result = renderEmail(
      EmailTemplateType.ACCOUNT_ACTIVATION,
      { to: 'user@example.com', userId: 'user-1', token: 'token-123' },
      'en'
    );

    expect(result.subject).toBeDefined();
    expect(typeof result.subject).toBe('string');
    expect(result.subject.length).toBeGreaterThan(0);
    expect(result.html).toBeDefined();
    expect(typeof result.html).toBe('string');
    expect(result.html).toContain('<html>');
    expect(result.html).toContain('Verify my email');
    expect(result.subject).toContain('Verify your email');
  });

  test('PASSWORD_RESET', () => {
    const result = renderEmail(
      EmailTemplateType.PASSWORD_RESET,
      { to: 'user@example.com', userId: 'user-1', token: 'token-456' },
      'en'
    );

    expect(result.subject).toBeDefined();
    expect(result.html).toBeDefined();
    expect(result.subject).toContain('Reset your password');
  });

  test('converts snake_case keys to camelCase', () => {
    const result = renderEmail(
      EmailTemplateType.ACCOUNT_ACTIVATION,
      { to: 'user@example.com', user_id: 'user-1', token: 'token-123' },
      'en'
    );

    expect(result.subject).toBeDefined();
    expect(result.html).toBeDefined();
  });

  test('TENANT_INVITATION', () => {
    const result = renderEmail(
      EmailTemplateType.TENANT_INVITATION,
      { to: 'user@example.com', token: 'invite-token', tenantMembershipId: 'membership-1' },
      'en'
    );

    expect(result.subject).toContain('invited');
    expect(result.html).toContain('View invitation');
  });

  test('SUBSCRIPTION_ERROR', () => {
    const result = renderEmail(EmailTemplateType.SUBSCRIPTION_ERROR, { to: 'user@example.com' }, 'en');

    expect(result.subject).toContain('payment');
    expect(result.html).toContain('Update payment method');
  });

  test('TRIAL_EXPIRES_SOON', () => {
    const result = renderEmail(
      EmailTemplateType.TRIAL_EXPIRES_SOON,
      { to: 'user@example.com', expiryDate: '2025-03-01' },
      'en'
    );

    expect(result.subject).toContain('trial');
    expect(result.html).toContain('Upgrade now');
  });

  test('USER_EXPORT', () => {
    const result = renderEmail(
      EmailTemplateType.USER_EXPORT,
      { to: 'user@example.com', data: { email: 'user@example.com', export_url: 'https://example.com/export.zip' } },
      'en'
    );

    expect(result.subject).toContain('export');
    expect(result.html).toContain('Download my data');
  });

  test('USER_EXPORT_ADMIN', () => {
    const result = renderEmail(
      EmailTemplateType.USER_EXPORT_ADMIN,
      {
        to: 'admin@example.com',
        data: [
          { email: 'user1@example.com', export_url: 'https://example.com/1.zip' },
          { email: 'user2@example.com', export_url: 'https://example.com/2.zip' },
        ],
      },
      'en'
    );

    expect(result.subject).toContain('Exported');
    expect(result.html).toContain('user1@example.com');
    expect(result.html).toContain('user2@example.com');
  });

  test('INVOICE_REQUEST_ASSIGNED', () => {
    const result = renderEmail(
      EmailTemplateType.INVOICE_REQUEST_ASSIGNED,
      {
        to: 'reviewer@example.com',
        projectName: 'Project A',
        iterationName: 'Iteration 1',
        requestedAmount: '1000',
        currency: 'USD',
        requesterName: 'John Doe',
        isCorrection: false,
        requestUrl: 'https://example.com/request/1',
      },
      'en'
    );

    expect(result.subject).toContain('Assigned');
    expect(result.html).toContain('Review Request');
  });

  test('INVOICE_REQUEST_ASSIGNED correction variant', () => {
    const result = renderEmail(
      EmailTemplateType.INVOICE_REQUEST_ASSIGNED,
      {
        to: 'reviewer@example.com',
        projectName: 'Project A',
        iterationName: '',
        requestedAmount: '500',
        currency: 'EUR',
        requesterName: 'Jane',
        isCorrection: true,
        requestUrl: 'https://example.com/request/2',
      },
      'en'
    );

    expect(result.subject).toContain('Correction');
  });

  test('INVOICE_REQUEST_COMMENT', () => {
    const result = renderEmail(
      EmailTemplateType.INVOICE_REQUEST_COMMENT,
      {
        to: 'user@example.com',
        projectName: 'Project A',
        iterationName: 'Iteration 1',
        commenterName: 'Alice',
        commentContent: 'Please review this request.',
        requestUrl: 'https://example.com/request/1',
      },
      'en'
    );

    expect(result.subject).toContain('Comment');
    expect(result.html).toContain('View Request');
  });

  test('INVOICE_REQUEST_MENTION', () => {
    const result = renderEmail(
      EmailTemplateType.INVOICE_REQUEST_MENTION,
      {
        to: 'user@example.com',
        projectName: 'Project A',
        iterationName: 'Iteration 1',
        commenterName: 'Bob',
        commentContent: 'Hey @[user-1:You] check this',
        requestUrl: 'https://example.com/request/1',
      },
      'en'
    );

    expect(result.subject).toContain('Mentioned');
    expect(result.html).toContain('View Request');
  });

  test('INVOICE_CREATED', () => {
    const result = renderEmail(
      EmailTemplateType.INVOICE_CREATED,
      {
        to: 'user@example.com',
        projectName: 'Project A',
        iterationName: 'Iteration 1',
        invoiceNumber: 'INV-001',
        invoiceAmount: '1500',
        currency: 'USD',
        invoiceUrl: 'https://example.com/invoice/1',
      },
      'en'
    );

    expect(result.subject).toContain('INV-001');
    expect(result.html).toContain('View Invoice');
  });

  test('INVOICE_FILE_ADDED', () => {
    const result = renderEmail(
      EmailTemplateType.INVOICE_FILE_ADDED,
      {
        to: 'user@example.com',
        projectName: 'Project A',
        invoiceNumber: 'INV-002',
        fileName: 'receipt.pdf',
        invoiceUrl: 'https://example.com/invoice/2',
      },
      'en'
    );

    expect(result.subject).toContain('INV-002');
    expect(result.html).toContain('View Invoice');
  });

  test('PROJECT_NOTE_MENTION', () => {
    const result = renderEmail(
      EmailTemplateType.PROJECT_NOTE_MENTION,
      {
        to: 'user@example.com',
        projectName: 'Project Alpha',
        authorName: 'Carol',
        noteContent: 'Important update for the team.',
        projectUrl: 'https://example.com/project/1',
      },
      'en'
    );

    expect(result.subject).toContain('Mentioned');
    expect(result.html).toContain('View Project');
  });
});
