"""Real Windows filesystem tests. Only creates files in temporary directories."""
import ctypes
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from openpyxl import load_workbook
import engine
from translator import GlossaryBackend, suggest


@unittest.skipUnless(os.name == 'nt', 'Windows rename semantics required')
class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='renamer-test-')
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        self.root.mkdir()
        self.backups = self.base / 'backups'

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self):
        folder = self.root / 'اسناد' / 'پروژه'
        folder.mkdir(parents=True)
        (folder / 'گزارش.txt').write_bytes(b'Original content\x00\xff')
        (self.root / '=1+1.txt').write_text('formula-like name')
        snapshot = engine.scan(self.root)
        for r in snapshot['rows']:
            r['proposed_name'], r['status'] = suggest(r['original_name'], r['type'], GlossaryBackend())
        return snapshot

    def plan(self):
        return engine.backup(self.fixture(), self.backups)

    def test_roundtrip_and_excel(self):
        path = self.plan()
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual([Path(o['source']).name for o in data['operations']], ['گزارش.txt', 'پروژه', 'اسناد'])
        book = load_workbook(path.with_name('inventory.xlsx'))
        ws = book['Inventory']
        self.assertEqual(ws.max_row, 5)
        self.assertTrue(all(c.data_type != 'f' for row in ws for c in row))
        book.close()
        engine.execute(path)
        self.assertEqual((self.root / 'Documents' / 'Project' / 'Report.txt').read_bytes(), b'Original content\x00\xff')
        engine.restore(path.with_name('inventory.xlsx'))
        self.assertEqual((self.root / 'اسناد' / 'پروژه' / 'گزارش.txt').read_bytes(), b'Original content\x00\xff')
        engine.restore(path)  # idempotent

    def test_collisions_and_reserved(self):
        (self.root / 'گزارش.txt').touch()
        (self.root / 'REPORT.TXT').touch()
        snapshot = engine.scan(self.root)
        next(r for r in snapshot['rows'] if r['original_name'] == 'گزارش.txt')['proposed_name'] = 'Report.txt'
        with self.assertRaises(ValueError):
            engine.validate(snapshot)
        for name in ['CON.txt', 'LPT¹.txt', 'COM9', 'a.', 'a ', '..', 'bad/name', 'a:b', 'x' * 256, 'a\x01']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                engine.valid_name(name)

    def test_office_lock_files_are_ignored(self):
        (self.root / 'لیست کارها.xlsx').write_bytes(b'workbook')
        (self.root / '~$لیست کارها.xlsx').write_bytes(b'office-lock')
        snapshot = engine.scan(self.root)
        names = {row['original_name'] for row in snapshot['rows']}
        self.assertIn('لیست کارها.xlsx', names)
        self.assertNotIn('~$لیست کارها.xlsx', names)

    def test_duplicate_proposals_and_swap(self):
        for name in ['a', 'b']:
            (self.root / name).touch()
        snapshot = engine.scan(self.root)
        for row in snapshot['rows']:
            row['proposed_name'] = 'Same'
        with self.assertRaises(ValueError):
            engine.validate(snapshot)
        for row in snapshot['rows']:
            row['proposed_name'] = 'b' if row['original_name'] == 'a' else 'a'
        with self.assertRaises(ValueError):
            engine.validate(snapshot)

    def test_drift_prevents_changes(self):
        path = self.plan()
        (self.root / 'added.txt').touch()
        with self.assertRaises(ValueError):
            engine.execute(path)
        self.assertTrue((self.root / 'اسناد' / 'پروژه' / 'گزارش.txt').exists())

    def test_modified_content_prevents_changes(self):
        path = self.plan()
        (self.root / 'اسناد' / 'پروژه' / 'گزارش.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            engine.execute(path)

    def test_backup_inside_root_rejected(self):
        snapshot = self.fixture()
        with self.assertRaises(ValueError):
            engine.backup(snapshot, self.root / 'backup')

    def test_automatic_rollback_on_permission_error(self):
        path = self.plan()
        original = engine.move
        count = [0]
        def fail_second(*args):
            count[0] += 1
            if count[0] == 2:
                raise PermissionError('simulated server ACL denial')
            return original(*args)
        with patch('engine.move', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'بازگردانده شدند'):
                engine.execute(path)
        self.assertTrue((self.root / 'اسناد' / 'پروژه' / 'گزارش.txt').exists())

    def test_crash_after_each_forward_rename(self):
        for stop in range(1, 4):
            with self.subTest(crash_after_operation=stop):
                self.root = self.base / f'root{stop}'
                self.root.mkdir()
                path = self.plan()
                _, data = engine.load_manifest(path)
                data['state'] = 'running'
                for op in data['operations'][:stop]:
                    op['state'] = 'pending'
                    engine.save_json(path, data)
                    engine.move(data['root'], op['source'], op['target'], op['identity'])
                    # Disk deliberately omits the commit for the latest rename.
                    op['state'] = 'done'
                engine.restore(path)
                self.assertTrue((self.root / 'اسناد' / 'پروژه' / 'گزارش.txt').exists())

    def test_crash_before_forward_rename(self):
        path = self.plan()
        _, data = engine.load_manifest(path)
        data['operations'][0]['state'] = 'pending'
        engine.save_json(path, data)
        engine.restore(path)

    def test_crash_after_inverse_rename(self):
        path = self.plan()
        engine.execute(path)
        _, data = engine.load_manifest(path)
        op = data['operations'][-1]
        op['state'] = 'undo_pending'
        engine.save_json(path, data)
        engine.move(data['root'], op['target'], op['source'], op['identity'])
        engine.restore(path)
        self.assertTrue((self.root / 'اسناد' / 'پروژه' / 'گزارش.txt').exists())

    def test_restore_conflict_never_overwrites(self):
        path = self.plan()
        engine.execute(path)
        (self.root / 'اسناد').mkdir()
        marker = self.root / 'اسناد' / 'do-not-touch.txt'
        marker.write_text('KEEP')
        with self.assertRaises(ValueError):
            engine.restore(path)
        self.assertEqual(marker.read_text(), 'KEEP')
        self.assertTrue((self.root / 'Documents' / 'Project' / 'Report.txt').exists())

    def test_replaced_file_is_not_restored(self):
        (self.root / 'گزارش.txt').write_text('original')
        snapshot = engine.scan(self.root)
        snapshot['rows'][0]['proposed_name'] = 'Report.txt'
        path = engine.backup(snapshot, self.backups)
        engine.execute(path)
        os.rename(self.root / 'Report.txt', self.root / 'elsewhere.txt')
        (self.root / 'Report.txt').write_text('replacement')
        with self.assertRaises(ValueError):
            engine.restore(path)
        self.assertEqual((self.root / 'Report.txt').read_text(), 'replacement')

    def test_real_windows_locked_file(self):
        from ctypes import wintypes
        path = self.plan()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(self.root / 'اسناد' / 'پروژه' / 'گزارش.txt'), 0x80000000, 1, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with self.assertRaises(RuntimeError):
                engine.execute(path)
        finally:
            kernel.CloseHandle(handle)
        self.assertTrue((self.root / 'اسناد' / 'پروژه' / 'گزارش.txt').exists())

    def test_long_final_path_rejected(self):
        snapshot = self.fixture()
        row = next(r for r in snapshot['rows'] if r['original_name'] == 'اسناد')
        row['proposed_name'] = 'X' * 240
        with self.assertRaises(ValueError):
            engine.validate(snapshot)

    def test_root_lock(self):
        with engine.root_lock(self.root):
            with self.assertRaises(RuntimeError):
                with engine.root_lock(self.root):
                    pass

    def test_malicious_manifest_path_rejected(self):
        path = self.plan()
        data = json.loads(path.read_text(encoding='utf-8'))
        data['operations'][0]['target'] = str(self.base / 'outside.txt')
        engine.save_json(path, data)
        with self.assertRaises(ValueError):
            engine.restore(path)

    def test_translation_preserves_suffix_and_unknown(self):
        self.assertEqual(suggest('گزارش.tar.gz', 'file', GlossaryBackend())[0], 'Report.tar.gz')
        self.assertEqual(suggest('نام ناشناخته.txt', 'file', GlossaryBackend())[0], 'نام ناشناخته.txt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
