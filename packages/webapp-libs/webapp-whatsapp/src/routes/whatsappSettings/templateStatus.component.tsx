import { TemplateStatus } from '@sb/webapp-api-client/graphql';
import { CheckCircle2, Circle, XCircle } from 'lucide-react';
import { ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

export type WhatsAppTemplate = {
  name: string;
  status: TemplateStatus;
  // Meta's reason as Meta sends it, such as "INVALID_FORMAT"; empty unless it's rejected.
  rejectedReason: string;
  statusCheckedAt?: unknown;
};

type TemplateStatusPanelProps = {
  accountId: string;
  templates: WhatsAppTemplate[];
};

/**
 * Whether Meta approved the number's message templates, such as the order updates a store customer gets more
 * than 24 hours after their last message (WhatsApp plan Step 4.7, user story WA.D3.OM.J2.A2). The status comes
 * from Meta's API, asked when the page opens (decided 2026-11-08). While one isn't approved, it says late order
 * updates fail; a rejection shows Meta's reason in plain words, and that the operator has been told
 * (user story WA.D7.OP.J2.A1). A number with no templates shows nothing.
 */
export const TemplateStatusPanel = ({ accountId, templates }: TemplateStatusPanelProps) => {
  const intl = useIntl();
  if (templates.length === 0) return null;

  // The one order template each number has since decision 30 (WhatsApp plan Step 4.7), apps/whatsapp_shop/
  // templates.py's ORDER_UPDATE. Any other name, such as a retired template not yet deleted, shows as Meta names it.
  const labelOf = (name: string) => {
    if (name === 'shop_order_update') {
      return intl.formatMessage({ defaultMessage: 'Order update', id: 'WhatsAppSettings / Templates / Order update' });
    }
    return name;
  };
  const statusOf = (status: TemplateStatus) =>
    ({
      [TemplateStatus.IN_REVIEW]: intl.formatMessage({ defaultMessage: 'In review', id: 'WhatsAppSettings / Templates / In review' }),
      [TemplateStatus.APPROVED]: intl.formatMessage({ defaultMessage: 'Approved', id: 'WhatsAppSettings / Templates / Approved' }),
      [TemplateStatus.REJECTED]: intl.formatMessage({ defaultMessage: 'Rejected', id: 'WhatsAppSettings / Templates / Rejected' }),
      [TemplateStatus.PAUSED]: intl.formatMessage({ defaultMessage: 'Paused', id: 'WhatsAppSettings / Templates / Paused' }),
      [TemplateStatus.DISABLED]: intl.formatMessage({ defaultMessage: 'Disabled', id: 'WhatsAppSettings / Templates / Disabled' }),
    })[status];

  const notApproved = templates.some(({ status }) => status !== TemplateStatus.APPROVED);
  const rejected = templates.filter(({ status }) => status === TemplateStatus.REJECTED);

  return (
    <div className="space-y-2" data-testid={`whatsapp-templates-${accountId}`}>
      <p className="text-sm font-medium">
        <FormattedMessage defaultMessage="Order update templates" id="WhatsAppSettings / Templates / Heading" />
      </p>
      <ul className="flex flex-wrap gap-2">
        {templates.map(({ name, status }) => (
          <li key={name} data-testid={`whatsapp-template-${name}`}>
            <StatusBadge status={status}>
              {labelOf(name)}: {statusOf(status)}
            </StatusBadge>
          </li>
        ))}
      </ul>
      {notApproved && (
        <p className="text-xs text-muted-foreground">
          <FormattedMessage
            defaultMessage="Order updates sent more than 24 hours after a customer's last message fail until Meta approves every template. Meta usually decides within a day."
            id="WhatsAppSettings / Templates / Not approved"
          />
        </p>
      )}
      {rejected.map(({ name, rejectedReason }) => (
        <p key={name} className="text-xs text-destructive">
          <FormattedMessage
            defaultMessage="Meta rejected {template}: {reason}. The operator has been told and will submit it again."
            id="WhatsAppSettings / Templates / Rejected reason"
            values={{ template: labelOf(name), reason: plainReason(rejectedReason) }}
          />
        </p>
      ))}
    </div>
  );
};

/** Meta's reason code in plain words: "INVALID_FORMAT" reads "invalid format". */
const plainReason = (reason: string) => (reason ? reason.toLowerCase().split('_').join(' ') : 'no reason given');

const StatusBadge = ({ status, children }: { status: TemplateStatus; children: ReactNode }) => {
  if (status === TemplateStatus.APPROVED) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
        <CheckCircle2 className="h-3 w-3" />
        {children}
      </span>
    );
  }
  if (status === TemplateStatus.IN_REVIEW) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
        <Circle className="h-3 w-3" />
        {children}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:text-red-400">
      <XCircle className="h-3 w-3" />
      {children}
    </span>
  );
};
