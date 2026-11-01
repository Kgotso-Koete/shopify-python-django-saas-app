"""
Tests for apps/whatsapp/services/meta_apps.py: an organization's own Meta apps, and which app each of
its numbers is on (WhatsApp plan Step 2.9, the maintainer's decisions of 2026-11-01).

- an app belongs to one organization; its App ID can be registered only once across the service
- registering stores the App secret encrypted, and generates the app's webhook address id and its
  verify token, which is stored encrypted and can be regenerated; the secret can be updated
- removing an app is refused while a connected number uses it, naming the numbers
- a number is on this service's app (no app) or one of its organization's apps; connecting picks one,
  and a connected number's app can be changed without reconnecting
- another organization's app is "not found", as a missing one is

Kind of test: integration (agents.md section 2.5). Why: apps and numbers are rows in the test database;
only Meta's HTTP, called when a number connects, is mocked.
"""

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory

from ..constants import AccountPurpose
from ..crypto import decrypt_credential
from ..models import MetaApp, WhatsAppAccount
from ..services import accounts, meta_apps
from ..services.accounts import AccountError
from .factories import ExternalAccountFactory, MetaAppFactory
from .fakes import meta_response

pytestmark = pytest.mark.django_db

APP_ID = "1234567890123456"
APP_SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def organization():
    return TenantFactory(type=TenantType.ORGANIZATION)


def register(organization, app_id=APP_ID, app_secret=APP_SECRET):
    return meta_apps.register_app(tenant=organization, app_id=app_id, app_secret=app_secret)


def refusal(call) -> AccountError:
    with pytest.raises(AccountError) as raised:
        call()
    return raised.value


class TestRegistering:
    def test_it_stores_the_secret_encrypted_and_makes_the_address_and_token(self, organization):
        app = register(organization, app_id=f"  {APP_ID} ", app_secret=f" {APP_SECRET}\n")

        app.refresh_from_db()
        assert app.tenant == organization
        assert app.app_id == APP_ID
        assert APP_SECRET not in app.app_secret_encrypted
        assert app.app_secret == APP_SECRET
        # Random, long enough not to be guessed, and safe in an address.
        assert len(app.public_id) >= 20
        assert app.public_id.replace("-", "").replace("_", "").isalnum()
        assert len(app.verify_token) >= 32
        assert app.verify_token not in app.verify_token_encrypted

    def test_each_app_gets_its_own_address_and_token(self, organization):
        first = register(organization)
        second = register(organization, app_id="6543210987654321")

        assert first.public_id != second.public_id
        assert first.verify_token != second.verify_token

    @pytest.mark.parametrize(
        ("app_id", "app_secret", "field"),
        [("", APP_SECRET, "app_id"), (APP_ID, "  ", "app_secret")],
        ids=["no App ID", "no App secret"],
    )
    def test_both_values_are_required(self, organization, app_id, app_secret, field):
        error = refusal(lambda: register(organization, app_id=app_id, app_secret=app_secret))

        assert (error.code, error.field) == ("required", field)
        assert not MetaApp.objects.exists()

    def test_an_app_id_is_digits(self, organization):
        # Meta's App IDs are numbers; anything else is most likely the secret in the wrong field.
        error = refusal(lambda: register(organization, app_id="abc123"))

        assert (error.code, error.field) == ("invalid_app_id", "app_id")

    def test_an_app_another_organization_registered_is_refused(self, organization):
        register(TenantFactory(type=TenantType.ORGANIZATION))

        error = refusal(lambda: register(organization))

        assert str(error) == "This Meta app is already connected to another organization."
        assert (error.code, error.field) == ("already_connected", "app_id")

    def test_registering_the_same_app_twice_is_refused(self, organization):
        register(organization)

        error = refusal(lambda: register(organization))

        assert (error.code, error.field) == ("already_registered", "app_id")


class TestChangingAnApp:
    def test_the_secret_can_be_updated(self, organization):
        app = register(organization)

        meta_apps.update_secret(tenant=organization, meta_app_id=app.pk, app_secret=" new-secret ")

        app.refresh_from_db()
        assert app.app_secret == "new-secret"

    def test_an_updated_secret_is_required(self, organization):
        app = register(organization)

        error = refusal(lambda: meta_apps.update_secret(tenant=organization, meta_app_id=app.pk, app_secret=""))

        assert (error.code, error.field) == ("required", "app_secret")

    def test_the_verify_token_can_be_regenerated_and_the_address_stays(self, organization):
        app = register(organization)
        token, public_id = app.verify_token, app.public_id

        meta_apps.regenerate_verify_token(tenant=organization, meta_app_id=app.pk)

        app.refresh_from_db()
        assert app.verify_token != token
        assert app.public_id == public_id

    def test_another_organizations_app_is_not_found(self, organization):
        app = MetaAppFactory()

        for call in [
            lambda: meta_apps.update_secret(tenant=organization, meta_app_id=app.pk, app_secret="x"),
            lambda: meta_apps.regenerate_verify_token(tenant=organization, meta_app_id=app.pk),
            lambda: meta_apps.remove_app(tenant=organization, meta_app_id=app.pk),
        ]:
            assert refusal(call).code == "app_not_found"


