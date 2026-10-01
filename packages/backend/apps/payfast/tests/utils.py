"""
Helpers shared by the PayFast tests.
"""

import json
import os
import pathlib
import subprocess
import sys

# packages/backend, the directory that contains the `config` package.
BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]


def read_settings(names, **env_overrides):
    """
    Import config.settings in a fresh interpreter and return {name: repr(value)} for `names`.

    Django reads config/settings.py once, at import time, so the only clean way to prove that a
    setting is read from an environment variable is to import the settings again in a new process
    with that variable set (docs/superpowers/agents.md, rule 2.3). All the requested settings are
    read in one subprocess because importing the settings takes several seconds.

    The subprocess inherits this process's environment (it already holds everything settings.py
    needs), with `env_overrides` on top. An override of None removes the variable, so a test can
    check the default used when it is unset.
    """
    env = os.environ.copy()
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value

    script = (
        "import json, config.settings as s; "
        f"print(json.dumps({{name: repr(getattr(s, name)) for name in {list(names)!r}}}))"
    )
    # The script is built in this file from setting names the tests pass, not from outside input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    # settings.py may print warnings first, so the JSON is the last line of output.
    return json.loads(result.stdout.strip().splitlines()[-1])


def signed_itn_body(pairs, passphrase="jt7NOE43FZPn") -> bytes:  # noqa: S107 (PayFast's public sandbox passphrase)
    """
    Build a form-encoded ITN body from ordered (key, value) pairs and sign it the way PayFast does
    (https://developers.payfast.co.za/docs#step_4_confirm_payment): every field in order, blanks
    included, PHP-style URL encoding, passphrase appended, MD5. The signature goes last.
    """
    from .. import signature

    param_string = "&".join(f"{key}={signature.php_urlencode(value)}" for key, value in pairs)
    sig = signature._md5(f"{param_string}&passphrase={signature.php_urlencode(passphrase)}")
    return f"{param_string}&signature={sig}".encode()


def itn_pairs(**fields):
    """Ordered ITN fields with realistic defaults for a completed payment, in PayFast's order."""
    defaults = {
        "m_payment_id": "",
        "pf_payment_id": "1089250",
        "payment_status": "COMPLETE",
        "item_name": "Monthly plan",
        "item_description": "",
        "amount_gross": "199.00",
        "amount_fee": "-4.58",
        "amount_net": "194.42",
        "custom_str1": "",
        "name_first": "Test",
        "name_last": "Buyer",
        "email_address": "buyer@example.com",
        "merchant_id": "10000100",
        "token": "",
        "billing_date": "",
    }
    unknown = set(fields) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown ITN fields: {unknown}")
    return list({**defaults, **fields}.items())
