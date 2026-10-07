import { nestedPath } from '@sb/webapp-core/utils';

export const RoutesConfig = {
  shopify: nestedPath('shopify', {
    list: '',
    link: 'link',
  }),
};
