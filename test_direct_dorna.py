import json
import unittest
from unittest.mock import patch

import direct_dorna_backend as direct


class FakeEngine:
    def __init__(self, translation='Travel Report 0628', ambiguous=False):
        self.translation = translation
        self.ambiguous = ambiguous

    def create_chat_completion(self, **kwargs):
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
            'translation': self.translation, 'ambiguous': self.ambiguous,
        })}}]}


class DirectDornaTests(unittest.TestCase):
    def backend(self, translation='Travel Report 0628', ambiguous=False):
        with patch('direct_dorna_backend._load_model', return_value=FakeEngine(translation, ambiguous)):
            backend = direct.DirectDornaBackend('گردشگری')
        backend.glossary = type('Empty', (), {'translate': lambda self, text: None})()
        return backend

    def test_valid_translation(self):
        self.assertEqual(self.backend().translate('گزارش سفر 0628'), 'Travel Report 0628')

    def test_changed_number_is_rejected(self):
        backend = self.backend('Travel Report 628')
        self.assertIsNone(backend.translate('گزارش سفر 0628'))
        self.assertIn('عدد', backend.last_issue)

    def test_persian_output_is_rejected(self):
        backend = self.backend('گزارش Travel')
        self.assertIsNone(backend.translate('گزارش سفر'))


if __name__ == '__main__':
    unittest.main()
