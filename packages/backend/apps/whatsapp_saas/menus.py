"""
The internal communications numbers' handler: menus for an organization's team in WHATSAPP_FORM
mode (plan Step 1.10, decision D1, user stories 4, 6, 9 and 21). Registered with apps.whatsapp's
registry in apps.py.

Everything happens in the number's organization, which the router puts in turn.conversation.tenant
(Step 1.17): there's no organization to pick or create, and the only organization action is Rename
(maintainer's decision, 2026-10-22).

Every screen is built with apps.whatsapp's builders, so every one offers a way back (D17): lists end
with Main menu, button screens keep Back or Main menu, and pages hold 7 items. Every button is an
opaque id from turn.choice (section 8.5); what it stands for stays on the server.

All work goes through use_cases.py, which checks permissions exactly as the website does (D10). The
menus also hide what a user may not do, but that's only courtesy: the use case refuses regardless.

Forms (Step 1.11b, D9): New item, Edit and Rename organization open a WhatsApp Flow, pre-filled. Its
answers are checked by the use cases first, so a mistake gets the reason and the form again with
what was typed, and then go through Confirm (D11): nothing is saved before it. The forms are
published to a number when it's connected (on_connected, tasks.publish_forms).

Products (Step 1.12b, user story 7): read live from Shopify, never stored. A store's screen offers
Browse and Search, since a full page (7 products, Previous, Next, Main menu) leaves no row for
Search. Search asks for typed words (turn.expect_text). Shopify pages by cursor, so each Previous,
Next and Back carries the cursor and the search words of the page it leads to.

Agentic mode (Step 1.13): free text goes to the assistant, with tools.py's tools and prompts.py's
instructions. Its writes, like the menus', are asked for through writes.py.
"""

from urllib.parse import urlparse

from apps.whatsapp.agent import service as agent
from apps.whatsapp.agent.service import AgentError
from apps.whatsapp.builders import MAIN_MENU, Choice, Row, list_message, reply_buttons, text_reply
from apps.whatsapp.services import flows
from apps.whatsapp.services.flows import FormExpired, FormNotAvailable

from . import display, prompts, tasks, use_cases, writes
from .flows import SCREEN_NAMES
from .tools import TOOLS
from .use_cases import UseCaseError

ITEMS = "items"
ITEM = "item.view"
ITEM_DELETE = "item.delete"
ITEM_EDIT = "item.edit"
ITEM_NEW = "item.new"
ORGANIZATION_RENAME = "organization.rename"
PRODUCTS = "products"
STORE = "store"
PRODUCT_PAGE = "products.page"
PRODUCT = "product.view"
PRODUCT_SEARCH = "products.search"

# What an open form is for; flows.open_form keeps it on the server with the form's context.
ITEM_FORM = "item.form"
ORGANIZATION_FORM = "organization.form"

# Meta's image headers take JPEG or PNG only; another format would fail the whole message.
SHOWABLE_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
# Longer than any product search needs; it's kept in the conversation with each page's buttons.
SEARCH_WORDS_MAX = 100

NO_ITEMS_PERMISSION_TEXT = "You don't have permission to change this organization's items."
FORM_EXPIRED_TEXT = "That form has expired, so nothing was changed."
FORMS_NOT_SET_UP_TEXT = (
    "Forms aren't set up on this number yet, so this can't be done here for now. An admin can set "
    "them up by connecting the number again on the website's WhatsApp page."
)


