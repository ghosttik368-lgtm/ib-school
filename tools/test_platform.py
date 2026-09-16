"""Host-side transfer/startup regression tests; no Docker daemon required."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

# Avoid colliding with Python's standard-library platform module.
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ib_platform_cli', HERE / 'ib.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class PlatformTests(unittest.TestCase):
    def test_offline_start_never_builds_or_pulls(self):
        values = {'DEPLOY_MODE': 'local', 'AUTOQUIZ_MODEL': 'test', 'AUTOQUIZ_WHISPER': 'medium'}
        with patch.object(cli, 'docker_ready'), patch.object(cli, 'configure', return_value=values), \
             patch.object(cli, 'source_revision', return_value='same'), patch.object(cli, 'image_revision', return_value='same'), \
             patch.object(cli, 'has_image', return_value=True), patch.object(cli, 'models_ready') as models, \
             patch.object(cli, 'compose') as compose, patch.object(cli, 'run') as run:
            cli.start(offline=True)
        run.assert_not_called()
        models.assert_not_called()
        for call in compose.call_args_list:
            if call.args[0] == '--profile':
                self.assertEqual(call.args, ('--profile', 'ai', 'stop', 'autoquiz', 'ollama'))
                continue
            self.assertEqual(call.args[0], 'up')
            self.assertIn('--no-build', call.args)
            self.assertIn('never', call.args)

    def test_stale_offline_images_fail_before_starting_services(self):
        with patch.object(cli, 'docker_ready'), patch.object(cli, 'configure', return_value={'DEPLOY_MODE': 'local'}), \
             patch.object(cli, 'source_revision', return_value='new'), patch.object(cli, 'image_revision', return_value='old'), \
             patch.object(cli, 'has_image', return_value=True), patch.object(cli, 'compose') as compose:
            with self.assertRaisesRegex(RuntimeError, 'выпуску'):
                cli.start(offline=True)
        compose.assert_not_called()

    def test_public_export_rejects_modified_source_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text('public')
            manifest = {'files': {'README.md': cli.digest(root / 'README.md')}}
            (root / 'source-manifest.json').write_text(json.dumps(manifest))
            with patch.object(cli, 'ROOT', root):
                cli.copy_public_source(root / 'out')
                self.assertEqual((root / 'out/README.md').read_text(), 'public')
                (root / 'README.md').write_text('changed')
                with self.assertRaises(RuntimeError): cli.copy_public_source(root / 'bad')
                manifest['files'] = {'../private.txt': 'unknown'}
                (root / 'source-manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(RuntimeError): cli.copy_public_source(root / 'bad')

    def test_configure_preserves_existing_deployment_mode_and_keys(self):
        with patch.object(cli, 'read_env', return_value={'DEPLOY_MODE': 'server', 'DJANGO_SECRET_KEY': 'keep'}), patch.object(cli, 'run') as run:
            cli.configure()
        args = run.call_args.args[0]
        self.assertNotIn('--mode', args)
        self.assertNotIn('--import-keys', args)
        self.assertEqual(args[-2:], ['--ai', 'off'])

    def test_account_import_mounts_only_hash_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'accounts.json'; path.write_text('{}')
            with patch.object(cli, 'compose') as compose:
                cli.import_accounts(path)
            args = compose.call_args.args
            self.assertIn(str(path) + ':/private/accounts.json:ro', args)
            self.assertNotIn('credentials.csv', ' '.join(args))


if __name__ == '__main__':
    unittest.main()
