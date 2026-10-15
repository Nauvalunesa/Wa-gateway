import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from neonize.proto.Neonize_pb2 import JID
from pydantic import ValidationError

import gateway.messages.airich as rich_builder
import gateway.messages.models as models
import gateway.routes.airich as airich_api


class AIRichTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_supported_blocks_build_into_wire_message(self):
        blocks = [
            {'type': 'text', 'text': '**Hello** [Neonize](https://github.com/krypton-byte/neonize)'},
            {'type': 'code', 'language': 'html', 'code': '<h1>Hello</h1>'},
            {'type': 'table', 'table': [['Name', 'Price'], ['A', '10']]},
            {'type': 'image', 'url': ['https://example.com/a.jpg', 'https://example.com/b.jpg']},
            {'type': 'video', 'url': 'https://example.com/video.mp4', 'duration': 5},
            {'type': 'source', 'source': {'display_name': 'Docs', 'url': 'https://example.com'}},
            {'type': 'product', 'product': {'title': 'A', 'price': '$10'}},
            {'type': 'reels', 'reel': {'username': 'creator', 'reels_title': 'A'}},
            {'type': 'post', 'post': {'title': 'Post', 'post_type': 'IMAGE'}},
            {'type': 'tip', 'text': 'A tip'},
            {'type': 'suggest', 'suggestions': ['More', 'Next']},
        ]
        data = models.AIRichPayload(to='244952155419', title='Test', footer='Footer', blocks=blocks)
        result = await airich_api.api_airich_preview(data, username='test')
        self.assertFalse(result['sent'])
        msg = await rich_builder.build_airich_message(data, mentioned_jids=['244952155419@s.whatsapp.net'])
        rich = msg.botForwardedMessage.message.richResponseMessage
        self.assertEqual(list(rich.contextInfo.mentionedJID), ['244952155419@s.whatsapp.net'])
        wire = json.loads(rich.unifiedResponse.data)
        self.assertGreaterEqual(len(wire['sections']), len(blocks))
        self.assertIn('<h1>', rich.submessages[1].codeMetadata.codeBlocks[0].codeContent)
        self.assertEqual(msg.messageContextInfo.botMetadata.messageDisclaimerText, 'Test')
        self.assertTrue(msg.SerializeToString())

    async def test_bad_blocks_are_rejected(self):
        for block in [
            {'type': 'html', 'text': '<h1>Hello</h1>'},
            {'type': 'text'},
            {'type': 'code', 'code': 'x'},
            {'type': 'table', 'table': [['a'], ['b', 'c']]},
            {'type': 'source', 'source': {'invalid_field': 'x'}},
            {'type': 'video', 'url': 'x', 'duration': -1},
        ]:
            with self.subTest(block=block), self.assertRaises(ValidationError):
                models.AIRichPayload(to='x', blocks=[block])
        with self.assertRaises(ValidationError):
            models.AIRichPayload(to='x', submessages=[])

    async def test_get_and_post_send_same_message(self):
        client = AsyncMock()
        jid = JID(User='244952155419', Server='s.whatsapp.net')
        values = {'blocks': [{'type': 'TEXT', 'text': 'Hello'}]}
        with patch.object(airich_api, 'get_client', return_value=(client, 'device')), \
             patch.object(airich_api, 'get_actual_jid', AsyncMock(return_value=jid)), \
             patch.object(airich_api, 'log_message', AsyncMock()):
            response = await airich_api.api_send_airich_get(None, '244952155419', json.dumps(values), username='test')
        self.assertTrue(response['success'])
        sent = client.send_message.await_args.args[1]
        self.assertEqual(sent.botForwardedMessage.message.richResponseMessage.submessages[0].messageText, 'Hello')
        for bad in ['not json', '[]', '{"blocks":[{"type":"html"}]}']:
            with self.assertRaises(HTTPException) as context:
                await airich_api.api_send_airich_get(None, 'x', bad, username='test')
            self.assertEqual(context.exception.status_code, 422)

    async def test_html_preserves_script_and_order_without_double_base64(self):
        html = '<button>音</button><script>window.test=1</script>'
        data = models.AIRichPayload(to='x', blocks=[
            {'type': 'text', 'text': 'Before'},
            {'type': 'html', 'html': html, 'trusted_sources': ['example.com']},
            {'type': 'text', 'text': 'After'},
        ])
        msg = await rich_builder.build_airich_message(data, mentioned_jids=['1@s.whatsapp.net'])
        rich = msg.botForwardedMessage.message.richResponseMessage
        wire = json.loads(rich.unifiedResponse.data)
        primitive = wire['sections'][1]['view_model']['primitive']
        self.assertEqual(primitive['payload'], html)
        self.assertEqual(primitive['trusted_sources'], ['example.com'])
        self.assertEqual(primitive['__typename'], 'GenAIaeacdsnwHtmlPrimitive')
        self.assertEqual(rich.submessages[0].messageText, 'Before')
        self.assertEqual(rich.submessages[-1].messageText, 'After')
        self.assertEqual(list(rich.contextInfo.mentionedJID), ['1@s.whatsapp.net'])
        self.assertTrue(msg.SerializeToString())

    async def test_raw_payload(self):
        data = models.AIRichPayload(to='x', submessages=[{'messageType': 1, 'messageText': 'Hello'}], unified={'sections': []})
        msg = await rich_builder.build_airich_message(data)
        self.assertEqual(msg.botForwardedMessage.message.richResponseMessage.submessages[0].messageText, 'Hello')