class InternalNumberHandler:
    """Answers an organization's linked members on its internal number (registry.py describes the methods)."""

    def on_connected(self, account) -> None:
        # Meta's calls take a while; the form doesn't wait for them.
        tasks.publish_forms.delay(str(account.pk))

    def main_menu(self, turn) -> list[dict]:
        tenant = turn.conversation.tenant
        rows = [Row(turn.choice(ITEMS, page=1), "Items", "List, view and change items")]
        if use_cases.can_manage_items(turn.user, tenant):
            rows.append(Row(turn.choice(ITEM_NEW), "New item", f"Create an item in {tenant.name}"))
        if use_cases.can_view_products(turn.user, tenant):
            rows.append(Row(turn.choice(PRODUCTS), "Products", "Browse and search your Shopify store"))
        if use_cases.can_rename_organization(turn.user, tenant):
            rows.append(Row(turn.choice(ORGANIZATION_RENAME), "Rename organization", f"Rename {tenant.name}"))
        # "Organization:" says what the name is: a personal organization is named after an email (Step 1.20).
        body = f"You're working in Organization: {tenant.name}. What would you like to do?"
        return [list_message(body, button_label="Menu", section_title="Main menu", rows=rows)]

    def on_choice(self, turn, kind: str, data: dict) -> list[dict]:
        screens = {
            ORGANIZATION_RENAME: self._rename_organization,
            ITEMS: self._items,
            ITEM: self._item,
            ITEM_NEW: self._new_item,
            ITEM_EDIT: self._edit_item,
            ITEM_DELETE: self._delete_item,
            PRODUCTS: self._products,
            STORE: self._store,
            PRODUCT_PAGE: self._product_page,
            PRODUCT: self._product,
            PRODUCT_SEARCH: self._search,
        }
        screen = screens.get(kind)
        if screen is None:
            return self.main_menu(turn)
        return self._show(turn, screen, data)

    def on_free_text(self, turn, text: str) -> list[dict]:
        # Agentic mode (Step 1.13): the assistant, with this app's tools and instructions.
        try:
            return agent.respond(turn, text, tools=TOOLS, instructions=prompts.instructions(turn))
        except AgentError as error:
            return text_reply(str(error)) + self.main_menu(turn)

    def on_typed_answer(self, turn, kind: str, data: dict, text: str) -> list[dict]:
        words = " ".join(text.split())[:SEARCH_WORDS_MAX]
        if kind != PRODUCT_SEARCH or not words:
            return self.main_menu(turn)
        return self._show(turn, self._product_page, {"store_id": data["store_id"], "query": words})

    def _show(self, turn, screen, data) -> list[dict]:
        """A screen, or what went wrong and the main menu."""
        try:
            return screen(turn, data)
        except FormNotAvailable:
            return text_reply(FORMS_NOT_SET_UP_TEXT) + self.main_menu(turn)
        except UseCaseError as error:
            return text_reply(str(error)) + self.main_menu(turn)

    def on_flow_reply(self, turn, response: dict) -> list[dict]:
        try:
            kind, context, answers = flows.read_answers(turn, response)
        except FormExpired:
            return text_reply(FORM_EXPIRED_TEXT) + self.main_menu(turn)
        answered = {ITEM_FORM: self._item_answered, ORGANIZATION_FORM: self._organization_answered}.get(kind)
        if answered is None:
            return self.main_menu(turn)
        try:
            return answered(turn, context, answers)
        except FormNotAvailable:
            return text_reply(FORMS_NOT_SET_UP_TEXT) + self.main_menu(turn)
        except UseCaseError as error:
            return text_reply(str(error)) + self.main_menu(turn)

    # The organization (user story 5): renaming is the only action on it here.

    def _rename_organization(self, turn, data) -> list[dict]:
        tenant = turn.conversation.tenant
        if not use_cases.can_rename_organization(turn.user, tenant):
            return text_reply("You don't have permission to rename this organization.")
        return self._organization_form(turn, tenant)

    def _organization_form(self, turn, tenant, *, name=None) -> list[dict]:
        """The form renaming `tenant`."""
        return flows.open_form(
            turn,
            form="organization",
            screen=SCREEN_NAMES["organization"],
            data={"heading": f"Rename {tenant.name}", "name": tenant.name if name is None else name},
            body=f"Fill in the form to rename {tenant.name}.",
            cta="Rename organization",
            kind=ORGANIZATION_FORM,
            context={},
        )

    def _organization_answered(self, turn, context, answers) -> list[dict]:
        name = str(answers.get("name", "")).strip()
        tenant = turn.conversation.tenant
        try:
            return writes.ask_to_rename_organization(turn, tenant, name)
        except UseCaseError as error:
            return _try_again(error, lambda: self._organization_form(turn, tenant, name=name))

    # Items (user story 6)

    def _items(self, turn, data) -> list[dict]:
        tenant = turn.conversation.tenant
        page = use_cases.list_items(turn.user, tenant, page=int(data.get("page", 1)))
        rows = [Row(turn.choice(ITEM, item_id=str(item.pk), page=page.page), item.name) for item in page.items]
        previous = Row(turn.choice(ITEMS, page=page.page - 1), "Previous") if page.has_previous else None
        following = Row(turn.choice(ITEMS, page=page.page + 1), "Next") if page.has_next else None
        if page.items:
            body = f"Items in {tenant.name}, page {page.page} of {page.total_pages}."
        else:
            body = f"There are no items in {tenant.name} yet."
        return [
            list_message(
                body, button_label="Items", section_title="Items", rows=rows, previous=previous, next=following
            )
        ]

    def _item(self, turn, data) -> list[dict]:
        tenant = turn.conversation.tenant
        item = use_cases.get_item(turn.user, tenant, data["item_id"])
        choices = []
        if use_cases.can_manage_items(turn.user, tenant):
            # Edit opens a pre-filled form; Delete asks to confirm first (D11).
            choices.append(Choice(turn.choice(ITEM_EDIT, item_id=str(item.pk)), "Edit"))
            choices.append(Choice(turn.choice(ITEM_DELETE, item_id=str(item.pk)), "Delete"))
        back = Choice(turn.choice(ITEMS, page=data.get("page", 1)), "Back")
        return [reply_buttons(f"Item: {item.name}", choices, way_back=back)]

    def _new_item(self, turn, data) -> list[dict]:
        tenant = turn.conversation.tenant
        if not use_cases.can_manage_items(turn.user, tenant):
            return text_reply(NO_ITEMS_PERMISSION_TEXT)
        return self._item_form(turn, tenant)

    def _edit_item(self, turn, data) -> list[dict]:
        tenant = turn.conversation.tenant
        if not use_cases.can_manage_items(turn.user, tenant):
            return text_reply(NO_ITEMS_PERMISSION_TEXT)
        return self._item_form(turn, tenant, use_cases.get_item(turn.user, tenant, data["item_id"]))

    def _item_form(self, turn, tenant, item=None, *, name=None) -> list[dict]:
        """The item form: editing `item`, or creating one, in `tenant`, the number's organization."""
        if item is None:
            heading, body, cta, context = (
                f"Create an item in {tenant.name}",
                f"Fill in the form to create an item in {tenant.name}.",
                "New item",
                {},
            )
        else:
            heading, body, cta, context = (
                f"Edit {item.name}",
                f"Fill in the form to change {item.name}.",
                "Edit item",
                {"item_id": str(item.pk)},
            )
        default = "" if item is None else item.name
        data = {"heading": heading, "name": default if name is None else name}
        return flows.open_form(
            turn,
            form="item",
            screen=SCREEN_NAMES["item"],
            data=data,
            body=body,
            cta=cta,
            kind=ITEM_FORM,
            context=context,
        )

    def _item_answered(self, turn, context, answers) -> list[dict]:
        name = str(answers.get("name", "")).strip()
        # Always the number's organization, whatever a form published before Step 1.17 sends.
        tenant = turn.conversation.tenant
        if "item_id" in context:
            try:
                return writes.ask_to_update_item(turn, tenant, context["item_id"], name)
            except UseCaseError as error:
                return _try_again(
                    error,
                    lambda: self._item_form(
                        turn, tenant, use_cases.get_item(turn.user, tenant, context["item_id"]), name=name
                    ),
                )

        try:
            return writes.ask_to_create_item(turn, tenant, name)
        except UseCaseError as error:
            return _try_again(error, lambda: self._item_form(turn, tenant, name=name))

    def _delete_item(self, turn, data) -> list[dict]:
        tenant = turn.conversation.tenant
        if not use_cases.can_manage_items(turn.user, tenant):
            # The button was shown earlier; the permission has gone since.
            return text_reply(NO_ITEMS_PERMISSION_TEXT)
        return writes.ask_to_delete_item(turn, tenant, data["item_id"])

    # Shopify products (user story 7)

    def _products(self, turn, data) -> list[dict]:
        tenant = turn.conversation.tenant
        stores = use_cases.list_stores(turn.user, tenant)
        if not stores:
            return text_reply(
                f"No Shopify store is connected to {tenant.name} yet. Connect one on the website's Shopify page."
            )
        if len(stores) == 1:
            return self._store(turn, {"store_id": stores[0].pk})
        page = max(1, int(data.get("page", 1)))
        start = (page - 1) * use_cases.PAGE_SIZE
        # A row title holds 24 characters, which most full domains overflow: the handle, then the domain.
        rows = [
            Row(
                turn.choice(STORE, store_id=store.pk),
                store.shop_domain.removesuffix(".myshopify.com"),
                store.shop_domain,
            )
            for store in stores[start : start + use_cases.PAGE_SIZE]
        ]
        previous = Row(turn.choice(PRODUCTS, page=page - 1), "Previous") if page > 1 else None
        has_next = start + use_cases.PAGE_SIZE < len(stores)
        following = Row(turn.choice(PRODUCTS, page=page + 1), "Next") if has_next else None
        return [
            list_message(
                f"Which of {tenant.name}'s stores?",
                button_label="Stores",
                section_title="Stores",
                rows=rows,
                previous=previous,
                next=following,
            )
        ]

    def _store(self, turn, data) -> list[dict]:
        store = use_cases.get_store(turn.user, turn.conversation.tenant, data["store_id"])
        browse = Choice(turn.choice(PRODUCT_PAGE, store_id=store.pk), "Browse")
        search = Choice(turn.choice(PRODUCT_SEARCH, store_id=store.pk), "Search")
        body = f"{store.shop_domain}: browse its products, newest first, or search them."
        return [reply_buttons(body, [browse, search], way_back=MAIN_MENU)]

    def _product_page(self, turn, data) -> list[dict]:
        where = {
            "store_id": data["store_id"],
            "after": data.get("after"),
            "before": data.get("before"),
            "query": data.get("query"),
        }
        page = use_cases.list_products(
            turn.user,
            turn.conversation.tenant,
            where["store_id"],
            after=where["after"],
            before=where["before"],
            query=where["query"],
        )
        domain = page.store.shop_domain
        query = where["query"]
        if not page.products and query:
            search_again = Choice(turn.choice(PRODUCT_SEARCH, store_id=page.store.pk), "Search again")
            browse_all = Choice(turn.choice(PRODUCT_PAGE, store_id=page.store.pk), "Browse all")
            body = f'No products in {domain} match "{query}".'
            return [reply_buttons(body, [search_again, browse_all], way_back=MAIN_MENU)]

        rows = [
            Row(
                turn.choice(PRODUCT, product=_product_shown(product), back=where),
                product["title"],
                f"{display.price(product)} · {display.status(product)}",
            )
            for product in page.products
        ]
        previous = None
        if page.has_previous:
            previous = Row(
                turn.choice(PRODUCT_PAGE, store_id=page.store.pk, before=page.start_cursor, query=query), "Previous"
            )
        following = None
        if page.has_next:
            following = Row(
                turn.choice(PRODUCT_PAGE, store_id=page.store.pk, after=page.end_cursor, query=query), "Next"
            )
        if not page.products:
            body = f"There are no products in {domain} yet."
        elif query:
            body = f'Products in {domain} matching "{query}", newest first.'
        else:
            body = f"Products in {domain}, newest first."
        return [
            list_message(
                body, button_label="Products", section_title="Products", rows=rows, previous=previous, next=following
            )
        ]

    def _product(self, turn, data) -> list[dict]:
        # Shown from the page it was listed on, so Shopify isn't asked again; the permission is.
        if not use_cases.can_view_products(turn.user, turn.conversation.tenant):
            return text_reply("You don't have permission to see this organization's products.")
        product = data["product"]
        body = f"*{product['title']}*\nPrice: {display.price(product)}\nStatus: {display.status(product)}"
        back = Choice(turn.choice(PRODUCT_PAGE, **data["back"]), "Back")
        return [reply_buttons(body, [], way_back=back, image_url=_showable_image(product["image_url"]))]

    def _search(self, turn, data) -> list[dict]:
        store = use_cases.get_store(turn.user, turn.conversation.tenant, data["store_id"])
        turn.expect_text(PRODUCT_SEARCH, store_id=store.pk)
        return text_reply(
            f"Type what you're looking for in {store.shop_domain}, such as a product's name. "
            "Send *menu* to go back instead."
        )


def _product_shown(product: dict) -> dict:
    """What a product's detail screen shows, kept with its button until it's pressed."""
    keys = ("title", "status", "price_min", "price_max", "currency_code", "image_url")
    return {key: product[key] for key in keys}


def _showable_image(url: str | None) -> str | None:
    """The picture's link if Meta can show it in a header, judged by the file name; else None."""
    if url and urlparse(url).path.lower().endswith(SHOWABLE_IMAGE_EXTENSIONS):
        return url
    return None


def _try_again(error: UseCaseError, form) -> list[dict]:
    """An invalid answer gets the reason and the form again, holding what was typed; other errors go up."""
    if error.code != "invalid":
        raise error
    return text_reply(str(error)) + form()
