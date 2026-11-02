"""Windows GUI. All filesystem/translation work runs outside Tk's UI thread."""
import copy
import os
from pathlib import Path
import queue
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import customtkinter as ctk
import engine
from translator import ArgosBackend, GlossaryBackend, QuickMTBackend, PERSIAN, suggest
from ollama_backend import OllamaBackend, local_models, DEFAULT_MODEL
from direct_dorna_backend import DirectDornaBackend
from ui_text import display as rtl, display_log


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(rtl('آریانا فایل سرور | ترجمه مستقیم Dorna 2 | توسعه‌دهنده: Mohamad Milad'))
        self.geometry('1240x850')
        self.minsize(1024, 720)
        self.configure(fg_color='#080D18')
        self.snapshot = None
        self.busy = False
        self.events = queue.Queue()
        self.manifest = None
        self.root_path = tk.StringVar()
        self.backup_path = tk.StringVar(value=str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ArianaFileServerRenamer' / 'backups'))
        self.backend = tk.StringVar(value='Dorna 2 — مستقیم GPU + CPU/RAM')
        self.ollama_model = tk.StringVar(value=DEFAULT_MODEL)
        self.domain_context = tk.StringVar()
        self.reviewed = tk.BooleanVar(value=False)
        initial_status = 'مسیر محلی یا UNC را وارد کنید؛ سپس Scan.'
        self.status = tk.StringVar(value=initial_status)
        self.status_display = tk.StringVar(value=rtl(initial_status))
        self.buttons = []
        self.ui_font = ctk.CTkFont(family='Tahoma', size=13)
        self.ui_font_bold = ctk.CTkFont(family='Tahoma', size=13, weight='bold')
        self.title_font = ctk.CTkFont(family='Tahoma', size=24, weight='bold')
        self.small_font = ctk.CTkFont(family='Tahoma', size=11)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(5, weight=1)

        hero = ctk.CTkFrame(self, height=86, corner_radius=18, fg_color='#111A2D',
                            border_width=1, border_color='#24324A')
        hero.grid(row=0, column=0, sticky='ew', padx=16, pady=(14, 8))
        hero.grid_propagate(False)
        hero.columnconfigure(1, weight=1)
        brand = ctk.CTkFrame(hero, width=58, height=58, corner_radius=16, fg_color='#2563EB')
        brand.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=14)
        brand.grid_propagate(False)
        ctk.CTkLabel(brand, text='A', font=ctk.CTkFont(family='Segoe UI', size=30, weight='bold'),
                     text_color='white').place(relx=.5, rely=.5, anchor='center')
        ctk.CTkLabel(hero, text=rtl('آریانا فایل سرور'), font=self.title_font,
                     text_color='#F8FAFC', anchor='e').grid(row=0, column=1, sticky='se', pady=(13, 0))
        ctk.CTkLabel(hero, text=rtl('سامان‌دهی امن فایل‌سرورها؛ تبدیل گروهی نام‌های فارسی به انگلیسی با هوش مصنوعی محلی'),
                     font=self.small_font, text_color='#94A3B8', anchor='e').grid(row=1, column=1, sticky='ne', pady=(0, 13))
        ctk.CTkLabel(hero, text='DORNA 2  •  LOCAL AI', font=ctk.CTkFont(family='Segoe UI', size=11, weight='bold'),
                     text_color='#93C5FD', fg_color='#172554', corner_radius=12,
                     padx=14, pady=7).grid(row=0, column=2, rowspan=2, padx=16)

        header = ctk.CTkFrame(self, corner_radius=16, fg_color='#111827', border_width=1, border_color='#1F2A40')
        header.grid(row=1, column=0, sticky='ew', padx=16, pady=8)
        header.columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text=rtl('Root / مسیر روت'), font=self.ui_font, anchor='e').grid(row=0, column=0, padx=8, sticky='e')
        self.root_entry = ctk.CTkEntry(header, textvariable=self.root_path, font=self.ui_font)
        self.root_entry.grid(row=0, column=1, sticky='ew', padx=8, pady=8)
        self.button(header, 'انتخاب پوشه', self.pick_root).grid(row=0, column=2, padx=8)
        ctk.CTkLabel(header, text=rtl('محل پشتیبان'), font=self.ui_font, anchor='e').grid(row=1, column=0, padx=8, sticky='e')
        self.backup_entry = ctk.CTkEntry(header, textvariable=self.backup_path, font=self.ui_font)
        self.backup_entry.grid(row=1, column=1, sticky='ew', padx=8, pady=8)
        self.button(header, 'انتخاب پشتیبان', self.pick_backup).grid(row=1, column=2, padx=8)
        ctk.CTkLabel(header, text=rtl('مدل Ollama (اختیاری)'), font=self.ui_font, anchor='e').grid(row=2, column=0, padx=8, sticky='e')
        self.model_entry = ctk.CTkComboBox(header, variable=self.ollama_model, values=[DEFAULT_MODEL, 'qwen3.5:9b'], width=640, font=self.ui_font, dropdown_font=self.ui_font)
        self.model_entry.grid(row=2, column=1, sticky='w', padx=8, pady=5)
        self.button(header, 'مدل‌های نصب‌شده', self.refresh_models).grid(row=2, column=2, padx=8)
        ctk.CTkLabel(header, text=rtl('موضوع فایل‌ها (اختیاری)'), font=self.ui_font, anchor='e').grid(row=3, column=0, padx=8, sticky='e')
        self.context_entry = ctk.CTkEntry(header, textvariable=self.domain_context,
                                         placeholder_text=rtl('مثلاً معماری و پروژه‌های گردشگری؛ برای Dorna و Ollama'),
                                         font=self.ui_font, justify='right')
        self.context_entry.grid(row=3, column=1, columnspan=2, sticky='ew', padx=8, pady=5)
        toolbar = ctk.CTkFrame(self, corner_radius=16, fg_color='#111827', border_width=1, border_color='#1F2A40')
        toolbar.grid(row=2, column=0, sticky='ew', padx=16, pady=8)
        for i in range(5):
            toolbar.columnconfigure(i, weight=1)
        actions = [
            ('۱  پیمایش', self.scan, '#334155'), ('۲  ترجمه و پیش‌نمایش', self.preview, '#2563EB'),
            ('۳  تهیه پشتیبان', self.backup, '#7C3AED'), ('۴  اجرای تغییر نام', self.rename, '#059669'),
            ('بازگردانی', self.restore, '#B45309')]
        for i, (label, action, color) in enumerate(actions):
            self.button(toolbar, label, action, color=color, width=170).grid(row=0, column=i, sticky='ew', padx=6, pady=10)
        options = ctk.CTkFrame(self, corner_radius=16, fg_color='#111827', border_width=1, border_color='#1F2A40')
        options.grid(row=3, column=0, sticky='ew', padx=16, pady=8)
        self.menu = ctk.CTkOptionMenu(options, width=315, values=['Dorna 2 — مستقیم GPU + CPU/RAM', 'Ollama — مدل محلی', 'QuickMT — ترجمه هوشمند آفلاین', 'واژه‌نامه محلی', 'Argos — مدل آفلاین'], variable=self.backend, font=self.ui_font, dropdown_font=self.ui_font)
        self.menu.pack(side='left', padx=8, pady=8)
        self.button(options, 'نصب مدل محلی Argos', self.install_model).pack(side='left', padx=8)
        self.button(options, 'ویرایش نام انتخاب‌شده', self.edit).pack(side='left', padx=8)
        self.button(options, 'بازکردن پشتیبان‌ها', self.open_backups).pack(side='left', padx=8)
        ctk.CTkLabel(self, text=rtl('راهنما: برای اصلاح نام، روی پیشنهاد دوبار کلیک کنید. پسوند فایل همیشه حفظ می‌شود.'),
                     font=self.small_font, text_color='#94A3B8', anchor='e', justify='right').grid(row=4, column=0, padx=22, sticky='e')
        container = ttk.Frame(self)
        container.grid(row=5, column=0, sticky='nsew', padx=16, pady=8)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(container, columns=('relative', 'type', 'name', 'proposed', 'status'), show='headings', selectmode='browse')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Treeview', font=('Tahoma', 10), rowheight=27)
        style.configure('Treeview.Heading', font=('Tahoma', 10, 'bold'))
        style.configure('Treeview', background='#0F172A', fieldbackground='#0F172A', foreground='#E2E8F0',
                        borderwidth=0, relief='flat')
        style.configure('Treeview.Heading', background='#1E293B', foreground='#CBD5E1',
                        borderwidth=0, relief='flat', padding=(8, 9))
        style.map('Treeview', background=[('selected', '#1D4ED8')], foreground=[('selected', '#FFFFFF')])
        style.map('Treeview.Heading', background=[('active', '#263449')])
        for col, title, width in [('relative', 'مسیر نسبی', 320), ('type', 'نوع', 70), ('name', 'نام اصلی', 180), ('proposed', 'نام پیشنهادی', 220), ('status', 'وضعیت', 220)]:
            self.tree.heading(col, text=rtl(title))
            anchor = 'w' if col in ('relative', 'proposed') else 'e'
            self.tree.column(col, width=width, minwidth=60, anchor=anchor)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(container, orient='vertical', command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(container, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind('<Double-1>', lambda e: self.edit())
        self.check = ctk.CTkCheckBox(self, text=rtl('پیشنهادها و نام‌های بدون ترجمه را بررسی کرده‌ام؛ فقط تغییرات نمایش‌داده‌شده اجرا شوند.'),
                                    variable=self.reviewed, font=self.ui_font)
        self.check.configure(fg_color='#10B981', hover_color='#059669', border_color='#475569')
        self.check.grid(row=6, column=0, sticky='e', padx=18, pady=(4, 2))
        self.progress = ctk.CTkProgressBar(self)
        self.progress.configure(height=7, corner_radius=5, progress_color='#3B82F6', fg_color='#1E293B')
        self.progress.grid(row=7, column=0, sticky='ew', padx=18, pady=5)
        self.progress.set(0)
        ctk.CTkLabel(self, textvariable=self.status_display, font=self.ui_font, anchor='e',
                     text_color='#93C5FD', justify='right', wraplength=1160).grid(row=8, column=0, sticky='ew', padx=18)
        log_card = ctk.CTkFrame(self, corner_radius=14, fg_color='#0B1220', border_width=1, border_color='#1F2A40')
        log_card.grid(row=9, column=0, sticky='ew', padx=16, pady=8)
        log_card.columnconfigure(0, weight=1)
        ctk.CTkLabel(log_card, text=rtl('گزارش فعالیت'), font=self.small_font,
                     text_color='#64748B', anchor='e').grid(row=0, column=0, sticky='e', padx=12, pady=(5, 0))
        self.log = ctk.CTkTextbox(log_card, height=72, font=('Tahoma', 11), fg_color='transparent',
                                  border_width=0, text_color='#CBD5E1')
        self.log.grid(row=1, column=0, sticky='ew', padx=4, pady=(0, 4))
        self.log.configure(state='disabled')
        ctk.CTkLabel(self, text=rtl('توسعه‌دهنده: Mohamad Milad | GitHub: mohamadmilad1'),
                     font=self.small_font, text_color='#64748B').grid(row=10, column=0, pady=(0, 8))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def button(self, parent, text, command, color='#1D4ED8', width=140):
        button = ctk.CTkButton(parent, text=rtl(text), font=self.ui_font_bold, command=command,
                               width=width, height=38, corner_radius=10, fg_color=color,
                               hover_color=self.hover_color(color))
        self.buttons.append(button)
        return button

    @staticmethod
    def hover_color(color):
        return {
            '#334155': '#475569', '#2563EB': '#1D4ED8', '#7C3AED': '#6D28D9',
            '#059669': '#047857', '#B45309': '#92400E', '#1D4ED8': '#1E40AF'
        }.get(color, '#1E40AF')

    def pick_root(self):
        selected = filedialog.askdirectory()
        if selected:
            self.root_path.set(selected)

    def pick_backup(self):
        selected = filedialog.askdirectory()
        if selected:
            self.backup_path.set(selected)

    def open_backups(self):
        path = Path(self.backup_path.get())
        if path.is_dir():
            os.startfile(str(path))
        else:
            messagebox.showinfo('پشتیبان', 'هنوز پوشه پشتیبان ساخته نشده است.')

    def record(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', time.strftime('%H:%M:%S') + '  ' + display_log(message) + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 500:
            self.log.delete('1.0', '100.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def set_status(self, message, shape=True):
        self.status.set(message)
        self.status_display.set(rtl(message) if shape else message)

    def start(self, title, operation, done):
        if self.busy:
            return
        self.busy = True
        self.set_status(title)
        self.record(title)
        for widget in [*self.buttons, self.root_entry, self.backup_entry, self.menu, self.check, self.model_entry, self.context_entry]:
            widget.configure(state='disabled')
        self.progress.configure(mode='indeterminate')
        self.progress.start()

        def run():
            try:
                self.events.put(('done', operation(), done))
            except Exception as exc:
                self.events.put(('error', str(exc), traceback.format_exc()))
        threading.Thread(target=run, daemon=False).start()

    def reporter(self, total=None):
        last = [0.0]
        def report(count, path):
            now = time.monotonic()
            if now - last[0] > 0.15 or count == total:
                last[0] = now
                self.events.put(('progress', count, str(path), total))
        return report

    def poll(self):
        try:
            while True:
                item = self.events.get_nowait()
                if item[0] == 'progress':
                    self.set_status(f'{item[1]} | {item[2]}', shape=False)
                    if item[3]:
                        self.progress.stop()
                        self.progress.configure(mode='determinate')
                        self.progress.set(min(item[1] / item[3], 1))
                elif item[0] == 'backup_saved':
                    self.manifest = item[1]
                    self.record('پشتیبان ذخیره شد: ' + str(item[1]))
                else:
                    self.busy = False
                    self.progress.stop()
                    self.progress.configure(mode='determinate')
                    self.progress.set(1 if item[0] == 'done' else 0)
                    for widget in [*self.buttons, self.root_entry, self.backup_entry, self.menu, self.check, self.model_entry, self.context_entry]:
                        widget.configure(state='normal')
                    if item[0] == 'done':
                        self.set_status('انجام شد')
                        item[2](item[1])
                    else:
                        self.reviewed.set(False)
                        self.set_status('متوقف شد — گزارش را بررسی کنید')
                        self.record(item[1])
                        messagebox.showerror('خطا', item[1])
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def populate(self, snapshot):
        self.snapshot = snapshot
        self.reviewed.set(False)
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(snapshot['rows']):
            self.tree.insert('', 'end', iid=str(index), values=self.values(row))
        links = sum(r['type'] == 'reparse' for r in snapshot['rows'])
        self.set_status(f'{len(snapshot["rows"])} آیتم | {links} پیوند ثبت شد؛ داخل پیوندها پیمایش نمی‌شود.')
        self.record(self.status.get())
        if snapshot.get('backend_status'):
            self.record(snapshot['backend_status'])

    @staticmethod
    def values(row):
        kinds = {'file': 'فایل', 'folder': 'پوشه', 'reparse': 'پیوند'}
        return (row['relative'], rtl(kinds.get(row['type'], row['type'])),
                rtl(row['original_name']), rtl(row['proposed_name']), rtl(row['status']))

    def current(self):
        if not self.snapshot:
            messagebox.showinfo('Scan', 'ابتدا Scan کنید.')
            return None
        if os.path.normcase(os.path.abspath(self.root_path.get().strip())) != os.path.normcase(self.snapshot['root']):
            messagebox.showerror('روت تغییر کرده', 'پس از تغییر روت دوباره Scan کنید.')
            return None
        return copy.deepcopy(self.snapshot)

    def scan(self):
        root = self.root_path.get().strip()
        if not root:
            messagebox.showinfo('مسیر', 'مسیر روت را وارد کنید.')
            return
        self.snapshot = None
        self.tree.delete(*self.tree.get_children())
        self.start('در حال پیمایش؛ هر خطای دسترسی Scan را متوقف می‌کند.', lambda: engine.scan(root, self.reporter()), self.populate)

    def preview(self):
        snapshot = self.current()
        if snapshot is None:
            return
        selection = self.backend.get()
        model = self.ollama_model.get()
        context = self.domain_context.get()
        def work():
            if selection.startswith('Dorna 2'):
                backend = DirectDornaBackend(context)
            elif selection.startswith('Ollama'):
                backend = OllamaBackend(model, context)
            elif selection.startswith('QuickMT'):
                backend = QuickMTBackend()
            elif selection.startswith('Argos'):
                backend = ArgosBackend()
            else:
                backend = GlossaryBackend()
            snapshot['backend_status'] = getattr(backend, 'runtime_description', '')
            report = self.reporter(len(snapshot['rows']))
            for i, row in enumerate(snapshot['rows']):
                report(i, row['path'])
                if row['type'] != 'reparse':
                    row['proposed_name'], row['status'] = suggest(row['original_name'], row['type'], backend)
                report(i + 1, row['path'])
            return snapshot
        self.start('در حال ساخت پیشنهادهای محلی…', work, self.populate)

    def refresh_models(self):
        def done(models):
            self.model_entry.configure(values=models or ['qwen3.5:9b'])
            if models and self.ollama_model.get() not in models:
                self.ollama_model.set(models[0])
            self.record('مدل‌های محلی: ' + ', '.join(models))
            if not models:
                messagebox.showinfo('Ollama', 'مدل محلی نصب‌شده‌ای پیدا نشد.')
        self.start('بررسی مدل‌های Ollama محلی…', local_models, done)

    def edit(self):
        if self.busy or not self.snapshot or not self.tree.selection():
            return
        index = int(self.tree.selection()[0])
        row = self.snapshot['rows'][index]
        if row['type'] == 'reparse':
            messagebox.showinfo('پیوند', 'تغییر نام پیوندها در این نسخه غیرفعال است.')
            return
        name = simpledialog.askstring('ویرایش نام', 'نام کامل جدید (شامل پسوند فایل):', initialvalue=row['proposed_name'], parent=self)
        if name is not None:
            try:
                engine.valid_name(name)
            except ValueError as exc:
                messagebox.showerror('نام نامعتبر', str(exc))
                return
            row['proposed_name'] = name
            row['status'] = 'ویرایش دستی'
            self.reviewed.set(False)
            self.tree.item(str(index), values=self.values(row))

    def checked(self):
        snapshot = self.current()
        if snapshot is not None:
            try:
                engine.validate(snapshot)
            except Exception as exc:
                messagebox.showerror('پیش‌نمایش قابل اجرا نیست', str(exc))
                return None
        return snapshot

    def backup(self):
        snapshot = self.checked()
        if snapshot is None:
            return
        dest = self.backup_path.get().strip()
        def work():
            engine.check_snapshot(snapshot)
            return engine.backup(snapshot, dest)
        def done(path):
            self.manifest = path
            self.record('پشتیبان: ' + str(path))
            messagebox.showinfo('پشتیبان آماده است', str(path.parent))
        self.start('ذخیره Excel و inventory و manifest…', work, done)

    def rename(self):
        snapshot = self.checked()
        if snapshot is None:
            return
        count = sum(r['proposed_name'] != r['original_name'] for r in snapshot['rows'])
        if not count:
            messagebox.showinfo('بدون تغییر', 'نام پیشنهادی متفاوتی وجود ندارد؛ Preview یا ویرایش دستی انجام دهید.')
            return
        if not self.reviewed.get():
            messagebox.showinfo('بررسی لازم است', 'پیش‌نمایش را بررسی و گزینه تأیید بررسی را فعال کنید.')
            return
        unresolved = sum(bool(PERSIAN.search(r['original_name'])) and r['proposed_name'] == r['original_name'] for r in snapshot['rows'] if r['type'] != 'reparse')
        dest = self.backup_path.get().strip()
        if not messagebox.askyesno('تأیید تغییر نام', f'{count} نام تغییر می‌کند.\n{unresolved} نام فارسی بدون تغییر می‌ماند.\nروت: {snapshot["root"]}\nپشتیبان پیش از اجرا: {dest}\n\nاجرا شود؟', default='no'):
            return
        def work():
            engine.check_snapshot(snapshot)
            path = engine.backup(snapshot, dest)
            self.events.put(('backup_saved', path))
            engine.execute(path, self.reporter(count))
            return path
        def done(path):
            self.snapshot = None
            self.reviewed.set(False)
            self.tree.delete(*self.tree.get_children())
            self.record('تغییر نام کامل شد: ' + str(path))
            messagebox.showinfo('انجام شد', f'{count} نام تغییر کرد. برای ادامه دوباره Scan کنید.\nRestore: {path}')
        self.start('بررسی مجدد، ذخیره پشتیبان و تغییر نام…', work, done)

    def restore(self):
        selected = filedialog.askopenfilename(title='manifest.json یا inventory.xlsx را انتخاب کنید', initialdir=self.backup_path.get(), filetypes=[('Recovery', '*.json *.xlsx')])
        if not selected:
            return
        try:
            path, data = engine.load_manifest(selected)
        except Exception as exc:
            messagebox.showerror('پشتیبان نامعتبر', str(exc))
            return
        if not messagebox.askyesno('تأیید بازگردانی', f'نام‌های ثبت‌شده این تراکنش به حالت قبل بازگردند؟\nروت: {data["root"]}\nوضعیت: {data["state"]}\nعملیات: {len(data["operations"])}\n{path}', default='no'):
            return
        def done(result):
            self.snapshot = None
            self.tree.delete(*self.tree.get_children())
            self.record('بازگردانی کامل شد: ' + result)
            messagebox.showinfo('Restore', 'نام‌ها بازگردانده شدند. برای ادامه دوباره Scan کنید.')
        self.start('در حال بازگردانی…', lambda: engine.restore(path, self.reporter(len(data['operations']))), done)

    def install_model(self):
        selected = filedialog.askopenfilename(title='بسته معتبر محلی Argos (.argosmodel)', filetypes=[('Argos model', '*.argosmodel')])
        if not selected:
            return
        def work():
            try:
                from argostranslate.package import install_from_path
            except ImportError as exc:
                raise RuntimeError('ابتدا install_offline.bat را اجرا کنید.') from exc
            install_from_path(Path(selected))
            return 'مدل محلی نصب شد.'
        self.start('نصب مدل محلی…', work, lambda result: messagebox.showinfo('Argos', result))

    def close(self):
        if self.busy:
            messagebox.showinfo('عملیات فعال', 'برای حفظ امکان بازگردانی، تا پایان عملیات یا نمایش خطا صبر کنید.')
            return
        self.destroy()


if __name__ == '__main__':
    ctk.set_appearance_mode('system')
    App().mainloop()