class TestRemoving:
    def test_an_unused_app_is_removed(self, organization):
        app = register(organization)

        meta_apps.remove_app(tenant=organization, meta_app_id=app.pk)

        assert not MetaApp.objects.exists()

    def test_it_is_refused_while_a_connected_number_uses_it_naming_them(self, organization):
        app = register(organization)
        ExternalAccountFactory(tenant=organization, meta_app=app, display_phone_number="+27 83 000 0001")
        ExternalAccountFactory(tenant=organization, meta_app=app, display_phone_number="+27 83 000 0002")

        error = refusal(lambda: meta_apps.remove_app(tenant=organization, meta_app_id=app.pk))

        assert str(error) == "Disconnect its numbers first: +27 83 000 0001, +27 83 000 0002."
        assert error.code == "app_in_use"
        assert MetaApp.objects.filter(pk=app.pk).exists()

    def test_a_disconnected_number_doesnt_keep_it_and_goes_back_to_this_services_app(self, organization):
        app = register(organization)
        number = ExternalAccountFactory(tenant=organization, meta_app=app, is_active=False)

        meta_apps.remove_app(tenant=organization, meta_app_id=app.pk)

        number.refresh_from_db()
        assert number.meta_app is None

    def test_removing_the_organization_removes_its_apps_and_numbers(self, organization):
        ExternalAccountFactory(tenant=organization, meta_app=register(organization))

        organization.delete()

        assert not MetaApp.objects.exists()
        assert not WhatsAppAccount.objects.exists()


class TestANumbersApp:
    def test_a_number_starts_on_this_services_app(self, organization):
        assert ExternalAccountFactory(tenant=organization).meta_app is None

    def test_a_connected_numbers_app_is_changed_and_back(self, organization):
        app = register(organization)
        number = ExternalAccountFactory(tenant=organization)

        meta_apps.set_account_app(tenant=organization, account_id=number.pk, meta_app_id=app.pk)
        number.refresh_from_db()
        assert number.meta_app == app

        meta_apps.set_account_app(tenant=organization, account_id=number.pk, meta_app_id=None)
        number.refresh_from_db()
        assert number.meta_app is None

    def test_another_organizations_app_is_not_found(self, organization):
        number = ExternalAccountFactory(tenant=organization)

        error = refusal(
            lambda: meta_apps.set_account_app(
                tenant=organization, account_id=number.pk, meta_app_id=MetaAppFactory().pk
            )
        )

        assert error.code == "app_not_found"
        number.refresh_from_db()
        assert number.meta_app is None

    def test_another_organizations_number_is_not_found(self, organization):
        app = register(organization)

        error = refusal(
            lambda: meta_apps.set_account_app(
                tenant=organization, account_id=ExternalAccountFactory().pk, meta_app_id=app.pk
            )
        )

        assert error.code == "not_found"

    def test_a_disconnected_numbers_app_isnt_changed(self, organization):
        number = ExternalAccountFactory(tenant=organization, is_active=False)

        error = refusal(
            lambda: meta_apps.set_account_app(
                tenant=organization, account_id=number.pk, meta_app_id=register(organization).pk
            )
        )

        assert error.code == "not_connected"


class TestConnectingWithAnApp:
    @pytest.fixture(autouse=True)
    def meta(self, settings, mocker):
        settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"
        mocker.patch(
            "apps.whatsapp.client.requests.get",
            return_value=meta_response(200, {"display_phone_number": "+27 83 000 0777", "verified_name": "Acme"}),
        )
        mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))

    def connect(self, organization, **app):
        return accounts.connect_account(
            tenant=organization,
            purpose=AccountPurpose.EXTERNAL_COMMUNICATIONS,
            phone_number_id="100000000000777",
            waba_id="200000000000777",
            access_token="EAAGacme-access-token",
            **app,
        ).account

    def test_by_default_a_number_is_on_this_services_app(self, organization):
        assert self.connect(organization).meta_app is None

    def test_a_number_is_connected_on_the_organizations_app(self, organization):
        app = register(organization)

        assert self.connect(organization, meta_app_id=app.pk).meta_app == app

    def test_reconnecting_without_an_app_puts_it_back_on_this_services_app(self, organization):
        app = register(organization)
        self.connect(organization, meta_app_id=app.pk)

        assert self.connect(organization).meta_app is None

    def test_another_organizations_app_is_refused_and_nothing_is_saved(self, organization):
        error = refusal(lambda: self.connect(organization, meta_app_id=MetaAppFactory().pk))

        assert (error.code, error.field) == ("app_not_found", "meta_app_id")
        assert not WhatsAppAccount.objects.exists()


def test_the_secret_and_token_are_kept_under_the_credentials_key(organization):
    app = register(organization)

    assert decrypt_credential(app.app_secret_encrypted) == APP_SECRET
    assert decrypt_credential(app.verify_token_encrypted) == app.verify_token
