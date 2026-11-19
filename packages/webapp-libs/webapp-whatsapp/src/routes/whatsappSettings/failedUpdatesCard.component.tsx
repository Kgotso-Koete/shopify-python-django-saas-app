import { useMutation, useQuery } from '@apollo/client/react';
import { WhatsAppOrderStage } from '@sb/webapp-api-client/graphql';
import { Button, ButtonVariant } from '@sb/webapp-core/components/buttons';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { useToast } from '@sb/webapp-core/toast';
import { AlertTriangle, Send } from 'lucide-react';
import { useState } from 'react';
import { FormattedDate, FormattedMessage, useIntl } from 'react-intl';

import {
  sendWhatsAppOrderUpdateAgainMutation,
  whatsAppFailedOrderUpdatesQuery,
} from '../../graphql/failedOrderUpdates.graphql';
import { serverReason } from '../../utils/serverReason';

type FailedUpdatesCardProps = {
  tenantId: string;
  canManage: boolean;
};

/**
 * The order updates WhatsApp couldn't deliver (WhatsApp plan Step 4.7, user story WA.D3.OM.J2.A3): each order
 * stage whose message failed, with the customer, the number, when it failed and Meta's reason in plain words.
 * Once the cause is fixed, whatsapp.manage presses Send again, and the backend asks Shopify for the order and
 * builds the update fresh (decided 2026-11-08). Shown only while there's something to show.
 */
export const FailedUpdatesCard = ({ tenantId, canManage }: FailedUpdatesCardProps) => {
  const { data, refetch } = useQuery(whatsAppFailedOrderUpdatesQuery, {
    variables: { tenantId },
    skip: !tenantId,
  });
  const updates = data?.whatsAppFailedOrderUpdates ?? [];
  if (updates.length === 0) return null;

  return (
    <Card data-testid="whatsapp-failed-updates">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-amber-500" />
          <FormattedMessage defaultMessage="Order updates that didn't go out" id="WhatsAppSettings / Failed updates / Title" />
        </CardTitle>
        <CardDescription>
          <FormattedMessage
            defaultMessage="WhatsApp couldn't deliver these to your customers. Fix the cause, then send each one again: it's built fresh from the order in Shopify."
            id="WhatsAppSettings / Failed updates / Description"
          />
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-md border">
          {updates.map((update) => (
            <FailedUpdateRow
              key={`${update.checkoutId}-${update.stage}`}
              tenantId={tenantId}
              update={update}
              canManage={canManage}
              onSent={() => void refetch()}
            />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
};

type FailedUpdate = {
  checkoutId: string;
  stage: WhatsAppOrderStage;
  number: string;
  customer: string;
  failedAt: unknown;
  reason: string;
};

type FailedUpdateRowProps = {
  tenantId: string;
  update: FailedUpdate;
  canManage: boolean;
  onSent: () => void;
};

const FailedUpdateRow = ({ tenantId, update, canManage, onSent }: FailedUpdateRowProps) => {
  const intl = useIntl();
  const { toast } = useToast();
  const [problem, setProblem] = useState<string | null>(null);
  const [sendAgain, { loading }] = useMutation(sendWhatsAppOrderUpdateAgainMutation);

  const onSendAgain = async () => {
    setProblem(null);
    try {
      await sendAgain({ variables: { input: { tenantId, checkoutId: update.checkoutId, stage: update.stage } } });
      toast({
        description: intl.formatMessage(
          { defaultMessage: 'Sent again to {customer}.', id: 'WhatsAppSettings / Failed updates / Sent' },
          { customer: update.customer }
        ),
        variant: 'success',
      });
      onSent();
    } catch (error) {
      setProblem(
        serverReason(error) ??
          intl.formatMessage({
            defaultMessage: "The update couldn't be sent again. Please try again.",
            id: 'WhatsAppSettings / Failed updates / Generic error',
          })
      );
    }
  };

  return (
    <li className="space-y-2 px-6 py-4" data-testid={`whatsapp-failed-update-${update.checkoutId}-${update.stage}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-sm font-medium">
            {update.stage === WhatsAppOrderStage.PAID ? (
              <FormattedMessage defaultMessage="Order paid" id="WhatsAppSettings / Failed updates / Paid" />
            ) : (
              <FormattedMessage defaultMessage="Order received" id="WhatsAppSettings / Failed updates / Received" />
            )}{' '}
            <FormattedMessage
              defaultMessage="to {customer}, from {number}"
              id="WhatsAppSettings / Failed updates / Who"
              values={{ customer: update.customer, number: update.number }}
            />
          </p>
          <p className="text-xs text-muted-foreground">
            <FormattedMessage defaultMessage="Failed" id="WhatsAppSettings / Failed updates / Failed at" />{' '}
            <FormattedDate value={String(update.failedAt)} dateStyle="medium" timeStyle="short" />
          </p>
          <p className="text-sm">{update.reason}</p>
        </div>
        {canManage && (
          <Button variant={ButtonVariant.SECONDARY} disabled={loading} onClick={onSendAgain}>
            <Send className="mr-1 h-4 w-4" />
            <FormattedMessage defaultMessage="Send again" id="WhatsAppSettings / Failed updates / Send again" />
          </Button>
        )}
      </div>
      {problem && <p className="text-sm text-destructive">{problem}</p>}
    </li>
  );
};
