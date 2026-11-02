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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('آریانا فایل سرور | ترجمه مستقیم Dorna 2 | توسعه‌دهنده: Mohamad Milad')
        self.geometry('1180x780')
        self.minsize(900, 650)
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
        self.status = tk.StringVar(value='مسیر محلی یا UNC را وارد کنید؛ سپس Scan.')
        self.buttons = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky='ew', padx=12, pady=8)
        header.columnconfigure(1, weight=1)
        ctk.CTkLabel(header, text='Root / مسیر روت').grid(row=0, column=0, padx=8)
        self.root_entry = ctk.CTkEntry(header, textvariable=self.root_path)
        self.root_entry.grid(row=0, column=1, sticky='ew', padx=8, pady=8)
        self.button(header, 'انتخاب پوشه', self.pick_root).grid(row=0, column=2, padx=8)
        ctk.CTkLabel(header, text='محل پشتیبان').grid(row=1, column=0, padx=8)
        self.backup_entry = ctk.CTkEntry(header, textvariable=self.backup_path)
        self.backup_entry.grid(row=1, column=1, sticky='ew', padx=8, pady=8)
        self.button(header, 'انتخاب پشتیبان', self.pick_backup).grid(row=1, column=2, padx=8)
        ctk.CTkLabel(header, text='مدل Ollama (اختیاری)').grid(row=2, column=0, padx=8)
        self.model_entry = ctk.CTkComboBox(header, variable=self.ollama_model, values=[DEFAULT_MODEL, 'qwen3.5:9b'], width=640)
        self.model_entry.grid(row=2, column=1, sticky='w', padx=8, pady=5)
        self.button(header, 'مدل‌های نصب‌شده', self.refresh_models).grid(row=2, column=2, padx=8)
        ctk.CTkLabel(header, text='موضوع فایل‌ها (اختیاری)').grid(row=3, column=0, padx=8)
        self.context_entry = ctk.CTkEntry(header, textvariable=self.domain_context,
                                         placeholder_text='مثلاً معماری و پروژه‌های گردشگری؛ برای Dorna و Ollama')
        self.context_entry.grid(row=3, column=1, columnspan=2, sticky='ew', padx=8, pady=5)
        toolbar = ctk.CTkFrame(self)
        toolbar.grid(row=1, column=0, sticky='ew', padx=12)
        for i, (label, action) in enumerate([
            ('Scan / پیمایش', self.scan), ('Preview / ترجمه', self.preview),
            ('Backup / پشتیبان', self.backup), ('Rename / اجرا', self.rename),
            ('Restore / بازگردانی', self.restore)]):
            self.button(toolbar, label, action).grid(row=0, column=i, padx=5, pady=8)
        options = ctk.CTkFrame(self)
        options.grid(row=2, column=0, sticky='ew', padx=12, pady=8)
        self.menu = ctk.CTkOptionMenu(options, width=315, values=['Dorna 2 — مستقیم GPU + CPU/RAM', 'Ollama — مدل محلی', 'QuickMT — ترجمه هوشمند آفلاین', 'واژه‌نامه محلی', 'Argos — مدل آفلاین'], variable=self.backend)
        self.menu.pack(side='left', padx=8, pady=8)
        self.button(options, 'نصب مدل محلی Argos', self.install_model).pack(side='left', padx=8)
        self.button(options, 'ویرایش نام انتخاب‌شده', self.edit).pack(side='left', padx=8)
        self.button(options, 'بازکردن پشتیبان‌ها', self.open_backups).pack(side='left', padx=8)
        ctk.CTkLabel(self, text='ستون پیشنهاد با دوبارکلیک قابل ویرایش است. ترجمه خودکار نیازمند بررسی است؛ پسوند لاتین فایل حفظ می‌شود.').grid(row=3, column=0, padx=12, sticky='w')
        container = ttk.Frame(self)
        container.grid(row=4, column=0, sticky='nsew', padx=12, pady=8)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(container, columns=('relative', 'type', 'name', 'proposed', 'status'), show='headings', selectmode='browse')
        for col, title, width in [('relative', 'مسیر نسبی', 320), ('type', 'نوع', 70), ('name', 'نام اصلی', 180), ('proposed', 'نام پیشنهادی', 220), ('status', 'وضعیت', 220)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, minwidth=60)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(container, orient='vertical', command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(container, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.bind('<Double-1>', lambda e: self.edit())
        self.check = ctk.CTkCheckBox(self, text='پیشنهادها و نام‌های بدون ترجمه را بررسی کرده‌ام؛ فقط تغییرات نمایش‌داده‌شده اجرا شوند.', variable=self.reviewed)
        self.check.grid(row=5, column=0, sticky='w', padx=12, pady=5)
        self.progress = ctk.CTkProgressBar(self)
        self.progress.grid(row=6, column=0, sticky='ew', padx=12, pady=5)
        self.progress.set(0)
        ctk.CTkLabel(self, textvariable=self.status, anchor='w', wraplength=1100).grid(row=7, column=0, sticky='ew', padx=12)
        self.log = ctk.CTkTextbox(self, height=110)
        self.log.grid(row=8, column=0, sticky='ew', padx=12, pady=8)
        self.log.configure(state='disabled')
        ctk.CTkLabel(self, text='توسعه‌دهنده: Mohamad Milad | GitHub: mohamadmilad1',
                     text_color=('gray40', 'gray65')).grid(row=9, column=0, pady=(0, 6))
        ctk.CTkLabel(self, text='Developed by Mohamad Milad', text_color=('gray35', 'gray70')).grid(row=9, column=0, pady=(0, 7))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def button(self, parent, text, command):
        button = ctk.CTkButton(parent, text=text, command=command, width=140)
        self.buttons.append(button)
        return button

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
        self.log.insert('end', time.strftime('%H:%M:%S') + '  ' + message + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 500:
            self.log.delete('1.0', '100.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def start(self, title, operation, done):
        if self.busy:
            return
        self.busy = True
        self.status.set(title)
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
                    self.status.set(f'{item[1]} | {item[2]}')
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
                        self.status.set('انجام شد')
                        item[2](item[1])
                    else:
                        self.reviewed.set(False)
                        self.status.set('متوقف شد — گزارش را بررسی کنید')
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
        self.status.set(f'{len(snapshot["rows"])} آیتم | {links} پیوند ثبت شد؛ داخل پیوندها پیمایش نمی‌شود.')
        self.record(self.status.get())
        if snapshot.get('backend_status'):
            self.record(snapshot['backend_status'])
        if snapshot.get('backend_status'):
            self.record(snapshot['backend_status'])

    @staticmethod
    def values(row):
        return tuple(row[k] for k in ('relative', 'type', 'original_name', 'proposed_name', 'status'))

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
