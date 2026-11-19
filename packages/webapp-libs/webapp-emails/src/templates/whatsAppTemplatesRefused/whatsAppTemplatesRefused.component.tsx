import { FormattedMessage, useIntl } from 'react-intl';

import { Layout } from '../../base';
import { EmailComponentProps } from '../../types';
import { Label, Line, Problem } from './whatsAppTemplatesRefused.styles';

/**
 * To the operator (WhatsApp plan Step 4.7, user story WA.D7.OP.J2.A1): message templates a business can't use,
 * because Meta rejected them or refused their submission, each with its business, number and Meta's reason.
 * Late order updates to that business's customers fail until it's fixed. Sent by apps/whatsapp/emails.py.
 * renderEmail camelCases only the top-level keys; each problem's keys are single words, so none changes.
 */
export type TemplateProblem = {
  organization: string;
  number: string;
  template: string;
  reason: string;
};

export type WhatsAppTemplatesRefusedProps = EmailComponentProps & {
  problems: Array<TemplateProblem>;
};

export const Template = ({ problems }: WhatsAppTemplatesRefusedProps) => {
  const intl = useIntl();

  const preheaderText = intl.formatMessage({
    defaultMessage: "Late order updates fail until these templates are fixed and Meta approves them",
    id: 'Email / WhatsApp Templates Refused / Preheader',
  });

  return (
    <Layout
      preheader={preheaderText}
      title={
        <FormattedMessage
          defaultMessage="WhatsApp templates can't be used"
          id="Email / WhatsApp Templates Refused / Title"
        />
      }
      text={
        <FormattedMessage
          defaultMessage="Order updates sent more than 24 hours after a customer's last message fail on these numbers until it's fixed. A rejected template: change its wording in apps/whatsapp_shop/templates.py and deploy. A refused submission: check the number's access token on the business's WhatsApp page. Then run whatsapp_publish_order_templates, and Meta reviews it again."
          id="Email / WhatsApp Templates Refused / Text"
        />
      }
      footer={{
        companyName: 'SaaS Boilerplate',
      }}
    >
      {problems.map((problem) => (
        <Problem key={`${problem.number}-${problem.template}`}>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Business:" id="Email / WhatsApp Templates Refused / Business" />
            </Label>{' '}
            {problem.organization}
          </Line>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Number:" id="Email / WhatsApp Templates Refused / Number" />
            </Label>{' '}
            {problem.number}
          </Line>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Template:" id="Email / WhatsApp Templates Refused / Template" />
            </Label>{' '}
            {problem.template}
          </Line>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Meta's reason:" id="Email / WhatsApp Templates Refused / Reason" />
            </Label>{' '}
            {problem.reason}
          </Line>
        </Problem>
      ))}
    </Layout>
  );
};

export const Subject = () => (
  <FormattedMessage
    defaultMessage="WhatsApp templates can't be used: action needed"
    id="Email / WhatsApp Templates Refused / Subject"
  />
);
