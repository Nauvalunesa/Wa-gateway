"""Build customer-service replies with buttons, lists, or numbered text."""
import json

from google.protobuf.json_format import ParseDict
from neonize.ext.interactive_message import ButtonV2Message
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import InteractiveMessage, Message

from gateway.messages.cs_models import CSConfig, CSNode


def option_token(revision: str, node: CSNode, option_id: str) -> str:
    return f"cs:{revision}:{node.id}:{option_id}"


def reply_content(config: CSConfig, node: CSNode, name: str, revision: str) -> dict:
    text = node.text.replace("{name}", name).replace("{business}", config.business_name)
    if node.handoff and config.admin_phone:
        text += f"\n\nAdmin: https://wa.me/{config.admin_phone}"
    options = [{"id": option_token(revision, node, o.id), "label": o.label, "target": o.target} for o in node.options]
    if options:
        text += "\n\n" + "\n".join(f"{index}. {o['label']}" for index, o in enumerate(options, 1))
    return {"title": node.title, "body": text, "footer": config.business_name,
            "options": options, "mode": config.reply_mode, "node": node.id, "handoff": node.handoff}


async def build_cs_message(content: dict, client=None):
    options = content["options"]
    if not options or content["mode"] == "text":
        return Message(conversation=f"*{content['title']}*\n\n{content['body']}")
    if content["mode"] == "legacy":
        builder = ButtonV2Message()
        builder.set_body(content["body"])
        builder.set_title(content["title"])
        builder.set_footer(content["footer"])
        for option in options:
            builder.add_button(option["label"], option["id"])
        return await builder.prepare_asend(client)
    if content["mode"] == "list" or len(options) > 3:
        params = {"title": "Pilih layanan", "sections": [{"title": content["title"], "rows": [
            {"id": option["id"], "title": option["label"]} for option in options
        ]}]}
        buttons = [{"name": "single_select", "buttonParamsJSON": json.dumps(params, ensure_ascii=False)}]
    else:
        buttons = [{"name": "quick_reply", "buttonParamsJSON": json.dumps(
            {"display_text": option["label"], "id": option["id"]}, ensure_ascii=False
        )} for option in options]
    interactive = ParseDict({
        "header": {"title": content["title"], "hasMediaAttachment": False},
        "body": {"text": content["body"]}, "footer": {"text": content["footer"]},
        "nativeFlowMessage": {"buttons": buttons},
    }, InteractiveMessage())
    return Message(interactiveMessage=interactive)
