import { nestedPath } from '@sb/webapp-core/utils';

export const RoutesConfig = {
  home: '/',
  tenant: nestedPath('tenant', {
    settings: nestedPath('settings', {
      members: 'members',
      general: 'general',
      security: 'security',
      activityLogs: 'activity-logs',
      roles: 'roles',
      backup: 'backup',
      // The WhatsApp tab (WhatsApp plan Step 1.6); its screens are in @sb/webapp-whatsapp.
      whatsapp: 'whatsapp',
    }),
    accessDenied: 'access-denied',
  }),
};
