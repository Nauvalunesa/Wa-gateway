import asyncio
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict
from neonize.proto.Neonize_pb2 import JID
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message

from gateway.application import create_app
from gateway.messages.crm_models import validate_raw
from gateway.services import crm
from gateway.services.crm_bot import try_raw_crm
from gateway.services.crm_send import run_item
from gateway.services.crm_access import set_owner_phones
from gateway.services.jid_conversion import convert_jid


async def serialize_send(jid,message,*args,**kwargs):
    # Neonize serializes both objects before calling its native transport.
    jid.SerializeToString()
    message.SerializeToString()


async def serialize_document(jid,*args,**kwargs):
    jid.SerializeToString()


class RawCRMTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.original=os.getcwd();self.directory=tempfile.TemporaryDirectory(prefix='utusan-crm-');os.chdir(self.directory.name)
        self.client=AsyncMock();self.phone='628123456789';self.owner=self.phone+'@s.whatsapp.net'
        self.client.send_message.side_effect=serialize_send
        self.client.send_document.side_effect=serialize_document
        self.log=patch('gateway.services.crm_send.log_message',new_callable=AsyncMock);self.log.start()

    async def asyncTearDown(self):
        self.log.stop();os.chdir(self.original);self.directory.cleanup()

    def message(self,text='crm',raw=None,server='g.us',owner=True,event_id='crm-1'):
        return SimpleNamespace(from_me=owner,is_edit=False,text=text,chat=JID(User='120363123456789',Server=server),
            info=SimpleNamespace(ID=event_id),quoted=SimpleNamespace(message=raw) if raw else None)

    async def command(self,message): return await try_raw_crm(self.client,'owner',self.phone,message)

    def menu(self):
        wire=self.client.send_message.await_args.args[1]
        return [json.loads(b.buttonParamsJSON)['id'] for b in wire.interactiveMessage.nativeFlowMessage.buttons]

    async def test_quote_menu_and_replay_preserve_fields_and_send_once_to_source_group(self):
        raw=Message(extendedTextMessage={'text':'Pesan asli','contextInfo':{'mentionedJID':['628222222222@s.whatsapp.net']}})
        await self.command(self.message(raw=raw))
        for call in self.client.send_message.await_args_list:
            self.assertEqual(call.args[0].User,self.phone)
        run,save,action=self.menu()
        self.assertIn(json.dumps(MessageToDict(raw),ensure_ascii=False,indent=2),self.client.send_message.await_args_list[0].args[1].conversation)
        await self.command(self.message(text=save,event_id='save-1'))
        await self.command(self.message(text=save,event_id='save-2'))
        self.assertEqual((await crm.list_items('owner','saved',1))['total'],1)
        await self.command(self.message(text=action,event_id='action-1'))
        item=(await crm.list_items('owner','action',1))['items'][0]
        self.assertEqual(item['payload'],MessageToDict(raw));self.assertEqual(item['source_chat'],'120363123456789@g.us')
        self.client.send_message.reset_mock()
        await self.command(self.message(text=run,event_id='run-1'))
        await self.command(self.message(text=run,event_id='run-2'))
        group_calls=[call for call in self.client.send_message.await_args_list if call.args[0].Server=='g.us']
        self.assertEqual(len(group_calls),1);self.assertEqual(group_calls[0].args[1],raw)

    async def test_private_quotes_large_document_and_nonowner_cannot_access(self):
        raw=Message(conversation='A'*5000)
        self.assertFalse(await self.command(self.message(raw=raw,owner=False)))
        self.client.send_message.assert_not_awaited()
        await self.command(self.message(raw=raw,server='s.whatsapp.net'))
        self.assertEqual(json.loads(self.client.send_document.await_args.args[1]),MessageToDict(raw))
        token=self.menu()[1];self.client.send_message.reset_mock()
        self.assertFalse(await self.command(self.message(text=token,owner=False)))
        self.client.send_message.assert_not_awaited()
        await self.command(self.message(text=token))
        self.assertEqual((await crm.list_items('owner',None,1))['total'],1)

    async def test_extra_owner_pn_and_lid_authorization_and_button_binding(self):
        additional='6281776348790';set_owner_phones('owner',[additional])
        raw=Message(conversation='Owner tambahan')
        command=self.message(raw=raw,owner=False)
        command.sender=JID(User='999999999999',Server='lid')
        command.sender_alt=JID(User=additional,Server='s.whatsapp.net')
        await self.command(command)
        self.assertEqual(self.client.send_message.await_args.args[0].User,additional)
        token=self.menu()[1]
        # Linked owner cannot reuse another owner's draft button.
        await self.command(self.message(text=token))
        self.assertEqual((await crm.list_items('owner',None,1))['total'],0)
        command.text=token;command.sender_alt=None
        self.client.get_pn_from_lid.return_value=JID(User=additional,Server='s.whatsapp.net')
        await self.command(command)
        self.assertEqual((await crm.list_items('owner',None,1))['total'],1)
        self.client.get_pn_from_lid.return_value=JID(User='628999999999',Server='s.whatsapp.net')
        self.assertFalse(await self.command(command))
        self.client.get_pn_from_lid.side_effect=RuntimeError('no mapping')
        self.assertFalse(await self.command(command))
        set_owner_phones('owner',[])
        command.sender=JID(User=additional,Server='s.whatsapp.net')
        self.assertFalse(await self.command(command))

    async def test_complete_quoted_wrapper_is_preserved_without_participant(self):
        wrapped=Message(viewOnceMessage={'message':{'imageMessage':{'caption':'Foto','URL':'https://example.com/image'}}})
        command=self.message()
        command._real_msg=Message(extendedTextMessage={'text':'crm','contextInfo':{'quotedMessage':wrapped}})
        await self.command(command)
        item_id=self.menu()[0].split(':')[1]
        self.assertEqual((await crm.get_item('owner',item_id))['payload'],MessageToDict(wrapped))

    async def test_bidirectional_jid_conversion_and_missing_mapping(self):
        self.client.get_lid_from_pn.return_value=JID(User='123456789123',Server='lid')
        converted=await convert_jid(self.client,'6281776348790@s.whatsapp.net')
        self.assertEqual(converted['result'],'123456789123@lid')
        self.client.get_lid_from_pn.await_args.args[0].SerializeToString()
        self.client.get_pn_from_lid.return_value=JID(User='6281776348790',Server='s.whatsapp.net')
        self.assertEqual((await convert_jid(self.client,'123456789123@lid'))['result'],'6281776348790@s.whatsapp.net')
        self.client.get_pn_from_lid.await_args.args[0].SerializeToString()
        self.client.get_pn_from_lid.return_value=JID()
        with self.assertRaises(HTTPException) as error:await convert_jid(self.client,'123456789123@lid')
        self.assertEqual(error.exception.status_code,404)
        with self.assertRaises(HTTPException) as error:await convert_jid(self.client,'120363123456789@g.us')
        self.assertEqual(error.exception.status_code,422)

    async def test_missing_quote_expiry_and_device_account_isolation(self):
        await self.command(self.message())
        self.assertIn('Reply pesan',self.client.send_message.await_args.args[1].conversation)
        item=await crm.create_item('owner','test','draft',{'conversation':'Hello'},self.phone,self.owner,'628222222222@s.whatsapp.net')
        for username,phone,owner in [('other',self.phone,self.owner),('owner','628999999999',self.owner)]:
            with self.assertRaises(HTTPException) as error:await crm.get_item(username,item['id'],phone,owner)
            self.assertEqual(error.exception.status_code,404)
        async with crm.database('owner') as db:
            await db.execute('UPDATE items SET expires_at=0.1 WHERE id=?',(item['id'],));await db.commit()
        await self.command(self.message(text=f'crm:{item["id"]}:run'))
        self.assertIn('kedaluwarsa',self.client.send_message.await_args.args[1].conversation)
        self.assertFalse(any(call.args[0].Server=='g.us' for call in self.client.send_message.await_args_list))

    async def test_failed_and_uncertain_sends_are_not_retried_and_concurrent_claims_deduplicate(self):
        item=await crm.create_item('owner','test','saved',{'conversation':'Hello'})
        self.client.send_message.side_effect=TimeoutError()
        with self.assertRaises(HTTPException) as error:await run_item(self.client,'owner',item,self.phone,'628222222222','timeout_123')
        self.assertEqual(error.exception.status_code,504)
        duplicate=await run_item(self.client,'owner',item,self.phone,'628222222222','timeout_123')
        self.assertEqual(duplicate['status'],'uncertain');self.assertTrue(duplicate['duplicate'])
        self.client.send_message.assert_awaited_once()
        self.client.send_message.side_effect=RuntimeError('send failed')
        with self.assertRaises(HTTPException) as error:await run_item(self.client,'owner',item,self.phone,'628222222222','failed_123')
        self.assertEqual(error.exception.status_code,502)
        self.assertEqual((await run_item(self.client,'owner',item,self.phone,'628222222222','failed_123'))['status'],'failed')
        claims=await asyncio.gather(*(crm.claim_execution('owner',item['id'],'concurrent_123') for _ in range(4)))
        self.assertEqual(sum(claimed for claimed,_ in claims),1)

    def test_invalid_raw_fields_empty_and_size_are_rejected(self):
        for payload in ({},{'unknownField':'x'},{'conversation':'x'*(256*1024)},
                        {'interactiveMessage':{'nativeFlowMessage':{'buttons':[{'name':'quick_reply','buttonParamsJson':'{}'}]}}}):
            with self.assertRaises(ValueError):validate_raw(payload)


