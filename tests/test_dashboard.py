import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import main


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='utusan-dashboard-')
        self.original_cwd = os.getcwd()
        os.chdir(self.directory.name)
        Path('storage').mkdir()
        self.client = TestClient(main.app, base_url="https://testserver")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        os.chdir(self.original_cwd)
        self.directory.cleanup()

    def register(self, username='tester'):
        response = self.client.post('/api/web/register', json={'username':username,'password':'testing-password'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_login_register_and_logout(self):
        self.assertEqual(self.client.get('/api/web/me').status_code,401)
        account=self.register()
        self.assertEqual(self.client.get('/api/web/me').json(),account)
        self.assertEqual(self.client.post('/api/web/register',json={'username':'tester','password':'testing-password'}).status_code,409)
        self.client.post('/api/web/logout')
        self.assertEqual(self.client.get('/api/web/devices').status_code,401)
        self.assertEqual(self.client.post('/api/web/login',json={'username':'tester','password':'wrong-password'}).status_code,401)
        self.assertEqual(self.client.post('/api/web/login',json={'username':'tester','password':'testing-password'}).status_code,200)

    def test_stats_logs_and_account_isolation(self):
        self.register('first')
        import asyncio
        asyncio.run(main.log_message('first','device','628123456789','Example','OUTGOING'))
        overview=self.client.get('/api/web/overview').json()
        self.assertEqual(overview['messages'],1)
        self.assertEqual(len(overview['daily']),7)
        self.assertEqual(self.client.get('/api/web/logs?search=Example').json()['total'],1)
        self.assertEqual(self.client.get('/api/web/logs?search=no-match').json()['total'],0)
        self.client.post('/api/web/logout')
        self.register('second')
        self.assertEqual(self.client.get('/api/web/logs').json()['total'],0)
        self.assertEqual(self.client.get('/api/web/devices').json()['devices'],[])

    def test_key_rotation_and_csrf(self):
        user=self.register()
        headers={'x-api-key':user['api_key']}
        self.assertEqual(self.client.get('/api/status',headers=headers).status_code,200)
        key=self.client.post('/api/web/api-key').json()['api_key']
        self.assertNotEqual(key,user['api_key'])
        self.assertEqual(self.client.get('/api/status',headers=headers).status_code,403)
        self.assertEqual(self.client.post('/api/web/api-key',headers={'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/web/logout',headers={'Origin':'https://testserver'}).status_code,200)

    def test_frontend_and_host(self):
        for path in ['/login','/register','/','/devices','/tools','/airich','/blast','/channels','/logs','/settings']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertIn('Utusan',response.text)
            self.assertNotIn('_nicegui',response.text)
        self.assertEqual(self.client.get('/login',headers={'Host':'utusan.chat'}).status_code,200)
        self.assertEqual(self.client.get('/login',headers={'Host':'wa.mustikapay.app'}).status_code,403)
        self.assertEqual(self.client.get('/api/unknown').status_code,404)
        self.assertEqual(self.client.get('/api/web/logs?limit=999').status_code,401)
