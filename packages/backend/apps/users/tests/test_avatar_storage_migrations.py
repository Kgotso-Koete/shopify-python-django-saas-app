"""
The avatar fields' migrations must not depend on which storage backend is configured.

UserAvatar's ImageFields choose their storage from STORAGE_BACKEND (common.storages.get_public_storage).
Called at import time, that choice is written into migrations, so `makemigrations --check` passed only
with the STORAGE_BACKEND the last migration was created with, and failed everywhere else (CI, tests,
other machines; seen 2026-10-02). Passed as a callable, as get_public_storage's docstring says, the
migration records only the function and stays the same in every environment.
"""

import os
import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.django_db

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("storage_backend", ["s3", "r2", "local"])
def test_no_avatar_migration_is_missing_for_any_storage_backend(storage_backend):
    env = {**os.environ, "STORAGE_BACKEND": storage_backend}

    result = subprocess.run(  # noqa: S603 - fixed arguments
        [sys.executable, "manage.py", "makemigrations", "users", "--check", "--dry-run"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
