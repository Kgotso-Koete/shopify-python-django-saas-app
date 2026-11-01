import { Lock } from 'lucide-react';
import { ReactNode } from 'react';
import { FormattedMessage } from 'react-intl';
import { Link } from 'react-router-dom';

import { useGenerateTenantPath } from '../../hooks/useGenerateTenantPath';
import { usePermissionCheck } from '../../hooks/usePermissionCheck';

// The Subscriptions page, as webapp-finances' RoutesConfig.subscriptions names it. Written out here,
// since this library doesn't depend on webapp-finances.
const SUBSCRIPTIONS_PATH = 'subscriptions';

export type PlanRequiredNoticeProps = {
  // The feature's name as the page shows it, such as "WhatsApp".
  feature: string;
  // What happens to the organization's data, such as its numbers being kept (decision 3).
  children?: ReactNode;
};

/**
 * Shown on a feature's page while the organization's plan doesn't include it (WhatsApp plan phase 3,
 * decision 5): the page stays, read-only, with one way back. Whoever may change the plan
 * (billing.manage, the Owner by default) gets a link to choose one; everyone else is told to ask the
 * owner, since Admins can view billing but not change it.
 */
export const PlanRequiredNotice = ({ feature, children }: PlanRequiredNoticeProps) => {
  const { hasPermission: canChoosePlan } = usePermissionCheck('billing.manage');
  const generateTenantPath = useGenerateTenantPath();

  return (
    <div
      className="space-y-2 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm dark:border-amber-700 dark:bg-amber-950/30"
      data-testid="plan-required"
    >
      <p className="flex items-center gap-2 font-medium">
        <Lock className="h-4 w-4" />
        <FormattedMessage
          defaultMessage="Your plan doesn't include {feature}."
          id="PlanRequiredNotice / Title"
          values={{ feature }}
        />
      </p>
      {children && <p className="text-muted-foreground">{children}</p>}
      {canChoosePlan ? (
        <Link to={generateTenantPath(SUBSCRIPTIONS_PATH)} className="font-medium text-primary underline">
          <FormattedMessage defaultMessage="Choose a plan" id="PlanRequiredNotice / Choose a plan" />
        </Link>
      ) : (
        <p>
          <FormattedMessage
            defaultMessage="Ask the organization's owner to choose a plan."
            id="PlanRequiredNotice / Ask the owner"
          />
        </p>
      )}
    </div>
  );
};
