"""
Building the message part of a Meta send request, within Meta's limits (plan Step 1.4a).

Each builder returns what goes under one message in a Cloud API send request, for example
{"type": "interactive", "interactive": {...}}. The client adds the envelope (messaging_product,
recipient) when it sends. Named builders.py so it isn't confused with Django's `messages` framework.

Two kinds of overflow are treated differently:
- text that comes from data (an item's or product's name) is cut to fit, ending in "…", so a long
  name never stops a reply (`_fit`);
- our own code breaking a rule (an over-long id, too many buttons or rows, no way back) raises
  BuilderError: that's a bug to fix, not data to squeeze.

Every reply offers a way back, so nobody is ever stuck (plan decision D17, user story 21): every
interactive message carries WAY_BACK_FOOTER, button messages keep a button for Back or Main menu,
lists always end with Main menu, and plain text goes out with a Main menu button.

Meta's limits, linked next to where each is used:
- reply buttons: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-reply-buttons-messages.md
- lists: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-list-messages.md
- link buttons: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-cta-url-messages.md
- Flows: https://developers.facebook.com/docs/whatsapp/flows/guides/sendingaflow
- text: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/text-messages.md
- pictures: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/image-messages.md
"""

from dataclasses import dataclass

# Text messages: text.body is at most 4096 characters.
TEXT_BODY_MAX = 4096
# Reply buttons: at most 3 buttons; titles up to 20 characters (unique); ids up to 256; body up to 1024.
REPLY_BUTTONS_MAX = 3
REPLY_TITLE_MAX = 20
REPLY_ID_MAX = 256
REPLY_BODY_MAX = 1024
# Lists: at most 10 rows in all; row titles 24, descriptions 72, ids 200; section title 24;
# the button that opens the list 20; body 4096.
LIST_ROWS_MAX = 10
LIST_ROW_TITLE_MAX = 24
LIST_ROW_DESCRIPTION_MAX = 72
LIST_ROW_ID_MAX = 200
LIST_SECTION_TITLE_MAX = 24
LIST_BUTTON_MAX = 20
LIST_BODY_MAX = 4096
# Link buttons (cta_url): display_text up to 20 characters; body up to 1024.
LINK_TEXT_MAX = 20
LINK_BODY_MAX = 1024
# Pictures: the caption is at most 1024 characters; JPEG or PNG, up to 5 MB.
IMAGE_CAPTION_MAX = 1024
# Flows: Meta advises a call-to-action of 30 characters or fewer.
FLOW_CTA_MAX = 30

# D17: lists hold at most 7 items, so Previous, Next and Main menu always fit in Meta's 10 rows.
LIST_ITEMS_MAX = 7
# Every interactive message's footer (Meta allows 60 characters). *menu* is bold in WhatsApp.
WAY_BACK_FOOTER = "Send *menu* at any time"

ELLIPSIS = "…"


class BuilderError(ValueError):
    """Our own code asked for a message Meta would refuse, or one without a way back."""


@dataclass(frozen=True)
class Choice:
    """A reply button: the id comes back in the webhook when it's pressed (an opaque id, plan 8.5)."""

    id: str
    title: str


@dataclass(frozen=True)
class Row:
    """A row of a list message; the description may be empty."""

    id: str
    title: str
    description: str = ""


# The way back to the start, as a button and as a list's last row. Its id is fixed, not opaque,
# because it means the same thing on every screen.
MAIN_MENU = Choice("menu", "Main menu")
MAIN_MENU_ROW = Row(MAIN_MENU.id, MAIN_MENU.title, "Back to the start")


def reply_buttons(body: str, choices: list[Choice], *, way_back: Choice, image_url: str | None = None) -> dict:
    """
    A message with up to 3 reply buttons: up to 2 choices, then the way back (Back or Main menu),
    which always takes one of the 3 (D17). `image_url`, optional, shows a picture above the body,
    such as a product's (Meta fetches it from the link).
    """
    if way_back is None:
        raise BuilderError("A reply-button message needs a way back: Back or Main menu (D17).")
    if len(choices) > REPLY_BUTTONS_MAX - 1:
        raise BuilderError(f"At most {REPLY_BUTTONS_MAX - 1} choices fit beside the way back; got {len(choices)}.")
    if len(body) > REPLY_BODY_MAX:
        raise BuilderError(f"A reply-button body is at most {REPLY_BODY_MAX} characters; use text_reply for longer.")

    buttons = []
    for choice in [*choices, way_back]:
        _check_id(choice.id, REPLY_ID_MAX)
        buttons.append({"type": "reply", "reply": {"id": choice.id, "title": _fit(choice.title, REPLY_TITLE_MAX)}})

    titles = [button["reply"]["title"] for button in buttons]
    if len(set(titles)) != len(titles):
        raise BuilderError(f"Button titles must be unique, as Meta requires; got {titles}.")

    message = _interactive("button", body, {"buttons": buttons})
    if image_url:
        message["interactive"]["header"] = {"type": "image", "image": {"link": image_url}}
    return message


