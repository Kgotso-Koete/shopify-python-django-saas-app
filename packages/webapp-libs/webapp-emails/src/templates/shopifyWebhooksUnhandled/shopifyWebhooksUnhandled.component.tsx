import { FormattedDate } from '@sb/webapp-core/components/dateTime';
import { FormattedMessage, useIntl } from 'react-intl';

import { Layout } from '../../base';
import { EmailComponentProps } from '../../types';
import { Delivery, Label, Line } from './shopifyWebhooksUnhandled.styles';

/**
 * To the operator (WhatsApp plan, user story WA.D7.OP.J2.A2): Shopify webhooks the sweep gave up on, past
 * Shopify's own retries, each with its shop, topic, when it came and its last error, so the cause can be fixed
 * and the deliveries handled again from the Django admin. Sent by apps/shopify/emails.py. renderEmail camelCases
 * only the top-level keys, so each delivery's keys stay snake_case, as userExportAdmin's export_url does.
 */
export type UnhandledDelivery = {
  webhook_id: string;
  topic: string;
  shop_domain: string;
  received_at: string;
  last_error: string;
};

export type ShopifyWebhooksUnhandledProps = EmailComponentProps & {
  deliveries: Array<UnhandledDelivery>;
};

export const Template = ({ deliveries }: ShopifyWebhooksUnhandledProps) => {
  const intl = useIntl();

  const preheaderText = intl.formatMessage({
    defaultMessage: 'Shopify stopped retrying these webhooks; handle them again once the cause is fixed',
    id: 'Email / Shopify Webhooks Unhandled / Preheader',
  });

  return (
    <Layout
      preheader={preheaderText}
      title={
        <FormattedMessage
          defaultMessage="Shopify webhooks weren't handled"
          id="Email / Shopify Webhooks Unhandled / Title"
        />
      }
      text={
        <FormattedMessage
          defaultMessage="These webhooks still failed after Shopify's retries and three days of the sweep's, so nothing will try them again. Fix the cause, then in the Django admin open Shopify webhook deliveries, filter by Not handled, select them and choose Handle again."
          id="Email / Shopify Webhooks Unhandled / Text"
        />
      }
      footer={{
        companyName: 'SaaS Boilerplate',
      }}
    >
      {deliveries.map((delivery) => (
        <Delivery key={delivery.webhook_id}>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Shop:" id="Email / Shopify Webhooks Unhandled / Shop" />
            </Label>{' '}
            {delivery.shop_domain}
          </Line>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Topic:" id="Email / Shopify Webhooks Unhandled / Topic" />
            </Label>{' '}
            {delivery.topic}
          </Line>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Received:" id="Email / Shopify Webhooks Unhandled / Received" />
            </Label>{' '}
            <FormattedDate value={delivery.received_at} />
          </Line>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Last error:" id="Email / Shopify Webhooks Unhandled / Last error" />
            </Label>{' '}
            {delivery.last_error || (
              <FormattedMessage defaultMessage="none recorded" id="Email / Shopify Webhooks Unhandled / No error" />
            )}
          </Line>
          <Line>
            <Label>
              <FormattedMessage defaultMessage="Webhook id:" id="Email / Shopify Webhooks Unhandled / Webhook id" />
            </Label>{' '}
            {delivery.webhook_id}
          </Line>
        </Delivery>
      ))}
    </Layout>
  );
};

export const Subject = () => (
  <FormattedMessage
    defaultMessage="Shopify webhooks weren't handled: action needed"
    id="Email / Shopify Webhooks Unhandled / Subject"
  />
);
