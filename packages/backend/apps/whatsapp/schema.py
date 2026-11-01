"""
The WhatsApp tab's GraphQL API (plan Step 1.5f, user story 11), modelled on apps/shopify/schema.py.

- whatsAppAccounts lists the organization's numbers and their status; it needs whatsapp.view.
- connectWhatsAppAccount, sendWhatsAppTestMessage, disconnectWhatsAppAccount and
  changeWhatsAppNumberPurpose (Step 2.7) need whatsapp.manage (plan D16).
- whatsAppMetaApps and the Meta app mutations (Step 2.9) need whatsapp.manage; the list holds each
  app's webhook address and verify token, never its App secret.

The organization is always the one the tenant middleware checked the user belongs to
(info.context.tenant), never one taken from the input. The work is in services/accounts.py; this
module only checks permissions, calls it and shapes the answer. No secret is ever a field here.
"""

import graphene
from graphql_relay import from_global_id, to_global_id

from apps.multitenancy.models import Tenant, TenantMembership
from common.acl.policies import IsAuthenticatedFullAccess, IsTenantMemberAccess
from common.graphql import exceptions
from common.graphql.acl import permission_classes, requires

from .constants import TEAM_PURPOSES, AccountPurpose, ConnectionMethod, ConversationMode
from .models import MetaApp, WhatsAppAccount, WhatsAppIdentity
from .services import accounts, identity, meta_apps, number_tools
from .services.accounts import AccountError
from .services.identity import IdentityError
from .services.number_tools import NumberToolError

ConnectionMethodEnum = graphene.Enum.from_enum(ConnectionMethod)
AccountPurposeEnum = graphene.Enum.from_enum(AccountPurpose)


class WhatsAppAccountType(graphene.ObjectType):
    """One of the organization's WhatsApp numbers, with the form's three proofs (user story 11)."""

    id = graphene.ID(required=True)
    # Who texts it: the organization's team, or its store customers (plan Step 1.17).
    purpose = graphene.Field(AccountPurposeEnum, required=True)
    phone_number_id = graphene.String(required=True)
    waba_id = graphene.String(required=True)
    display_phone_number = graphene.String(required=True)
    verified_name = graphene.String(required=True)
    connection_method = graphene.Field(ConnectionMethodEnum, required=True)
    is_active = graphene.Boolean(required=True)
    # Meta accepted the id and token; our app is subscribed to its WhatsApp Business account (Step
    # 1.18); a message arrived.
    credentials_verified_at = graphene.DateTime()
    subscribed_at = graphene.DateTime()
    last_message_received_at = graphene.DateTime()
    # The organization's own Meta app the number is in, or null for this service's app (plan Step 2.9).
    meta_app_id = graphene.ID()

    @staticmethod
    def resolve_id(account, info):
        return str(account.id)

    @staticmethod
    def resolve_meta_app_id(account, info):
        return str(account.meta_app.id) if account.meta_app else None

    @staticmethod
    def resolve_purpose(account, info):
        return AccountPurpose(account.purpose)

    @staticmethod
    def resolve_connection_method(account, info):
        return ConnectionMethod(account.connection_method)

    @staticmethod
    def resolve_last_message_received_at(account, info):
        return accounts.last_message_received_at(account)


def _user_error(error: AccountError) -> exceptions.GraphQlValidationError:
    # GraphQlValidationError is on SanitizeErrorsMiddleware's safe list, so the message and code reach
    # the form in production too, under the field at fault or non_field_errors, as Shopify's do.
    return exceptions.GraphQlValidationError({error.field or "non_field_errors": [str(error)]}, code=error.code)


def _tenant(info):
    """The organization the tenant middleware checked the user belongs to."""
    return getattr(info.context, "tenant", None)


class AccountsQuery(graphene.ObjectType):
    whats_app_accounts = graphene.List(
        graphene.NonNull(WhatsAppAccountType), tenant_id=graphene.ID(required=True), required=True
    )

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("whatsapp.view"))
    def resolve_whats_app_accounts(root, info, tenant_id):
        tenant = _tenant(info)
        if tenant is None:
            return []
        # Both kinds; each of the tab's two forms lists those with its purpose.
        return WhatsAppAccount.objects.filter(tenant=tenant).select_related("meta_app").order_by("created_at")


class ConnectWhatsAppAccountInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    purpose = graphene.Field(AccountPurposeEnum, required=True)
    phone_number_id = graphene.String(required=True)
    waba_id = graphene.String(required=True)
    access_token = graphene.String(required=True)
    # One of the organization's own Meta apps; left out for this service's app (plan Step 2.9).
    meta_app_id = graphene.ID()


class ConnectWhatsAppAccount(graphene.Mutation):
    """
    Connect a number with the form. Meta checks the id and token, and the token's app is subscribed to
    the number's WhatsApp Business account, before anything is saved (Steps 1.18 and 2.9).
    """

    class Arguments:
        input = ConnectWhatsAppAccountInput(required=True)

    account = graphene.Field(WhatsAppAccountType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            connected = accounts.connect_account(
                tenant=_tenant(info),
                purpose=AccountPurpose(input.purpose).value,
                phone_number_id=input.phone_number_id,
                waba_id=input.waba_id,
                access_token=input.access_token,
                meta_app_id=input.meta_app_id,
            )
        except AccountError as error:
            raise _user_error(error) from error
        return cls(account=connected.account)


class SendWhatsAppTestMessageInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    # Any common format (plan D19), e.g. "083 123 4567".
    to = graphene.String(required=True)


class SendWhatsAppTestMessage(graphene.Mutation):
    """Send Meta's hello_world template from the number, directly, so Meta's answer shows in the form."""

    class Arguments:
        input = SendWhatsAppTestMessageInput(required=True)

    message_id = graphene.String(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            message_id = accounts.send_test_message(tenant=_tenant(info), account_id=input.account_id, to=input.to)
        except AccountError as error:
            raise _user_error(error) from error
        return cls(message_id=message_id)


class DisconnectWhatsAppAccountInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)


class DisconnectWhatsAppAccount(graphene.Mutation):
    """
    Wipe the number's secrets, mark it inactive and delete its conversations (plan Step 2.8, finding
    17): numbers are recycled, so its history must never reach whoever gets it next.
    """

    class Arguments:
        input = DisconnectWhatsAppAccountInput(required=True)

    account = graphene.Field(WhatsAppAccountType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        tenant = _tenant(info)
        try:
            accounts.disconnect_account(tenant=tenant, account_id=input.account_id)
        except AccountError as error:
            raise _user_error(error) from error
        return cls(account=WhatsAppAccount.objects.get(tenant=tenant, pk=input.account_id))


class ChangeWhatsAppNumberPurposeInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    purpose = graphene.Field(AccountPurposeEnum, required=True)


class ChangeWhatsAppNumberPurpose(graphene.Mutation):
    """
    Change whom a connected number serves: the team, customers, or both (plan Step 2.7). It keeps its
    credentials, history and Meta registration; leaving the team unlinks its members.
    """

    class Arguments:
        input = ChangeWhatsAppNumberPurposeInput(required=True)

    account = graphene.Field(WhatsAppAccountType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            account = accounts.change_purpose(
                tenant=_tenant(info), account_id=input.account_id, purpose=AccountPurpose(input.purpose).value
            )
        except AccountError as error:
            raise _user_error(error) from error
        return cls(account=account)


# An organization's own Meta apps (plan Step 2.9): the list and every change need whatsapp.manage,
# since the list holds each app's verify token. The work is in services/meta_apps.py.


class WhatsAppMetaAppType(graphene.ObjectType):
    """One of the organization's own Meta apps, with what to paste into its webhook settings; never its App secret."""

    id = graphene.ID(required=True)
    # Meta's App ID.
    app_id = graphene.String(required=True)
    webhook_url = graphene.String(required=True)
    verify_token = graphene.String(required=True)
    created_at = graphene.DateTime(required=True)

    @staticmethod
    def resolve_id(app, info):
        return str(app.id)

    @staticmethod
    def resolve_webhook_url(app, info):
        return meta_apps.webhook_url(app)

    @staticmethod
    def resolve_verify_token(app, info):
        return app.verify_token


class MetaAppsQuery(graphene.ObjectType):
    whats_app_meta_apps = graphene.List(
        graphene.NonNull(WhatsAppMetaAppType), tenant_id=graphene.ID(required=True), required=True
    )

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("whatsapp.manage"))
    def resolve_whats_app_meta_apps(root, info, tenant_id):
        tenant = _tenant(info)
        if tenant is None:
            return []
        return MetaApp.objects.filter(tenant=tenant).order_by("created_at")


class RegisterWhatsAppMetaAppInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    app_id = graphene.String(required=True)
    app_secret = graphene.String(required=True)


class RegisterWhatsAppMetaApp(graphene.Mutation):
    """Register one of the organization's own Meta apps, giving it its webhook address and verify token."""

    class Arguments:
        input = RegisterWhatsAppMetaAppInput(required=True)

    meta_app = graphene.Field(WhatsAppMetaAppType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            app = meta_apps.register_app(tenant=_tenant(info), app_id=input.app_id, app_secret=input.app_secret)
        except AccountError as error:
            raise _user_error(error) from error
        return cls(meta_app=app)


class UpdateWhatsAppMetaAppSecretInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    meta_app_id = graphene.ID(required=True)
    app_secret = graphene.String(required=True)


class UpdateWhatsAppMetaAppSecret(graphene.Mutation):
    """Replace an app's App secret, after it's reset in Meta's App Dashboard."""

    class Arguments:
        input = UpdateWhatsAppMetaAppSecretInput(required=True)

    meta_app = graphene.Field(WhatsAppMetaAppType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            app = meta_apps.update_secret(
                tenant=_tenant(info), meta_app_id=input.meta_app_id, app_secret=input.app_secret
            )
        except AccountError as error:
            raise _user_error(error) from error
        return cls(meta_app=app)


class RegenerateWhatsAppMetaAppVerifyTokenInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    meta_app_id = graphene.ID(required=True)


class RegenerateWhatsAppMetaAppVerifyToken(graphene.Mutation):
    """A new verify token for the app, to paste into Meta; its webhook address stays the same."""

    class Arguments:
        input = RegenerateWhatsAppMetaAppVerifyTokenInput(required=True)

    meta_app = graphene.Field(WhatsAppMetaAppType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            app = meta_apps.regenerate_verify_token(tenant=_tenant(info), meta_app_id=input.meta_app_id)
        except AccountError as error:
            raise _user_error(error) from error
        return cls(meta_app=app)


class RemoveWhatsAppMetaAppInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    meta_app_id = graphene.ID(required=True)


class RemoveWhatsAppMetaApp(graphene.Mutation):
    """Remove an app no connected number uses; otherwise the answer names the numbers to disconnect first."""

    class Arguments:
        input = RemoveWhatsAppMetaAppInput(required=True)

    ok = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            meta_apps.remove_app(tenant=_tenant(info), meta_app_id=input.meta_app_id)
        except AccountError as error:
            raise _user_error(error) from error
        return cls(ok=True)


class SetWhatsAppNumberMetaAppInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    # Null puts the number back on this service's app.
    meta_app_id = graphene.ID()


class SetWhatsAppNumberMetaApp(graphene.Mutation):
    """Change the Meta app a connected number is in, without reconnecting it (plan Step 2.9, decision 5)."""

    class Arguments:
        input = SetWhatsAppNumberMetaAppInput(required=True)

    account = graphene.Field(WhatsAppAccountType, required=True)

    @classmethod
    def mutate(cls, root, info, input):
        try:
            account = meta_apps.set_account_app(
                tenant=_tenant(info), account_id=input.account_id, meta_app_id=input.meta_app_id
            )
        except AccountError as error:
            raise _user_error(error) from error
        return cls(account=account)


# The number troubleshooting tools (plan D18, Step 1.5b, user story 23): every one, the status
# included, needs whatsapp.manage. The work is in services/number_tools.py.


class WhatsAppNumberStatusType(graphene.ObjectType):
    """Meta's own view of a number, its values exactly as Meta sends them."""

    status = graphene.String()
    code_verification_status = graphene.String()
    quality_rating = graphene.String()
    name_status = graphene.String()
    verified_name = graphene.String()
    display_phone_number = graphene.String()


def _tool_error(error: NumberToolError) -> exceptions.GraphQlValidationError:
    # The message already holds the explanation, Meta's code and the link to Meta's page.
    return exceptions.GraphQlValidationError({error.field or "non_field_errors": [str(error)]}, code=error.code)


def _run_tool(info, account_id, call):
    """Find the organization's own number, then run one tool on it, as the logged-in user."""
    try:
        account = accounts.find_account(_tenant(info), account_id)
        return call(account, info.context.user)
    except AccountError as error:
        raise _user_error(error) from error
    except NumberToolError as error:
        raise _tool_error(error) from error


class NumberToolsQuery(graphene.ObjectType):
    whats_app_number_status = graphene.Field(
        graphene.NonNull(WhatsAppNumberStatusType),
        tenant_id=graphene.ID(required=True),
        account_id=graphene.ID(required=True),
    )

    @staticmethod
    # It asks Meta, so the plan must include WhatsApp (plan phase 3, decision 5).
    @permission_classes(IsTenantMemberAccess, requires("whatsapp.manage"))
    def resolve_whats_app_number_status(root, info, tenant_id, account_id):
        status = _run_tool(info, account_id, lambda account, user: number_tools.get_status(account))
        return WhatsAppNumberStatusType(**{field: status.get(field) for field in WhatsAppNumberStatusType._meta.fields})


class RequestWhatsAppVerificationCodeInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    # "SMS" or "VOICE".
    method = graphene.String(required=True)


class RequestWhatsAppVerificationCode(graphene.Mutation):
    class Arguments:
        input = RequestWhatsAppVerificationCodeInput(required=True)

    ok = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        _run_tool(
            info,
            input.account_id,
            lambda account, user: number_tools.request_code(account, method=input.method, actor=user),
        )
        return cls(ok=True)


class VerifyWhatsAppNumberInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    code = graphene.String(required=True)


class VerifyWhatsAppNumber(graphene.Mutation):
    class Arguments:
        input = VerifyWhatsAppNumberInput(required=True)

    ok = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        _run_tool(
            info, input.account_id, lambda account, user: number_tools.verify_code(account, code=input.code, actor=user)
        )
        return cls(ok=True)


class RegisterWhatsAppNumberInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)
    # Passed straight to Meta and never stored (D18).
    pin = graphene.String(required=True)


class RegisterWhatsAppNumber(graphene.Mutation):
    class Arguments:
        input = RegisterWhatsAppNumberInput(required=True)

    ok = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        _run_tool(
            info, input.account_id, lambda account, user: number_tools.register(account, pin=input.pin, actor=user)
        )
        return cls(ok=True)


class SubscribeWhatsAppAppInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    account_id = graphene.ID(required=True)


class SubscribeWhatsAppApp(graphene.Mutation):
    class Arguments:
        input = SubscribeWhatsAppAppInput(required=True)

    ok = graphene.Boolean(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        _run_tool(info, input.account_id, lambda account, user: number_tools.subscribe_app(account, actor=user))
        return cls(ok=True)


# The profile page's WhatsApp section (plan Step 1.7c, user stories 1 and 3, Step 1.17): only ever
# the logged-in user's own links, one per organization with an internal communications number, so no
# field takes an argument naming a user. The work is in services/identity.py.

ConversationModeEnum = graphene.Enum.from_enum(ConversationMode)


class WhatsAppLinkType(graphene.ObjectType):
    """
    The logged-in user's link on one organization's internal number, with their phone masked to its
    last four digits.
    """

    tenant_id = graphene.ID(required=True)
    organization_name = graphene.String(required=True)
    # The number the user texts, as Meta shows it.
    internal_number = graphene.String(required=True)
    linked = graphene.Boolean(required=True)
    masked_number = graphene.String()
    # Empty means WHATSAPP_DEFAULT_CONVERSATION_MODE applies (user story 3).
    conversation_mode = graphene.Field(ConversationModeEnum)
    linked_at = graphene.DateTime()


def _mask(number: str) -> str:
    """Only the last four digits show, e.g. "*******4567"."""
    return "*" * (len(number) - 4) + number[-4:]


def _link_of(user, internal: WhatsAppAccount) -> WhatsAppLinkType:
    tenant = internal.tenant
    shown = {
        "tenant_id": to_global_id("TenantType", str(tenant.id)),
        "organization_name": tenant.name,
        "internal_number": internal.display_phone_number or internal.phone_number_id,
    }
    linked = WhatsAppIdentity.objects.filter(user=user, account=internal).select_related("contact").first()
    if linked is None:
        return WhatsAppLinkType(linked=False, **shown)
    return WhatsAppLinkType(
        linked=True,
        masked_number=_mask(linked.contact.wa_id),
        conversation_mode=ConversationMode(linked.conversation_mode) if linked.conversation_mode else None,
        linked_at=linked.linked_at,
        **shown,
    )


def _identity_error(error: IdentityError, field: str | None = None) -> exceptions.GraphQlValidationError:
    return exceptions.GraphQlValidationError({field or "non_field_errors": [str(error)]}, code=error.code)


def _users_internal_number(user, tenant_id) -> WhatsAppAccount:
    """The internal number of an organization `user` is a member of; anything else is "not found"."""
    tenant = _users_tenant(user, tenant_id)
    internal = WhatsAppAccount.objects.internal_for(tenant)
    if internal is None:
        raise _identity_error(IdentityError("Link your WhatsApp number first.", "not_linked"))
    return internal


def _users_tenant(user, tenant_id):
    """The organization the input names, if `user` is a member of it; else "not found"."""
    try:
        _, pk = from_global_id(tenant_id)
    except (TypeError, ValueError):
        pk = None
    tenant = Tenant.objects.filter(pk=pk).first() if pk else None
    if tenant is None or not identity.is_member(user, tenant):
        raise _identity_error(IdentityError("Organization not found.", "not_found"))
    return tenant


class IdentityQuery(graphene.ObjectType):
    whats_app_links = graphene.List(graphene.NonNull(WhatsAppLinkType), required=True)

    @staticmethod
    @permission_classes(IsAuthenticatedFullAccess)
    def resolve_whats_app_links(root, info):
        user = info.context.user
        internal_numbers = (
            WhatsAppAccount.objects.filter(
                # The number each organization's team texts: internal, or serving both (Step 2.7).
                purpose__in=TEAM_PURPOSES,
                is_active=True,
                tenant__user_memberships__in=TenantMembership.objects.filter(user=user),
            )
            .select_related("tenant")
            .order_by("tenant__name", "pk")
        )
        return [_link_of(user, internal) for internal in internal_numbers]


class StartWhatsAppLinkInput(graphene.InputObjectType):
    # The organization whose internal number the phone is linked on.
    tenant_id = graphene.ID(required=True)
    # Any common format (plan D19), e.g. "083 123 4567".
    phone_number = graphene.String(required=True)


class StartWhatsAppLink(graphene.Mutation):
    """Issue a link code for the logged-in user's number; it works only when sent from that number."""

    class Arguments:
        input = StartWhatsAppLinkInput(required=True)

    code = graphene.String(required=True)
    # Opens WhatsApp with "link <code>" typed, addressed to the organization's internal number.
    link = graphene.String(required=True)
    masked_number = graphene.String(required=True)
    expires_at = graphene.DateTime(required=True)

    @classmethod
    def mutate(cls, root, info, input):
        user = info.context.user
        try:
            started = identity.start_link(user, _users_tenant(user, input.tenant_id), input.phone_number)
        except IdentityError as error:
            field = "phone_number" if error.code == "invalid_phone_number" else None
            raise _identity_error(error, field) from error
        return cls(
            code=started.code,
            link=started.link,
            masked_number=_mask(started.phone_number),
            expires_at=started.expires_at,
        )


class UpdateWhatsAppConversationModeInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)
    mode = graphene.Field(ConversationModeEnum, required=True)


class UpdateWhatsAppConversationMode(graphene.Mutation):
    """
    Save how the logged-in user wants to talk to one organization's number: menus and forms, or the
    AI assistant.
    """

    class Arguments:
        input = UpdateWhatsAppConversationModeInput(required=True)

    link = graphene.Field(graphene.NonNull(WhatsAppLinkType))

    @classmethod
    def mutate(cls, root, info, input):
        user = info.context.user
        internal = _users_internal_number(user, input.tenant_id)
        updated = WhatsAppIdentity.objects.filter(user=user, account=internal).update(
            conversation_mode=ConversationMode(input.mode).value
        )
        if not updated:
            raise _identity_error(IdentityError("Link your WhatsApp number first.", "not_linked"))
        return cls(link=_link_of(user, internal))


class DisconnectWhatsAppInput(graphene.InputObjectType):
    tenant_id = graphene.ID(required=True)


class DisconnectWhatsApp(graphene.Mutation):
    """
    Remove the logged-in user's link on one organization's number. Their WhatsApp contact stays; its
    conversation is forgotten, the assistant's history included (Step 1.13).
    """

    class Arguments:
        input = DisconnectWhatsAppInput(required=True)

    link = graphene.Field(graphene.NonNull(WhatsAppLinkType))

    @classmethod
    def mutate(cls, root, info, input):
        user = info.context.user
        internal = _users_internal_number(user, input.tenant_id)
        identity.unlink(user, internal)
        return cls(link=_link_of(user, internal))


@permission_classes(IsAuthenticatedFullAccess)
class IdentityMutation(graphene.ObjectType):
    """The logged-in user's own WhatsApp link; registered in config/schema.py beside Mutation."""

    start_whats_app_link = StartWhatsAppLink.Field()
    update_whats_app_conversation_mode = UpdateWhatsAppConversationMode.Field()
    disconnect_whats_app = DisconnectWhatsApp.Field()


class Query(AccountsQuery, MetaAppsQuery, NumberToolsQuery, IdentityQuery):
    """Every WhatsApp query, registered once in config/schema.py."""


@permission_classes(IsTenantMemberAccess)
class Mutation(graphene.ObjectType):
    # Setting a number up needs no plan, so a business can be ready before its trial starts (plan
    # Step 2.8, finding 16); what waits for a plan is the number replying, which the router checks.
    connect_whats_app_account = permission_classes(requires("whatsapp.manage"))(ConnectWhatsAppAccount.Field())
    send_whats_app_test_message = permission_classes(requires("whatsapp.manage"))(SendWhatsAppTestMessage.Field())
    disconnect_whats_app_account = permission_classes(requires("whatsapp.manage"))(DisconnectWhatsAppAccount.Field())
    change_whats_app_number_purpose = permission_classes(requires("whatsapp.manage"))(
        ChangeWhatsAppNumberPurpose.Field()
    )
    request_whats_app_verification_code = permission_classes(requires("whatsapp.manage"))(
        RequestWhatsAppVerificationCode.Field()
    )
    verify_whats_app_number = permission_classes(requires("whatsapp.manage"))(VerifyWhatsAppNumber.Field())
    register_whats_app_number = permission_classes(requires("whatsapp.manage"))(RegisterWhatsAppNumber.Field())
    subscribe_whats_app_app = permission_classes(requires("whatsapp.manage"))(SubscribeWhatsAppApp.Field())
    register_whats_app_meta_app = permission_classes(requires("whatsapp.manage"))(RegisterWhatsAppMetaApp.Field())
    update_whats_app_meta_app_secret = permission_classes(requires("whatsapp.manage"))(
        UpdateWhatsAppMetaAppSecret.Field()
    )
    regenerate_whats_app_meta_app_verify_token = permission_classes(requires("whatsapp.manage"))(
        RegenerateWhatsAppMetaAppVerifyToken.Field()
    )
    remove_whats_app_meta_app = permission_classes(requires("whatsapp.manage"))(RemoveWhatsAppMetaApp.Field())
    set_whats_app_number_meta_app = permission_classes(requires("whatsapp.manage"))(SetWhatsAppNumberMetaApp.Field())
