import unittest
from unittest.mock import patch
import json
from ollama_backend import OllamaBackend
from translator import QuickMTBackend, suggest


class OllamaTests(unittest.TestCase):
    def backend(self):
        with patch('ollama_backend.local_models', return_value=['local-test']):
            return OllamaBackend('local-test')

    def response(self, value, ambiguous=False):
        return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(
            {'translation': value, 'ambiguous': ambiguous})}}

    def test_preserves_suffix_and_caches(self):
        backend = self.backend()
        with patch('ollama_backend.request', return_value=self.response('Travel Report 0628')) as call:
            self.assertEqual(suggest('شرح سفر 0628.docx', 'file', backend)[0], 'Travel Report 0628.docx')
            self.assertEqual(suggest('شرح سفر 0628.docx', 'file', backend)[0], 'Travel Report 0628.docx')
            self.assertEqual(call.call_count, 1)

    def test_altered_id_rejected(self):
        with patch('ollama_backend.request', return_value=self.response('Travel Report 628')):
            name = 'شرح سفر 0628.docx'
            self.assertEqual(suggest(name, 'file', self.backend())[0], name)

    def test_english_code_rejected(self):
        with patch('ollama_backend.request', return_value=self.response('Project Abc')):
            name = 'پروژه ABC.pdf'
            self.assertEqual(suggest(name, 'file', self.backend())[0], name)

    def test_ambiguous_translation_marked(self):
        with patch('ollama_backend.request', return_value=self.response('Reza Khani', True)):
            result, status = suggest('رضاخانی', 'folder', self.backend())
            self.assertEqual(result, 'Reza Khani')
            self.assertIn('مبهم', status)

    def test_invalid_or_partial_output_is_unchanged(self):
        for output in ['CON', '../Other', 'پاسخ', '']:
            with self.subTest(output=output), patch('ollama_backend.request', return_value=self.response(output)):
                self.assertEqual(suggest('نمونه', 'folder', self.backend())[0], 'نمونه')

    def test_truncated_json_rejected(self):
        with patch('ollama_backend.request', return_value={'done': True, 'message': {'content': '{'}}):
            self.assertIsNone(self.backend().translate('نمونه'))

    def test_missing_model_errors(self):
        with patch('ollama_backend.local_models', return_value=[]), self.assertRaises(RuntimeError):
            OllamaBackend('missing')

    def test_domain_glossary_takes_priority(self):
        backend = self.backend()
        with patch('ollama_backend.request') as call:
            result, status = suggest('جانمایی مسکن.pdf', 'file', backend)
            self.assertEqual(result, 'Housing Layout.pdf')
            self.assertIn('واژه‌نامه', status)
            call.assert_not_called()


class ProtectedQuickMTTests(unittest.TestCase):
    def test_codes_numbers_passthrough(self):
        backend = object.__new__(QuickMTBackend)
        backend.glossary = type('Empty', (), {'translate': lambda self, t: None})()
        backend.phrase = lambda t: 'Report'
        self.assertEqual(backend.translate('گزارش ABC-12_3 ۰۶۲۸'), 'Report ABC-12_3 ۰۶۲۸')


if __name__ == '__main__':
    unittest.main(verbosity=2)
