import { useIntl } from 'react-intl';

/** Format a ZAR amount (the GraphQL Decimal arrives as a string, e.g. "199.00") in the user's locale. */
export const useFormatZar = () => {
  const intl = useIntl();

  return (amount: string | number | null | undefined) =>
    intl.formatNumber(Number(amount ?? 0), { style: 'currency', currency: 'ZAR' });
};
