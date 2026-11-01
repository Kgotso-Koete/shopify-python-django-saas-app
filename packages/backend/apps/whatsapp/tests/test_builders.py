"""
Tests for apps/whatsapp/builders.py: building the message part of a Meta send request, within
Meta's limits (plan Step 1.4a). Each limit is tested at its edge, one character either side.

Two kinds of overflow are treated differently:
- text that comes from data (an item's or product's name) is cut to fit, ending in "…", so a long
  name never stops a reply;
- our own code breaking a rule (an over-long id, too many buttons or rows) is refused with
  BuilderError: that's a bug to fix, not data to squeeze.

Meta's limits:
- reply buttons: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-reply-buttons-messages.md
- lists: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-list-messages.md
- link buttons: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-cta-url-messages.md
- Flows: https://developers.facebook.com/docs/whatsapp/flows/guides/sendingaflow
- text: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/text-messages.md

Kind of test: unit (agents.md section 2.5). Why: the builders on their own, with no database or
network; nothing is faked.
"""

import pytest

from ..builders import (
    MAIN_MENU,
    BuilderError,
    Choice,
    Row,
    flow_message,
    image_message,
    link_button,
    list_message,
    reply_buttons,
    text_reply,
)

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db


def buttons_of(message):
    return [button["reply"] for button in message["interactive"]["action"]["buttons"]]


def rows_of(message):
    return [row for section in message["interactive"]["action"]["sections"] for row in section["rows"]]


class TestPictures:
    """
    A picture on its own, such as a store's logo at its welcome (WhatsApp plan Step 2.8, finding 13).
    Meta: "Maximum 1024 characters" of caption, JPEG or PNG:
    https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/image-messages.md
    """

    def test_a_picture_by_its_link_with_a_caption(self):
        message = image_message("https://cdn.shopify.com/logo.png", caption="Acme Snow Co")

        assert message == {
            "type": "image",
            "image": {"link": "https://cdn.shopify.com/logo.png", "caption": "Acme Snow Co"},
        }

    def test_a_caption_from_data_is_cut_to_fit(self):
        message = image_message("https://cdn.shopify.com/logo.png", caption="x" * 1025)

        assert len(message["image"]["caption"]) == 1024
        assert message["image"]["caption"].endswith("…")


class TestReplyButtons:
    def test_the_message_has_meta_s_shape(self):
        message = reply_buttons("Delete Monthly report?", [Choice("c1", "Delete")], way_back=MAIN_MENU)

        assert message["type"] == "interactive"
        assert message["interactive"]["type"] == "button"
        assert message["interactive"]["body"] == {"text": "Delete Monthly report?"}
        assert buttons_of(message) == [{"id": "c1", "title": "Delete"}, {"id": "menu", "title": "Main menu"}]
        assert all(button["type"] == "reply" for button in message["interactive"]["action"]["buttons"])

    def test_a_title_of_20_characters_is_kept_and_21_is_cut_with_an_ellipsis(self):
        exactly_20 = "a" * 20
        message = reply_buttons("Pick", [Choice("c1", exactly_20), Choice("c2", "b" * 21)], way_back=MAIN_MENU)

        titles = [button["title"] for button in buttons_of(message)]
        assert titles[0] == exactly_20
        # A name from data is cut to fit, never refused: 19 characters and "…" make 20.
        assert titles[1] == "b" * 19 + "…"
        assert len(titles[1]) == 20

    def test_an_id_of_256_characters_is_allowed_and_257_is_refused(self):
        reply_buttons("Pick", [Choice("x" * 256, "Fine")], way_back=MAIN_MENU)

        # Ids are ours, not data, so an over-long one is a bug.
        with pytest.raises(BuilderError):
            reply_buttons("Pick", [Choice("x" * 257, "Too long")], way_back=MAIN_MENU)

    def test_a_body_of_1024_characters_is_allowed_and_1025_is_refused(self):
        reply_buttons("a" * 1024, [Choice("c1", "OK")], way_back=MAIN_MENU)

        # Longer text goes through text_reply, which splits it.
        with pytest.raises(BuilderError):
            reply_buttons("a" * 1025, [Choice("c1", "OK")], way_back=MAIN_MENU)

    def test_two_choices_and_the_way_back_make_three_and_a_third_choice_is_refused(self):
        message = reply_buttons("Pick", [Choice("c1", "One"), Choice("c2", "Two")], way_back=MAIN_MENU)
        assert len(buttons_of(message)) == 3

        with pytest.raises(BuilderError):
            reply_buttons("Pick", [Choice("c1", "One"), Choice("c2", "Two"), Choice("c3", "Three")], way_back=MAIN_MENU)

    def test_button_titles_must_be_unique(self):
        # Meta requires unique titles when a message has more than one button.
        with pytest.raises(BuilderError):
            reply_buttons("Pick", [Choice("c1", "Same"), Choice("c2", "Same")], way_back=MAIN_MENU)

    def test_an_image_header_shows_above_the_body(self):
        # A product's picture (Step 1.12b); Meta's header for reply buttons may be an image link.
        message = reply_buttons("Blue shirt", [], way_back=MAIN_MENU, image_url="https://cdn.shopify.com/blue.jpg")

        assert message["interactive"]["header"] == {
            "type": "image",
            "image": {"link": "https://cdn.shopify.com/blue.jpg"},
        }

    def test_without_an_image_there_is_no_header(self):
        message = reply_buttons("Blue shirt", [], way_back=MAIN_MENU)

        assert "header" not in message["interactive"]


