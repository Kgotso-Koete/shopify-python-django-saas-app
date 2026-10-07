import { asyncComponent } from '@sb/webapp-core/utils/asyncComponent';

export const ShopifyShops = asyncComponent(() => import('./shopifyShops'));
export const ShopifyLink = asyncComponent(() => import('./shopifyLink'));
