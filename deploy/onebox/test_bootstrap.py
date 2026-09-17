import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('onebox_bootstrap',Path(__file__).with_name('bootstrap.py'))
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)

class BootstrapTests(unittest.TestCase):
    def test_restart_preserves_secrets_and_can_update_domain(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{},clear=True), patch.object(bootstrap.os,'chown'):
            root=Path(temp)/'runtime';route=Path(temp)/'route'
            bootstrap.prepare(root,route);a=json.loads((root/'settings.json').read_text())
            with patch.dict(os.environ,{'IB_SITE':'school.example.org','POSTGRES_PASSWORD':'must-not-replace'}):bootstrap.prepare(root,route)
            b=json.loads((root/'settings.json').read_text())
            for key in ('POSTGRES_PASSWORD','DJANGO_SECRET_KEY','MFA_ENCRYPTION_KEY','ADMIN_PASSWORD'):self.assertEqual(a[key],b[key])
            self.assertEqual(b['SITE_ADDRESS'],'school.example.org')
            self.assertEqual((root/'settings.json').stat().st_mode & 0o777,0o600)
    def test_legacy_keys_import_and_invalid_domain(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,{'POSTGRES_PASSWORD':'existing','DJANGO_SECRET_KEY':'existing-key'},clear=True), patch.object(bootstrap.os,'chown'):
            root=Path(temp)/'runtime';route=Path(temp)/'route'
            bootstrap.prepare(root,route);data=json.loads((root/'settings.json').read_text())
            self.assertEqual(data['POSTGRES_PASSWORD'],'existing');self.assertEqual(data['DJANGO_SECRET_KEY'],'existing-key')
            with patch.dict(os.environ,{'IB_SITE':'https://bad/path'}):
                with self.assertRaises(ValueError):bootstrap.prepare(root,route)

if __name__=='__main__':unittest.main()