class TestLists:
    def test_the_message_has_meta_s_shape(self):
        message = list_message(
            "Your items",
            button_label="View items",
            section_title="Items",
            rows=[Row("c1", "Monthly report", "Acme")],
        )

        assert message["type"] == "interactive"
        assert message["interactive"]["type"] == "list"
        assert message["interactive"]["body"] == {"text": "Your items"}
        assert message["interactive"]["action"]["button"] == "View items"
        assert message["interactive"]["action"]["sections"][0]["title"] == "Items"
        assert rows_of(message)[0] == {"id": "c1", "title": "Monthly report", "description": "Acme"}

    def test_row_titles_are_cut_at_24_and_descriptions_at_72(self):
        message = list_message(
            "Pick",
            button_label="View",
            section_title="Items",
            rows=[Row("c1", "a" * 24, "d" * 72), Row("c2", "b" * 25, "e" * 73)],
        )

        first, second = rows_of(message)[:2]
        assert (first["title"], first["description"]) == ("a" * 24, "d" * 72)
        assert second["title"] == "b" * 23 + "…"
        assert second["description"] == "e" * 71 + "…"

    def test_a_row_id_of_200_characters_is_allowed_and_201_is_refused(self):
        list_message("Pick", button_label="View", section_title="Items", rows=[Row("x" * 200, "Fine", "")])

        with pytest.raises(BuilderError):
            list_message("Pick", button_label="View", section_title="Items", rows=[Row("x" * 201, "Too long", "")])

    def test_the_button_label_is_cut_at_20_and_the_section_title_at_24(self):
        message = list_message("Pick", button_label="v" * 21, section_title="s" * 25, rows=[Row("c1", "One", "")])

        assert message["interactive"]["action"]["button"] == "v" * 19 + "…"
        assert message["interactive"]["action"]["sections"][0]["title"] == "s" * 23 + "…"

    def test_no_message_has_more_than_10_rows(self):
        # 7 items, plus Previous, Next and Main menu, is exactly Meta's limit of 10.
        message = list_message(
            "Pick",
            button_label="View",
            section_title="Items",
            rows=[Row(f"c{n}", f"Item {n}", "") for n in range(7)],
            previous=Row("p1", "Previous", "Page 1"),
            next=Row("n1", "Next", "Page 3"),
        )

        assert len(rows_of(message)) == 10


class TestLinkButtons:
    def test_the_message_has_meta_s_shape(self):
        message = link_button("Pay for your plan", display_text="Pay now", url="https://example.com/pay/abc")

        assert message["type"] == "interactive"
        assert message["interactive"]["type"] == "cta_url"
        assert message["interactive"]["action"] == {
            "name": "cta_url",
            "parameters": {"display_text": "Pay now", "url": "https://example.com/pay/abc"},
        }

    def test_the_display_text_is_cut_at_20(self):
        message = link_button("Pay", display_text="p" * 21, url="https://example.com/pay/abc")

        assert message["interactive"]["action"]["parameters"]["display_text"] == "p" * 19 + "…"


class TestFlowMessages:
    def test_the_message_opens_the_flow_with_its_data_pre_filled(self):
        message = flow_message(
            "Create an item",
            flow_id="1234567890",
            flow_token="signed-token",
            cta="Open form",
            screen="ITEM",
            data={"organizations": [{"id": "c1", "title": "Acme"}]},
        )

        assert message["type"] == "interactive"
        assert message["interactive"]["type"] == "flow"
        parameters = message["interactive"]["action"]["parameters"]
        assert message["interactive"]["action"]["name"] == "flow"
        assert parameters["flow_message_version"] == "3"
        assert parameters["flow_id"] == "1234567890"
        assert parameters["flow_token"] == "signed-token"
        assert parameters["flow_cta"] == "Open form"
        # navigate opens the first screen with this data, so no Flow endpoint is needed (D9).
        assert parameters["flow_action"] == "navigate"
        assert parameters["flow_action_payload"] == {
            "screen": "ITEM",
            "data": {"organizations": [{"id": "c1", "title": "Acme"}]},
        }

    def test_pre_filled_data_must_not_be_empty(self):
        # Meta needs a non-empty flow_action_payload.data for navigate.
        with pytest.raises(BuilderError):
            flow_message("Create", flow_id="1", flow_token="t", cta="Open", screen="ITEM", data={})

    def test_the_call_to_action_is_cut_at_30(self):
        message = flow_message("Create", flow_id="1", flow_token="t", cta="c" * 31, screen="ITEM", data={"a": 1})

        assert message["interactive"]["action"]["parameters"]["flow_cta"] == "c" * 29 + "…"


class TestLongText:
    def text_of(self, message):
        """The text a message shows, whether plain text or the body of a button message."""
        if message["type"] == "text":
            return message["text"]["body"]
        return message["interactive"]["body"]["text"]

    def test_a_long_reply_is_split_without_losing_or_reordering_anything(self):
        # About 6,000 characters of words, so it must be split.
        text = " ".join(f"word{n}" for n in range(1000))

        messages = text_reply(text)

        assert len(messages) > 1
        assert "".join(self.text_of(message) for message in messages) == text
        # Every part but the last is plain text, within Meta's 4096 characters...
        for message in messages[:-1]:
            assert message["type"] == "text"
            assert len(message["text"]["body"]) <= 4096
        # ...and the last carries the way back, within the 1024 of a button message's body.
        assert len(self.text_of(messages[-1])) <= 1024

    def test_a_split_never_cuts_a_word_in_half_when_it_can_avoid_it(self):
        text = " ".join(f"word{n}" for n in range(1000))

        for message in text_reply(text)[:-1]:
            # Each earlier part ends after a space, so the next starts on a whole word.
            assert self.text_of(message).endswith(" ")

    def test_an_empty_reply_is_refused(self):
        with pytest.raises(BuilderError):
            text_reply("")