def list_message(
    body: str,
    *,
    button_label: str,
    section_title: str,
    rows: list[Row],
    previous: Row | None = None,
    next: Row | None = None,
) -> dict:
    """
    A list of up to 7 items, then Previous and Next when given (the caller knows whether there's
    another page), then Main menu, always last (D17). One section holds them all.
    """
    if len(rows) > LIST_ITEMS_MAX:
        raise BuilderError(
            f"A list holds at most {LIST_ITEMS_MAX} items, leaving room for Previous, Next and Main menu (D17); "
            f"got {len(rows)}."
        )
    if len(body) > LIST_BODY_MAX:
        raise BuilderError(f"A list body is at most {LIST_BODY_MAX} characters.")

    all_rows = [*rows, *(row for row in (previous, next) if row is not None), MAIN_MENU_ROW]
    # Never more than Meta's 10, given the 7-item limit above; checked anyway, as the rule it is.
    if len(all_rows) > LIST_ROWS_MAX:
        raise BuilderError(f"A list message has at most {LIST_ROWS_MAX} rows.")

    section = {"title": _fit(section_title, LIST_SECTION_TITLE_MAX), "rows": [_row(row) for row in all_rows]}
    return _interactive("list", body, {"button": _fit(button_label, LIST_BUTTON_MAX), "sections": [section]})


def image_message(link: str, *, caption: str) -> dict:
    """
    A picture on its own, fetched by Meta from `link`, such as a store's logo at its welcome (WhatsApp
    plan Step 2.8, finding 13). It has no buttons, so it's only ever sent just before a message that
    carries the way back (D17). The caption comes from data, so it's cut to fit.
    """
    return {"type": "image", "image": {"link": link, "caption": _fit(caption, IMAGE_CAPTION_MAX)}}


def link_button(body: str, *, display_text: str, url: str) -> dict:
    """
    A message with one button that opens a URL (cta_url), e.g. a checkout link. It has no room for
    a second button, so its way back is the footer (D17).
    """
    if len(body) > LINK_BODY_MAX:
        raise BuilderError(f"A link-button body is at most {LINK_BODY_MAX} characters.")
    return _interactive(
        "cta_url",
        body,
        {"name": "cta_url", "parameters": {"display_text": _fit(display_text, LINK_TEXT_MAX), "url": url}},
    )


def flow_message(body: str, *, flow_id: str, flow_token: str, cta: str, screen: str, data: dict) -> dict:
    """
    A message that opens a WhatsApp Flow (a form) on `screen`, pre-filled with `data`. With
    flow_action "navigate" the form opens with this data and needs no Flow endpoint (plan D9);
    Meta requires the data to be non-empty for navigate.
    """
    if not data:
        raise BuilderError("A Flow opened with navigate needs non-empty data for its first screen.")
    return _interactive(
        "flow",
        body,
        {
            "name": "flow",
            "parameters": {
                "flow_message_version": "3",
                "flow_token": flow_token,
                "flow_id": flow_id,
                "flow_cta": _fit(cta, FLOW_CTA_MAX),
                "flow_action": "navigate",
                "flow_action_payload": {"screen": screen, "data": data},
            },
        },
    )


def text_reply(text: str) -> list[dict]:
    """
    A plain reply, as one or more messages that end with a Main menu button (D17).

    Up to 1024 characters it's a single button message. Longer text is split: the final part (up to
    1024, the limit of a button message's body) carries the Main menu button, and the parts before
    it go out as plain text messages of up to 4096. Splits fall after a space where one exists, so
    no word is cut in half, and joining the parts gives back exactly the original text.
    """
    if not text:
        raise BuilderError("A reply needs some text.")
    if len(text) <= REPLY_BODY_MAX:
        return [reply_buttons(text, [], way_back=MAIN_MENU)]

    # The final part first: it must fit a button message, and start on a whole word.
    final_start = _split_point(text, earliest=len(text) - REPLY_BODY_MAX, latest=len(text), prefer="first")
    head, final = text[:final_start], text[final_start:]

    parts = []
    while len(head) > TEXT_BODY_MAX:
        end = _split_point(head, earliest=1, latest=TEXT_BODY_MAX, prefer="last")
        parts.append(head[:end])
        head = head[end:]
    if head:
        parts.append(head)

    return [*(_text(part) for part in parts), reply_buttons(final, [], way_back=MAIN_MENU)]


def _split_point(text: str, *, earliest: int, latest: int, prefer: str) -> int:
    """
    An index between `earliest` and `latest` just after a space, so text[:i] ends on a space and
    text[i:] starts on a whole word: the first such index, or the last. With no space in range, the
    hard limit itself (a very long word can't be kept whole).
    """
    candidates = range(earliest, latest + 1) if prefer == "first" else range(latest, earliest - 1, -1)
    for index in candidates:
        if 0 < index < len(text) and text[index - 1].isspace():
            return index
    return earliest if prefer == "first" else latest


def _interactive(kind: str, body: str, action: dict) -> dict:
    """The interactive message shape every builder shares, with the way-back footer (D17)."""
    return {
        "type": "interactive",
        "interactive": {"type": kind, "body": {"text": body}, "footer": {"text": WAY_BACK_FOOTER}, "action": action},
    }


def _text(body: str) -> dict:
    """A plain text message; links in it are not previewed."""
    return {"type": "text", "text": {"body": body, "preview_url": False}}


def _row(row: Row) -> dict:
    """One list row; Meta's description is optional, so an empty one is left out."""
    _check_id(row.id, LIST_ROW_ID_MAX)
    rendered = {"id": row.id, "title": _fit(row.title, LIST_ROW_TITLE_MAX)}
    if row.description:
        rendered["description"] = _fit(row.description, LIST_ROW_DESCRIPTION_MAX)
    return rendered


def _fit(text: str, limit: int) -> str:
    """Text from data, cut to `limit` characters with "…" when it's longer."""
    if len(text) <= limit:
        return text
    return text[: limit - len(ELLIPSIS)] + ELLIPSIS


def _check_id(identifier: str, limit: int) -> None:
    """Ids are ours, not data, so an over-long one is a bug in our code."""
    if len(identifier) > limit:
        raise BuilderError(f"An id is at most {limit} characters; got {len(identifier)}.")
