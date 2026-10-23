"""
The WhatsApp Flow JSON this app publishes (plan Step 1.11, decision D9): one form per file, sent
pre-filled with flow_action "navigate" and no data endpoint. Published once by the
whatsapp_publish_flows command; their ids are stored in apps.whatsapp's WhatsAppFlow.

Flow JSON reference: https://developers.facebook.com/docs/whatsapp/flows/reference/flowjson
Components: https://developers.facebook.com/docs/whatsapp/flows/reference/components
"""

from pathlib import Path

FLOWS_DIR = Path(__file__).parent

# Each form's file name (without .json) and its one screen, which the Flow message opens on.
SCREEN_NAMES = {
    "item": "ITEM",
    "organization": "ORGANIZATION",
}
