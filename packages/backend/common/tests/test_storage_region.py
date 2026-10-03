"""
Tests for AWS_S3_REGION_NAME in config/settings.py, the region the S3-compatible storages
(common/storages.py) send.

Cloudflare R2 accepts only its own region names ("auto", "weur", ...). Without this setting the
storage library falls back to AWS_DEFAULT_REGION, which docker-compose.yml sets to "eu-west-1" for
LocalStack, so every R2 upload failed locally with InvalidRegionName (seen 2026-10-02).

Settings are evaluated once per process, so the loader tests import config.settings in a fresh
Python subprocess with the environment they want (docs/superpowers/agents.md, rule 2.3).
"""

import os
import pathlib
import subprocess
import sys

import pytest
from django.test import override_settings

from common.storages import CloudflareR2Storage, PublicCloudflareR2Storage

# The root conftest.py registers fixtures that need the database for every test.
pytestmark = pytest.mark.django_db

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]


def read_setting(name, **env_overrides):
    """repr() of one setting, read by importing config.settings in a new interpreter."""
    env = os.environ.copy()
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    result = subprocess.run(  # noqa: S603 - fixed arguments built in this file
        [sys.executable, "-c", f"import config.settings as s; print(repr(s.{name}))"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


class TestRegionSetting:
    def test_reads_the_env_var(self):
        assert read_setting("AWS_S3_REGION_NAME", AWS_S3_REGION_NAME="auto") == "'auto'"

    def test_defaults_to_none_so_existing_deployments_are_unchanged(self):
        # None lets the storage library keep using AWS_DEFAULT_REGION, as before this setting existed.
        assert read_setting("AWS_S3_REGION_NAME", AWS_S3_REGION_NAME=None) == "None"


class TestR2StorageRegion:
    @pytest.mark.parametrize("storage_class", [PublicCloudflareR2Storage, CloudflareR2Storage])
    def test_r2_storages_send_the_configured_region_over_aws_default_region(self, monkeypatch, storage_class):
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        r2_settings = {
            "AWS_S3_REGION_NAME": "auto",
            "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
            "R2_ACCESS_KEY_ID": "key",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET_NAME": "bucket",
        }
        with override_settings(**r2_settings):
            # The region the storage passes to boto3 (S3Storage.connection uses region_name=self.region_name).
            # Not the client's own meta: the test suite's AWS mock reports its own region there.
            region = storage_class().region_name

        assert region == "auto"
