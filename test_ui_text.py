import unittest

from ui_text import display, display_log


class PersianDisplayTests(unittest.TestCase):
    def test_english_is_unchanged(self):
        self.assertEqual(display('Dorna 2'), 'Dorna 2')

    def test_persian_is_isolated_for_tk(self):
        shown = display('انتخاب پوشه')
        self.assertEqual(shown, '\u202bانتخاب پوشه\u202c')

    def test_paths_are_not_reordered_in_log(self):
        value = r'C:\Users\Test\فارسی\file.txt'
        self.assertEqual(display_log(value), value)


if __name__ == '__main__':
    unittest.main()
