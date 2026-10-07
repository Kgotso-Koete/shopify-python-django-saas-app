"""
Helpers shared by the Shopify tests.
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
    with that variable set. All the requested settings are read in one subprocess.

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
