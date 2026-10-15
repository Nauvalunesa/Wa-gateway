"""AI Rich protobuf construction, including HTML blocks."""
import json

from google.protobuf.json_format import MessageToDict, ParseDict
from neonize.ext.interactive_message import AIRichMessage
from neonize.proto.waAICommon.WAWebProtobufsAICommon_pb2 import (
    AIRichResponseUnifiedResponse,
    BotMetadata,
    ForwardedAIBotMessageInfo,
)
from neonize.proto.waAICommonDeprecated.WAAICommonDeprecated_pb2 import AIRichResponseSubMessage
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
    AIRichResponseMessage,
    ContextInfo,
    FutureProofMessage,
    Message as WAMessage,
    MessageContextInfo,
)

from gateway.messages.cards import AIRICH_CARDS
from gateway.messages.models import AIRichPayload


async def build_airich_message(data: AIRichPayload, client=None, mentioned_jids=None):
    context = ContextInfo(mentionedJID=mentioned_jids or [])
    if data.submessages is not None:
        subs = [ParseDict(sub, AIRichResponseSubMessage()) for sub in data.submessages]
        context.forwardingScore = 1
        context.isForwarded = True
        context.forwardedAiBotMessageInfo.CopyFrom(ForwardedAIBotMessageInfo(botJID="0@bot"))
        context.forwardOrigin = ContextInfo.META_AI
        rich = AIRichResponseMessage(messageType=1, submessages=subs,
            unifiedResponse=AIRichResponseUnifiedResponse(data=json.dumps(data.unified).encode()),
            contextInfo=context)
        return WAMessage(messageContextInfo=MessageContextInfo(deviceListMetadataVersion=2,
            botMetadata=BotMetadata(messageDisclaimerText=data.title or "")),
            botForwardedMessage=FutureProofMessage(message=WAMessage(richResponseMessage=rich)))

    if any(block.type == "html" for block in data.blocks):
        sections, subs = [], []
        for block in data.blocks:
            if block.type == "html":
                sections.append({"view_model": {
                    "primitive": {"__typename": "GenAIaeacdsnwHtmlPrimitive",
                                  "payload": block.html, "trusted_sources": block.trusted_sources},
                    "__typename": "GenAISingleLayoutViewModel"}})
                subs.append({"messageType": 2, "messageText": block.text or data.title or "HTML interactif"})
            else:
                part = await build_airich_message(data.model_copy(update={"blocks": [block], "title": None, "footer": None}), client)
                rich = part.botForwardedMessage.message.richResponseMessage
                sections.extend(json.loads(rich.unifiedResponse.data).get("sections", []))
                subs.extend(MessageToDict(sub) for sub in rich.submessages)
        if data.footer:
            part = await build_airich_message(AIRichPayload(to=data.to, blocks=[{"type": "text", "text": data.footer}]), client)
            rich = part.botForwardedMessage.message.richResponseMessage
            sections.extend(json.loads(rich.unifiedResponse.data).get("sections", []))
            subs.extend(MessageToDict(sub) for sub in rich.submessages)
        import uuid
        raw = data.model_copy(update={"blocks": [], "submessages": subs,
            "unified": {"response_id": str(uuid.uuid4()), "sections": sections}})
        return await build_airich_message(raw, client, mentioned_jids)

    msg = AIRichMessage()
    if data.title:
        msg.set_title(data.title)
    if data.footer:
        msg.set_footer(data.footer)
    msg.set_context_info(context)
    for block in data.blocks:
        kind = block.type
        if kind == "text":
            msg.add_text(block.text, latex=block.latex, hyperlink=block.hyperlink, citation=block.citation)
        elif kind == "code":
            msg.add_code(block.language, block.code)
        elif kind == "table":
            msg.add_table(block.table)
        elif kind == "image":
            msg.add_image(block.url)
        elif kind == "video":
            msg.add_video(block.url, duration=block.duration)
        elif kind in AIRICH_CARDS:
            items = getattr(block, "reel" if kind == "reels" else kind)
            cards = [AIRICH_CARDS[kind](**item) for item in (items if isinstance(items, list) else [items])]
            getattr(msg, {"source": "add_source", "product": "add_product", "reels": "add_reels", "post": "add_post"}[kind])(cards)
        elif kind == "tip":
            msg.add_tip(block.text)
        elif kind == "suggest":
            msg.add_suggest(block.suggestions)
    return await msg.prepare_asend(client)
