"""Exercise the GUI worker flow against temporary files without user dialogs."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from app import App


@unittest.skipUnless(os.name == 'nt', 'Windows required')
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='renamer-gui-')
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        (self.root / 'گزارش.txt').write_text('unchanged content', encoding='utf-8')
        self.app = App()
        self.app.withdraw()
        self.app.backend.set('واژه‌نامه محلی')
        self.app.root_path.set(str(self.root))
        self.app.backup_path.set(str(Path(self.temp.name) / 'backups'))
        self.messages = []
        self.patches = [patch('app.messagebox.showinfo'), patch('app.messagebox.askyesno', return_value=True),
                        patch('app.messagebox.showerror', side_effect=lambda *a, **k: self.messages.append(a))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        # Cancel callbacks before Tcl teardown to avoid cross-test theme callbacks.
        for task in self.app.tk.call('after', 'info'):
            self.app.tk.call('after', 'cancel', task)
        self.app.destroy()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def settle(self):
        deadline = time.monotonic() + 20
        while self.app.busy and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.messages, [])

    def test_scan_preview_backup_rename_restore(self):
        self.app.scan()
        self.settle()
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.app.preview()
        self.settle()
        self.assertEqual(self.app.snapshot['rows'][0]['proposed_name'], 'Report.txt')
        self.app.backup()
        self.settle()
        self.assertTrue(self.app.manifest.exists())
        self.app.reviewed.set(True)
        self.app.rename()
        self.settle()
        self.assertEqual((self.root / 'Report.txt').read_text(), 'unchanged content')
        with patch('app.filedialog.askopenfilename', return_value=str(self.app.manifest)):
            self.app.restore()
        self.settle()
        self.assertEqual((self.root / 'گزارش.txt').read_text(), 'unchanged content')

    def test_scan_changed_root_blocks_actions(self):
        self.app.scan()
        self.settle()
        self.app.root_path.set(str(Path(self.temp.name)))
        self.app.rename()
        self.assertEqual(len(self.messages), 1)
        self.assertTrue((self.root / 'گزارش.txt').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
