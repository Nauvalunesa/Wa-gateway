"""Integration checks for the modular application's startup and composition."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

from gateway.application import create_app
from gateway.config import PROJECT_ROOT


class ApplicationTests(unittest.TestCase):
    def test_service_imports_do_not_initialize_app_or_create_runtime_data(self):
        with tempfile.TemporaryDirectory(prefix="utusan-imports-") as directory:
            environment = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT))
            result = subprocess.run(
                [sys.executable, "-c", "import sys; import gateway.messages.airich; "
                 "import gateway.whatsapp.clients; import gateway.routes.messages; "
                 "assert 'gateway.application' not in sys.modules"],
                cwd=directory, env=environment, text=True, capture_output=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_factory_serves_frontend_and_authenticated_routes_from_runtime_cwd(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="utusan-app-") as directory:
            try:
                os.chdir(directory)
                app = create_app()
                with TestClient(app, base_url="https://testserver") as client:
                    self.assertEqual(client.get("/login").status_code, 200)
                    self.assertEqual(client.get("/api/web/me").status_code, 401)
                    self.assertEqual(client.get("/api/status").status_code, 401)
                    self.assertEqual(client.get("/api/nonexistent").status_code, 404)
                    self.assertTrue(Path("storage/system.db").is_file())
                    self.assertTrue(Path("storage/.session-secret").is_file())
            finally:
                os.chdir(original_cwd)
