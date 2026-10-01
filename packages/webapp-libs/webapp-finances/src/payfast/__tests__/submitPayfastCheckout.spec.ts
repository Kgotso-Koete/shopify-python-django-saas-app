import { submitPayfastCheckout } from '../submitPayfastCheckout';

// PayFast checkouts are an HTML form POSTed to PayFast's process URL
// (https://developers.payfast.co.za/docs#step_3_pay_on_payfast), not a JavaScript SDK call.
describe('submitPayfastCheckout', () => {
  let submit: jest.SpyInstance;

  beforeEach(() => {
    // jsdom doesn't implement navigation, so form submission is observed instead of performed.
    submit = jest.spyOn(HTMLFormElement.prototype, 'submit').mockImplementation(() => undefined);
  });

  afterEach(() => {
    submit.mockRestore();
    document.body.innerHTML = '';
  });

  it('posts every signed field, unchanged, to the action URL', () => {
    submitPayfastCheckout({
      actionUrl: 'https://sandbox.payfast.co.za/eng/process',
      fields: { merchant_id: '10000100', item_name: 'Monthly plan', signature: 'abc123' },
    });

    const form = document.querySelector('form') as HTMLFormElement;
    expect(form.method).toBe('post');
    expect(form.action).toBe('https://sandbox.payfast.co.za/eng/process');
    const inputs = Array.from(form.querySelectorAll('input')).map((input) => [input.type, input.name, input.value]);
    expect(inputs).toEqual([
      ['hidden', 'merchant_id', '10000100'],
      ['hidden', 'item_name', 'Monthly plan'],
      ['hidden', 'signature', 'abc123'],
    ]);
    expect(submit).toHaveBeenCalledTimes(1);
  });
});
