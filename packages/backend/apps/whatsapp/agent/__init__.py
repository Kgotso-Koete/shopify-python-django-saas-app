"""
The assistant's runtime (plan Step 1.13, decision D12): agentic mode answers a message by letting a
model call a fixed list of tools. The channel stays generic: the tools, and the instructions that
go with them, belong to the handler that calls service.respond (apps.whatsapp_saas, for an organization's team).

- provider.py: the one call to OpenAI's Responses API, with store: false
- tools.py: the tools a handler offers, their strict schemas, and running them
- history.py: the conversation's history, kept in WhatsAppAgentItem
- service.py: one message's loop, from the user's words to a reply
"""
