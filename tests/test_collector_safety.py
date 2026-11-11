import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collector


class CollectorSafetyTests(unittest.TestCase):
    def test_redacts_api_key_from_error_text(self):
        with patch.object(collector, 'API_KEY', 'test-secret'):
            result = collector.redact_sensitive('request failed: ?api-key=test-secret')
        self.assertEqual(result, 'request failed: ?api-key=[REDACTED]')

    def test_short_page_requires_empty_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mint_dir = root / 'mint'
            history_dir = mint_dir
            short_page = [{'signature': 'sig-2'}, {'signature': 'sig-1'}]
            with patch.object(collector, 'PAGES_PER_MINT', 1), patch.object(collector, 'PAGE_LIMIT', 3), patch.object(collector, 'request_json', return_value=short_page):
                collector.collect_history('address', 'test', mint_dir)
            checkpoint_path = history_dir / 'checkpoint.json'
            checkpoint = json.loads(checkpoint_path.read_text())
            self.assertFalse(checkpoint['completed'])
            self.assertEqual(checkpoint['completion_reason'], 'short_page_requires_empty_confirmation')
            with patch.object(collector, 'PAGES_PER_MINT', 1), patch.object(collector, 'request_json', return_value=[]):
                collector.collect_history('address', 'test', mint_dir)
            checkpoint = json.loads(checkpoint_path.read_text())
            self.assertTrue(checkpoint['completed'])
            self.assertEqual(checkpoint['completion_reason'], 'empty_page_confirmed')

    def test_repeated_cursor_is_rejected_before_page_write(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mint_dir = Path(temp_dir)
            with patch.object(collector, 'PAGES_PER_MINT', 1), patch.object(collector, 'PAGE_LIMIT', 1), patch.object(collector, 'request_json', return_value=[{'signature': 'same'}]):
                collector.collect_history('address', 'test', mint_dir)
            with patch.object(collector, 'PAGES_PER_MINT', 1), patch.object(collector, 'request_json', return_value=[{'signature': 'same'}]):
                with self.assertRaisesRegex(RuntimeError, 'cursor did not advance'):
                    collector.collect_history('address', 'test', mint_dir)
            files = list((mint_dir / 'transactions').glob('*.jsonl'))
            self.assertEqual(len(files), 1)

    def test_missing_signature_does_not_write_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mint_dir = Path(temp_dir)
            with patch.object(collector, 'PAGES_PER_MINT', 1), patch.object(collector, 'request_json', return_value=[{'type': 'SWAP'}]):
                with self.assertRaisesRegex(RuntimeError, 'no signature'):
                    collector.collect_history('address', 'test', mint_dir)
            self.assertFalse((mint_dir / 'transactions').exists())


if __name__ == '__main__':
    unittest.main()