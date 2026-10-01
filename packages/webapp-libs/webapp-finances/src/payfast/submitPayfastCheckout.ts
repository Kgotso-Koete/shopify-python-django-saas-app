export type PayfastCheckout = {
  actionUrl: string;
  fields: Record<string, string>;
};

/**
 * Send the buyer to PayFast's payment page. PayFast checkouts are a plain HTML form POST with the
 * signed fields from the backend (https://developers.payfast.co.za/docs#step_3_pay_on_payfast), so
 * this builds a hidden form and submits it. The fields are posted exactly as signed: changing any
 * of them would invalidate the signature.
 */
export const submitPayfastCheckout = ({ actionUrl, fields }: PayfastCheckout) => {
  const form = document.createElement('form');
  form.method = 'POST';
  form.action = actionUrl;
  form.style.display = 'none';

  Object.entries(fields).forEach(([name, value]) => {
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = name;
    input.value = String(value);
    form.appendChild(input);
  });

  document.body.appendChild(form);
  form.submit();
};
