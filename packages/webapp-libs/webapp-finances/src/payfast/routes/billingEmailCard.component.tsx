import { useMutation, useQuery } from '@apollo/client/react';
import { Button } from '@sb/webapp-core/components/buttons';
import { Input } from '@sb/webapp-core/components/forms';
import { Paragraph } from '@sb/webapp-core/components/typography';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@sb/webapp-core/components/ui/card';
import { usePermissionCheck } from '@sb/webapp-tenants/hooks';
import { useCurrentTenant } from '@sb/webapp-tenants/providers';
import { Mail } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { payfastTenantBillingEmailQuery, payfastUpdateBillingEmailMutation } from '../payfast.graphql';

/**
 * The organization's billing email (WhatsApp plan, user story WA.D6.OM.J1.A1). The organization pays, so PayFast
 * bills the organization's email, never whoever presses Pay: this one, or its creator's when it's empty, as
 * Tenant.email gives Stripe's customer. It's saved through upstream's updateTenant mutation, so changing it needs
 * org.settings.edit, the permission that mutation checks; anyone else sees it read-only.
 */
export const PayfastBillingEmailCard = () => {
  const intl = useIntl();
  const { data: currentTenant } = useCurrentTenant();
  const { hasPermission: canEdit } = usePermissionCheck('org.settings.edit');
  const { data } = useQuery(payfastTenantBillingEmailQuery, {
    variables: { id: currentTenant?.id ?? '' },
    skip: !currentTenant,
  });
  const billingEmail = data?.tenant?.billingEmail ?? null;
  const [value, setValue] = useState('');
  const [saved, setSaved] = useState<string | null>(null);
  const [save, { loading, error }] = useMutation(payfastUpdateBillingEmailMutation, {
    onCompleted: (result) => setSaved(result.updateTenant?.tenant?.billingEmail ?? ''),
  });

  useEffect(() => {
    if (billingEmail !== null) setValue(billingEmail);
  }, [billingEmail]);

  if (!currentTenant || billingEmail === null) return null;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSaved(null);
    // updateTenant requires the name; it's saved unchanged. tenantId names the organization for the backend's tenant
    // middleware, which ignores a plain id, so without it the save finds no organization (WhatsApp plan Step 4.7).
    save({
      variables: {
        input: {
          id: currentTenant.id,
          tenantId: currentTenant.id,
          name: currentTenant.name ?? '',
          billingEmail: value.trim(),
        },
      },
    });
  };

  const creatorIsBilled = (
    <FormattedMessage
      id="PayFast / My subscription / Billing email creator"
      defaultMessage="None set, so PayFast bills the email of the person who created the organization."
    />
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mail className="h-5 w-5" />
          <FormattedMessage id="PayFast / My subscription / Billing email header" defaultMessage="Billing email" />
        </CardTitle>
        <CardDescription>
          <FormattedMessage
            id="PayFast / My subscription / Billing email description"
            defaultMessage="PayFast bills this email for the organization's plan and donations, whoever pays."
          />
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {canEdit ? (
          <form onSubmit={onSubmit} className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <Input
              type="text"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              label={intl.formatMessage({
                id: 'PayFast / My subscription / Billing email label',
                defaultMessage: 'Billing email:',
              })}
              error={
                error
                  ? intl.formatMessage({
                      id: 'PayFast / My subscription / Billing email error',
                      defaultMessage: "That billing email couldn't be saved. Check it's a valid email address.",
                    })
                  : undefined
              }
            />
            <Button type="submit" disabled={loading} className="w-full sm:w-fit">
              <FormattedMessage id="PayFast / My subscription / Billing email save" defaultMessage="Save" />
            </Button>
          </form>
        ) : (
          billingEmail && <Paragraph>{billingEmail}</Paragraph>
        )}
        {!billingEmail && saved === null && <Paragraph>{creatorIsBilled}</Paragraph>}
        {saved !== null && (
          <Paragraph>
            {saved ? (
              <FormattedMessage
                id="PayFast / My subscription / Billing email saved"
                defaultMessage="Saved. PayFast bills {email} from now on."
                values={{ email: saved }}
              />
            ) : (
              <FormattedMessage
                id="PayFast / My subscription / Billing email cleared"
                defaultMessage="Saved. PayFast bills the email of the person who created the organization from now on."
              />
            )}
          </Paragraph>
        )}
      </CardContent>
    </Card>
  );
};
