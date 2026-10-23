import pytest
from cryptography.fernet import Fernet
from django.conf import settings


@pytest.fixture(autouse=True)
def whatsapp_encryption_key(monkeypatch):
    """
    Give every WhatsApp test a fresh, random credential encryption key (plan decision D5), so
    models that store access tokens and app secrets can encrypt them. A test that needs a missing
    or different key sets its own with monkeypatch, which overrides this one.
    """
    monkeypatch.setattr(settings, "WHATSAPP_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))


@pytest.fixture
def celery_keeps_the_test_connection():
    """
    For tests that run a Celery task with apply(): config/celery.py closes the database connection
    before and after every task (close_old_connections), which inside the test's transaction closes
    the connection the test is using. These receivers are disconnected for the test only, so it can
    stay in the normal test transaction; config/celery.py itself is untouched.

    The alternative, transaction=True, empties every table when the test ends, data migrations' rows
    included, and --reuse-db carries that into the next run (found 2026-10-17).
    """
    from celery.signals import task_postrun, task_prerun

    from config import celery

    task_prerun.disconnect(celery.close_db_connections_before_task)
    task_postrun.disconnect(celery.close_db_connections_after_task)
    yield
    task_prerun.connect(celery.close_db_connections_before_task)
    task_postrun.connect(celery.close_db_connections_after_task)
