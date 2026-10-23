"""
Publishing this app's WhatsApp Flows (the forms in apps/whatsapp_saas/flows/) to an internal
communications number's WhatsApp Business account (plan Step 1.11, decision D9, Step 1.17).

Used when a number is connected (tasks.publish_forms) and by the whatsapp_publish_flows command. A
form whose JSON hasn't changed since it was last published is left alone; a changed one is published
as a new Flow, since Meta doesn't allow editing a published one.
"""

from apps.whatsapp.services import flows

from .flows import FLOWS_DIR


def publish_forms(account) -> list[tuple[str, object, bool]]:
    """
    Publish every form to `account`'s WhatsApp Business account. Returns (name, WhatsAppFlow,
    published) for each; raises apps.whatsapp.client.SendError, with Meta's words, if Meta refuses one.
    """
    published = []
    for path in sorted(FLOWS_DIR.glob("*.json")):
        flow, changed = flows.publish(account, path.stem, path.read_text(encoding="utf-8"))
        published.append((path.stem, flow, changed))
    return published
