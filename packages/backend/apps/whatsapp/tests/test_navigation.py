"""
Tests for the way back in every message (plan decision D17, user story 21): nobody is ever stuck.

- Every interactive message's footer says "Send *menu* at any time" (*menu* is bold in WhatsApp).
- Lists hold at most 7 items, so Previous, Next and Main menu always fit in Meta's 10 rows.
- A reply-button message keeps one of its 3 buttons for Back or Main menu.
- Plain text goes out as a message with a Main menu button.

The builders enforce this, so a screen can't be written without a way back.

Kind of test: unit (agents.md section 2.5). Why: the builders on their own, with no database or
network; nothing is faked.
"""

import pytest

from ..builders import (
    MAIN_MENU,
    WAY_BACK_FOOTER,
    BuilderError,
    Choice,
    Row,
    flow_message,
    link_button,
    list_message,
    reply_buttons,
    text_reply,
)

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db


def rows_of(message):
    return [row for section in message["interactive"]["action"]["sections"] for row in section["rows"]]


def button_titles(message):
    return [button["reply"]["title"] for button in message["interactive"]["action"]["buttons"]]


class TestTheFooter:
    def test_the_footer_text_is_the_way_back_reminder(self):
        assert WAY_BACK_FOOTER == "Send *menu* at any time"

    @pytest.mark.parametrize(
        "message",
        [
            reply_buttons("Pick", [Choice("c1", "One")], way_back=MAIN_MENU),
            list_message("Pick", button_label="View", section_title="Items", rows=[Row("c1", "One", "")]),
            link_button("Pay", display_text="Pay now", url="https://example.com/pay/abc"),
            flow_message("Create", flow_id="1", flow_token="t", cta="Open", screen="ITEM", data={"a": 1}),
        ],
        ids=["reply-buttons", "list", "link-button", "flow"],
    )
    def test_every_interactive_message_carries_it(self, message):
        assert message["interactive"]["footer"] == {"text": WAY_BACK_FOOTER}


class TestLists:
    def test_seven_items_are_allowed_and_eight_are_refused(self):
        seven = [Row(f"c{n}", f"Item {n}", "") for n in range(7)]
        list_message("Pick", button_label="View", section_title="Items", rows=seven)

        # An eighth item would leave no room for Previous, Next and Main menu.
        with pytest.raises(BuilderError):
            list_message("Pick", button_label="View", section_title="Items", rows=[*seven, Row("c7", "Item 7", "")])

    def test_main_menu_is_always_the_last_row(self):
        message = list_message("Pick", button_label="View", section_title="Items", rows=[Row("c1", "One", "")])

        assert rows_of(message)[-1]["id"] == MAIN_MENU.id
        assert rows_of(message)[-1]["title"] == "Main menu"

    def test_previous_and_next_come_after_the_items_and_before_main_menu_when_given(self):
        message = list_message(
            "Pick",
            button_label="View",
            section_title="Items",
            rows=[Row("c1", "One", "")],
            previous=Row("p1", "Previous", "Page 1"),
            next=Row("n1", "Next", "Page 3"),
        )

        assert [row["id"] for row in rows_of(message)] == ["c1", "p1", "n1", MAIN_MENU.id]

    def test_there_is_no_previous_on_the_first_page_and_no_next_on_the_last(self):
        first_page = list_message(
            "Pick",
            button_label="View",
            section_title="Items",
            rows=[Row("c1", "One", "")],
            next=Row("n1", "Next", ""),
        )

        assert [row["id"] for row in rows_of(first_page)] == ["c1", "n1", MAIN_MENU.id]


class TestReplyButtons:
    def test_the_way_back_is_one_of_the_three_buttons(self):
        message = reply_buttons("Delete it?", [Choice("c1", "Delete")], way_back=MAIN_MENU)

        assert button_titles(message) == ["Delete", "Main menu"]

    def test_back_works_as_the_way_back_too(self):
        # From a detail screen, Back returns to the list it came from.
        message = reply_buttons("Monthly report", [Choice("c1", "Edit")], way_back=Choice("c9", "Back"))

        assert button_titles(message) == ["Edit", "Back"]

    def test_a_message_without_a_way_back_is_refused(self):
        with pytest.raises(BuilderError):
            reply_buttons("Delete it?", [Choice("c1", "Delete")], way_back=None)


class TestPlainText:
    def test_a_short_reply_is_a_message_with_a_main_menu_button(self):
        [message] = text_reply("Your item was created.")

        assert message["type"] == "interactive"
        assert message["interactive"]["body"] == {"text": "Your item was created."}
        assert button_titles(message) == ["Main menu"]

    def test_a_long_reply_ends_with_the_main_menu_button(self):
        messages = text_reply(" ".join(f"word{n}" for n in range(1000)))

        assert button_titles(messages[-1]) == ["Main menu"]