class CRMAPITests(unittest.TestCase):
    def setUp(self):
        self.original=os.getcwd();self.directory=tempfile.TemporaryDirectory(prefix='utusan-crm-api-');os.chdir(self.directory.name)
        self.http=TestClient(create_app(),base_url='https://testserver');self.http.__enter__()
        self.account=self.http.post('/api/web/register',json={'username':'rawowner','password':'Testing-password'}).json()
        self.base='/api/web/crm/items'

    def tearDown(self):
        self.http.__exit__(None,None,None);os.chdir(self.original);self.directory.cleanup()

    def test_storage_persistence_actions_cookie_auth_csrf_and_cross_account_isolation(self):
        response=self.http.post(self.base,json={'name':'hello','payload':{'conversation':'Hi'}})
        self.assertEqual(response.status_code,201,response.text);item=response.json()
        self.assertEqual(self.http.get(self.base+'/'+item['id']).json()['payload'],{'conversation':'Hi'})
        action=self.http.post(self.base+'/'+item['id']+'/action').json()
        self.assertEqual(self.http.post(self.base+'/'+item['id']+'/action').json()['id'],action['id'])
        self.assertEqual(self.http.get(self.base+'?kind=action').json()['total'],1)
        self.assertEqual(self.http.post(self.base,json={'name':'bad','payload':{},'username':'someone'}).status_code,422)
        self.assertEqual(self.http.post(self.base,json={'name':'bad','payload':{}}).status_code,422)
        self.assertEqual(self.http.post(self.base,json={'name':'x','payload':{'conversation':'Hi'}},headers={'Origin':'https://evil.example'}).status_code,403)
        self.http.post('/api/web/logout')
        self.assertEqual(self.http.get(self.base,headers={'x-api-key':self.account['api_key']}).status_code,401)
        self.http.post('/api/web/register',json={'username':'otherowner','password':'Testing-password'})
        self.assertEqual(self.http.get(self.base).json()['total'],0)
        for method,path in [('get',self.base+'/'+item['id']),('delete',self.base+'/'+item['id']),('post',self.base+'/'+item['id']+'/action')]:
            self.assertEqual(getattr(self.http,method)(path).status_code,404)
        self.assertEqual(self.http.post(self.base+'/'+item['id']+'/run',json={'phone':'628123456789','to':'628222222222','request_id':'foreign_123'}).status_code,404)
        self.http.post('/api/web/logout');self.http.post('/api/web/login',json={'username':'rawowner','password':'Testing-password'})
        self.assertEqual(self.http.get(self.base).json()['total'],2)
        self.assertEqual(self.http.delete(self.base+'/'+item['id']).status_code,200)

    def test_send_exact_saved_payload_and_reject_offline_or_invalid_destination(self):
        item=self.http.post(self.base,json={'name':'hello','payload':{'conversation':'Hi'}}).json()
        body={'phone':'628123456789','to':'120363123456789@g.us','request_id':'replay_123'}
        self.assertEqual(self.http.post(self.base+'/'+item['id']+'/run',json=body).status_code,503)
        client=AsyncMock();client.send_message.side_effect=serialize_send
        with patch('gateway.routes.crm.get_client',return_value=(client,body['phone'])),patch('gateway.services.crm_send.log_message',new_callable=AsyncMock):
            response=self.http.post(self.base+'/'+item['id']+'/run',json=body)
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(self.http.post(self.base+'/'+item['id']+'/run',json=body).json()['duplicate'])
            client.send_message.assert_awaited_once();jid,raw=client.send_message.await_args.args
            self.assertEqual(jid.Server,'g.us');self.assertEqual(raw.conversation,'Hi')
            self.assertEqual(self.http.post(self.base+'/'+item['id']+'/run',json={**body,'to':'status@broadcast','request_id':'invalid_123'}).status_code,422)

    def test_owner_settings_are_account_scoped_and_conversion_requires_owned_device(self):
        self.assertEqual(self.http.post('/api/web/crm/config',json={'owners':['6281776348790']}).status_code,200)
        self.assertEqual(self.http.get('/api/web/crm/config').json()['owners'],['6281776348790'])
        self.assertEqual(self.http.post('/api/web/crm/config',json={'owners':['invalid@lid']}).status_code,422)
        data={'phone':'628123456789','jid':'6281776348790@s.whatsapp.net'}
        self.assertEqual(self.http.post('/api/web/convert-jid',json=data).status_code,503)
        client=AsyncMock();client.get_lid_from_pn.return_value=JID(User='123456789123',Server='lid')
        with patch('gateway.routes.crm.get_client',return_value=(client,data['phone'])):
            self.assertEqual(self.http.post('/api/web/convert-jid',json=data).json()['result'],'123456789123@lid')
        self.http.post('/api/web/logout');self.http.post('/api/web/register',json={'username':'isolatedowner','password':'Testing-password'})
        self.assertEqual(self.http.get('/api/web/crm/config').json()['owners'],[])
