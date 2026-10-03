"""
Cloudflare R2 file links must come from R2 settings only (common/storages.py).

The R2 storages set their own endpoint, keys and bucket, but used R2_CUSTOM_DOMAIN only when it was
set; otherwise they inherited AWS_S3_CUSTOM_DOMAIN. docker-compose.local.yml sets that to LocalStack's
"localhost:4566/test-bucket", so locally every R2 file link pointed at LocalStack, which doesn't have
the file (NoSuchKey; seen 2026-10-03). On Render that variable isn't set, so links were right there.
"""

import pytest
from django.test import override_settings

from common.storages import CloudflareR2Storage, PublicCloudflareR2Storage

pytestmark = pytest.mark.django_db

R2_SETTINGS = {
    "R2_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET_NAME": "my-bucket",
    "AWS_S3_REGION_NAME": "auto",
    # What docker-compose.local.yml gives the backend for LocalStack.
    "AWS_S3_CUSTOM_DOMAIN": "localhost:4566/test-bucket",
}

R2_STORAGES = [PublicCloudflareR2Storage, CloudflareR2Storage]


@pytest.mark.parametrize("storage_class", R2_STORAGES)
def test_r2_links_ignore_the_aws_custom_domain(storage_class):
    with override_settings(**R2_SETTINGS, R2_CUSTOM_DOMAIN=None):
        storage = storage_class()
        url = storage.url("documents/abc/photo.jpeg")

    assert storage.custom_domain is None
    # Only the absence of LocalStack's address is checked: the test suite mocks S3 link building
    # (bucket and keys in the generated link come from the mock), so the exact link isn't meaningful here.
    assert "localhost:4566" not in url


@pytest.mark.parametrize("storage_class", R2_STORAGES)
def test_r2_links_use_the_r2_custom_domain_when_set(storage_class):
    with override_settings(**R2_SETTINGS, R2_CUSTOM_DOMAIN="files.example.com"):
        storage = storage_class()

    assert storage.custom_domain == "files.example.com"
