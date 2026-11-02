"""Conservative Windows rename transactions with durable write-ahead recovery."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import ctypes
import hashlib
import json
import os
import re
import stat
import unicodedata
import uuid

VERSION = 1
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$', re.I)
OFFICE_LOCK_EXTENSIONS = {'.doc', '.docx', '.docm', '.xls', '.xlsx', '.xlsm', '.ppt', '.pptx', '.pptm'}


def utc():
    return datetime.now(timezone.utc).isoformat()


def key(name):
    # Conservative Unicode-equivalent collision checking without changing original spelling.
    return unicodedata.normalize('NFC', name).casefold()


def units(text):
    return len(str(text).encode('utf-16-le')) // 2


def valid_name(name):
    if not isinstance(name, str) or not name or name in ('.', '..'):
        raise ValueError('نام خالی یا نامعتبر')
    if any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name) or name.endswith((' ', '.')):
        raise ValueError(f'کاراکتر غیرمجاز یا فاصله/نقطه انتهایی: {name}')
    if RESERVED.match(name.split('.')[0].rstrip(' ')):
        raise ValueError(f'نام رزروشده ویندوز: {name}')
    if units(name) > 255:
        raise ValueError(f'نام بیش از ۲۵۵ واحد UTF-16: {name}')


def is_reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def is_office_lock(name):
    """Office owner/lock files are ephemeral and must never be renamed."""
    path = Path(name)
    return path.name.startswith('~$') and path.suffix.casefold() in OFFICE_LOCK_EXTENSIONS


def identity(path):
    s = os.lstat(path)
    return [s.st_dev, s.st_ino]


def same(path, expected):
    try:
        return identity(path) == expected and not is_reparse(os.lstat(path))
    except FileNotFoundError:
        return False


def guarded(root, path):
    root, path = Path(root), Path(path)
    try:
        rel = path.relative_to(root)
    except ValueError:
        raise ValueError('مسیر خارج از روت است.')
    if any(x in ('.', '..') for x in rel.parts):
        raise ValueError('مسیر غیرمجاز در manifest')
    current = root
    for part in ('', *rel.parts):
        if part:
            current = current / part
        if os.path.lexists(current) and is_reparse(os.lstat(current)):
            raise ValueError(f'پیوند یا reparse point مجاز نیست: {current}')
    return path


def scan(root, report=lambda *a: None):
    root = Path(os.path.abspath(os.path.expanduser(str(root))))
    if not root.is_dir():
        raise ValueError('روت باید یک پوشه موجود محلی یا UNC باشد.')
    # Reject reparse ancestors too, not just the selected root.
    for p in (root, *root.parents):
        if is_reparse(os.lstat(p)):
            raise ValueError(f'روت/والد یک پیوند است: {p}')
    rows = []
    stack = [root]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and is_office_lock(entry.name):
                    continue
                # Windows DirEntry.stat may return st_ino=0; lstat queries the actual file ID.
                s = os.lstat(entry.path)
                path = Path(entry.path)
                link = is_reparse(s)
                kind = 'reparse' if link else ('folder' if stat.S_ISDIR(s.st_mode) else 'file')
                rows.append(dict(path=str(path), parent=str(path.parent), original_name=path.name,
                                 type=kind, depth=len(path.relative_to(root).parts),
                                 relative=str(path.relative_to(root)), proposed_name=path.name,
                                 created_ns=s.st_ctime_ns, modified_ns=s.st_mtime_ns,
                                 accessed_ns=s.st_atime_ns, size=s.st_size,
                                 identity=[s.st_dev, s.st_ino], status='پیوند: بدون پیمایش' if link else ''))
                if not link and kind == 'folder':
                    stack.append(path)
                report(len(rows), str(path))
    return dict(version=VERSION, root=str(root), root_identity=identity(root), scanned_at=utc(), rows=rows)


def validate(snapshot):
    root = Path(snapshot['root'])
    rows = snapshot['rows']
    by_path = {r['path']: r for r in rows}
    names = {}
    original_names = {}
    changed = []
    for r in rows:
        original_names.setdefault(r['parent'], set()).add(key(r['original_name']))
    for r in rows:
        new = r['proposed_name']
        if new != r['original_name']:
            if r['type'] == 'reparse':
                raise ValueError('تغییر نام پیوندها در این نسخه مجاز نیست.')
            valid_name(new)
            if not r['identity'][1] or not snapshot['root_identity'][1]:
                raise ValueError('فایل‌سیستم شناسه پایدار ارائه نمی‌کند؛ تغییر نام امن ممکن نیست.')
            if key(new) == key(r['original_name']):
                raise ValueError('تغییر فقط حروف بزرگ/کوچک یا شکل Unicode پشتیبانی نمی‌شود.')
            changed.append(r)
        bucket = names.setdefault(r['parent'], {})
        if key(new) in bucket:
            other = bucket[key(new)]
            raise ValueError(
                f'دو آیتم در یک پوشه نام پیشنهادی یکسان دارند:\n'
                f'{other["original_name"]}  →  {other["proposed_name"]}\n'
                f'{r["original_name"]}  →  {new}\n\n'
                f'پوشه: {r["parent"]}\n'
                f'یکی از نام‌های پیشنهادی را با دوبارکلیک ویرایش کنید.'
            )
        bucket[key(new)] = r
    for r in changed:
        destination = Path(r['parent']) / r['proposed_name']
        # Do not perform swaps or rename chains, even if another row plans to vacate a name.
        if key(r['proposed_name']) in original_names[r['parent']]:
            raise ValueError(f'نام مقصد هم‌اکنون اشغال است: {destination}')
        if os.path.lexists(destination):
            raise ValueError(f'مقصد موجود است: {destination}')
    for r in rows:
        parts = []
        current = Path(r['path'])
        while current != root:
            entry = by_path.get(str(current))
            if entry is None:
                raise ValueError('ساختار inventory نامعتبر است.')
            parts.append(entry['proposed_name'])
            current = current.parent
        final = root.joinpath(*reversed(parts))
        # Budget every ancestor expansion independently, also covering intermediate and undo paths.
        expansion = 0
        current = Path(r['path'])
        while current != root:
            entry = by_path[str(current)]
            expansion += max(0, units(entry['proposed_name']) - units(entry['original_name']))
            current = current.parent
        if changed and units(r['path']) + expansion >= 260:
            raise ValueError(f'مسیر از حد محافظه‌کارانه ۲۵۹ واحد طولانی‌تر است: {final}')
    return sorted(changed, key=lambda r: (-r['depth'], r['path']))


def check_snapshot(snapshot):
    now = scan(snapshot['root'])
    if now['root_identity'] != snapshot['root_identity']:
        raise ValueError('روت تعویض شده است؛ دوباره Scan کنید.')
    before = {r['path']: r for r in snapshot['rows']}
    after = {r['path']: r for r in now['rows']}
    if before.keys() != after.keys():
        raise ValueError('ساختار پوشه پس از Scan تغییر کرده؛ دوباره Scan کنید.')
    for path, old in before.items():
        new = after[path]
        if old['identity'] != new['identity'] or old['type'] != new['type'] or (
                old['type'] == 'file' and (old['size'], old['modified_ns']) != (new['size'], new['modified_ns'])):
            raise ValueError(f'آیتم پس از Scan تغییر کرده: {path}')


def save_json(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def backup(snapshot, destination):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    parent = Path(destination).absolute()
    root = Path(snapshot['root']).resolve()
    if parent.resolve() == root or root in parent.resolve().parents:
        raise ValueError('پشتیبان باید بیرون روت انتخاب‌شده ذخیره شود.')
    planned = validate(snapshot)
    if len(snapshot['rows']) > 1048575:
        raise ValueError('تعداد ردیف‌ها از ظرفیت یک صفحه Excel بیشتر است؛ روت کوچک‌تر انتخاب کنید.')
    folder = parent / ('rename-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    ops = [dict(source=r['path'], target=str(Path(r['parent']) / r['proposed_name']),
                identity=r['identity'], state='planned') for r in planned]
    data = dict(snapshot, operations=ops, state='backed_up', backup_at=utc())
    # Immutable original inventory plus a separate mutable transaction journal.
    save_json(folder / 'inventory.json', snapshot)
    book = Workbook()
    ws = book.active
    ws.title = 'Inventory'
    columns = ['path', 'parent', 'original_name', 'type', 'depth', 'created_ns', 'modified_ns',
               'accessed_ns', 'size', 'proposed_name', 'relative', 'identity', 'status']
    ws.append(columns)
    for row_index, row in enumerate(snapshot['rows'], start=2):
        ws.append([str(row.get(k, '')) for k in columns])
        # Force strings so untrusted file names never become spreadsheet formulas.
        for column_index in range(1, len(columns) + 1):
            ws.cell(row_index, column_index).data_type = 's'
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='245C78')
    for column in ('A', 'B', 'K'):
        ws.column_dimensions[column].width = 65
    for column in ('C', 'J', 'M'):
        ws.column_dimensions[column].width = 30
    meta = book.create_sheet('Recovery')
    meta.append(['manifest', 'manifest.json'])
    meta.append(['root', snapshot['root']])
    meta.append(['note', 'Restore uses the adjacent manifest.json; keep the entire backup folder.'])
    for row in meta:
        for cell in row:
            cell.data_type = 's'
    book.save(folder / 'inventory.xlsx')
    # Manifest only becomes available after both inventory files have been successfully saved.
    save_json(folder / 'manifest.json', data)
    return folder / 'manifest.json'


@contextmanager
def root_lock(root):
    if os.name != 'nt':
        raise RuntimeError('عملیات تغییر نام فقط در Windows اجرا می‌شود.')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    token = hashlib.sha256(os.path.normcase(str(root)).encode('utf-8')).hexdigest()
    handle = kernel.CreateMutexW(None, False, 'Local\\SafeEnglishRenamer-' + token)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError('عملیات دیگری روی همین روت در این نشست Windows فعال است.')
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def load_manifest(path):
    path = Path(path).absolute()
    if path.suffix.lower() == '.xlsx':
        path = path.with_name('manifest.json')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != VERSION or not isinstance(data.get('operations'), list):
        raise ValueError('manifest ناشناخته یا ناقص است.')
    root = Path(data['root'])
    if not root.is_absolute() or not same(root, data['root_identity']):
        raise ValueError('روت اصلی موجود نیست یا هویت آن تغییر کرده است.')
    rows = {r['path']: r for r in data['rows']}
    seen = set()
    for op in data['operations']:
        src, dst = Path(op['source']), Path(op['target'])
        if src.parent != dst.parent or src == root or src == dst:
            raise ValueError('عملیات خارج از ساختار مجاز است.')
        if not src.is_relative_to(root) or '..' in src.parts or '..' in dst.parts:
            raise ValueError('مسیر غیرمجاز در manifest')
        valid_name(dst.name)
        row = rows.get(str(src))
        if row is None or row['identity'] != op['identity'] or row['proposed_name'] != dst.name:
            raise ValueError('عملیات با inventory تطابق ندارد.')
        if str(src) in seen or op['state'] not in ('planned', 'pending', 'done', 'undo_pending', 'undone'):
            raise ValueError('وضعیت یا عملیات تکراری نامعتبر است.')
        seen.add(str(src))
    expected = sorted(data['operations'], key=lambda o: (-len(Path(o['source']).relative_to(root).parts), o['source']))
    if expected != data['operations']:
        raise ValueError('ترتیب عملیات manifest نامعتبر است.')
    return path, data


def move(root, source, target, expected):
    guarded(root, source)
    guarded(root, target)
    if not same(source, expected):
        raise ValueError(f'هویت فایل تغییر کرده یا منبع در دسترس نیست: {source}')
    # Reject case-insensitive/Unicode collisions introduced after preview.
    if any(key(p.name) == key(Path(target).name) for p in Path(target).parent.iterdir()):
        raise FileExistsError(f'مقصد موجود است: {target}')
    # On Windows os.rename fails when target exists; never uses os.replace for user files.
    os.rename(source, target)


def undo_data(path, data, report):
    for index, op in enumerate(reversed(data['operations'])):
        state = op['state']
        if state in ('planned', 'undone'):
            continue
        source, target = op['source'], op['target']
        guarded(data['root'], source)
        guarded(data['root'], target)
        at_source = same(source, op['identity'])
        at_target = same(target, op['identity'])
        if at_source and not os.path.lexists(target):
            # Crash before forward rename, or after inverse rename but before journal commit.
            op['state'] = 'undone'
            save_json(path, data)
            continue
        if not at_target or os.path.lexists(source) or at_source:
            raise ValueError(f'بازگردانی مبهم یا مقصد اشغال است؛ هیچ فایلی بازنویسی نشد: {source}')
        op['state'] = 'undo_pending'
        save_json(path, data)
        move(data['root'], target, source, op['identity'])
        op['state'] = 'undone'
        save_json(path, data)
        report(index + 1, source)
    data['state'] = 'restored'
    save_json(path, data)


def restore(path, report=lambda *a: None):
    path, data = load_manifest(path)
    with root_lock(data['root']):
        path, data = load_manifest(path)
        try:
            undo_data(path, data, report)
        except Exception as exc:
            data['state'] = 'restore_blocked'
            data['last_error'] = str(exc)
            save_json(path, data)
            raise
    return str(path)


def execute(path, report=lambda *a: None):
    path, data = load_manifest(path)
    with root_lock(data['root']):
        path, data = load_manifest(path)
        if data['state'] != 'backed_up':
            raise ValueError('این تراکنش قبلاً اجرا شده؛ Restore یا Scan جدید انجام دهید.')
        check_snapshot(data)
        validate(data)
        data['state'] = 'running'
        save_json(path, data)
        try:
            for index, op in enumerate(data['operations']):
                op['state'] = 'pending'
                save_json(path, data)
                move(data['root'], op['source'], op['target'], op['identity'])
                op['state'] = 'done'
                save_json(path, data)
                report(index + 1, op['target'])
            data['state'] = 'completed'
            save_json(path, data)
        except Exception as exc:
            data['last_error'] = str(exc)
            try:
                undo_data(path, data, report)
            except Exception as recovery:
                data['state'] = 'restore_blocked'
                data['recovery_error'] = str(recovery)
                try:
                    save_json(path, data)
                except OSError:
                    pass
                raise RuntimeError(f'عملیات متوقف شد: {exc}\nبازگردانی کامل نشد: {recovery}\nRestore از {path}') from exc
            raise RuntimeError(f'عملیات ناموفق بود و نام‌های تغییرکرده بازگردانده شدند: {exc}\n{path}') from exc
    return str(path)
