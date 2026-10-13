"""GitHub library manager, using only Python's standard library and Git."""
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlparse


CONFIG = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'KiLibSync' / 'repositories.json'


def repository_name(url):
    url = url.strip().rstrip('/')
    if url.startswith('git@github.com:'):
        path = url[len('git@github.com:'):]
    else:
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'github.com' or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('GitHubのHTTPS URLまたはSSH URLを入力してください。')
        path = parsed.path.strip('/')
    parts = path.split('/')
    if len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', p) for p in parts):
        raise ValueError('URLは https://github.com/所有者/リポジトリ の形式で入力してください。')
    name = parts[1].removesuffix('.git')
    if name in ('', '.', '..') or parts[0] in ('.', '..'):
        raise ValueError('リポジトリ名が不正です。')
    return name


def git(*args, cwd=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    result = subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True,
                            encoding='utf-8', errors='replace', timeout=300,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Gitコマンドに失敗しました。')
    return result.stdout.strip()


def check_repository(path, url):
    root = Path(git('rev-parse', '--show-toplevel', cwd=path)).resolve()
    if root != Path(path).resolve():
        raise ValueError('指定したフォルダーはリポジトリのルートではありません。')
    remote = git('remote', 'get-url', 'origin', cwd=path)
    def identity(value):
        repository_name(value)
        return value.strip().rstrip('/').removesuffix('.git').replace('git@github.com:', 'https://github.com/').lower()
    if identity(remote) != identity(url):
        raise ValueError('既存リポジトリのorigin URLが入力したURLと一致しません。')


def save_repositories(rows, destination=CONFIG):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)


class App:
    def __init__(self, root):
        self.root = root
        self.rows = []
        self.events = queue.Queue()
        self.busy = False
        root.title('KiLibSync — GitHubライブラリ管理')
        root.geometry('1000x600')
        root.minsize(720, 420)
        root.protocol('WM_DELETE_WINDOW', self.close)
        try:
            if CONFIG.exists():
                self.rows = json.loads(CONFIG.read_text(encoding='utf-8'))
                if not isinstance(self.rows, list) or any(
                    not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in ('name', 'url', 'path', 'last_pull'))
                    for row in self.rows
                ):
                    raise ValueError('保存データの形式が不正です。')
        except Exception as exc:
            messagebox.showerror('設定の読み込みエラー', f'{CONFIG}\n\n{exc}\n\nデータを保護するため終了します。')
            root.destroy()
            return
        toolbar = ttk.Frame(root, padding=12)
        toolbar.pack(fill='x')
        self.buttons = []
        for label, action in [('ライブラリを追加', self.add), ('選択した登録を編集', self.edit), ('選択した登録を削除', self.remove)]:
            button = ttk.Button(toolbar, text=label, command=action)
            button.pack(side='left', padx=(0, 8))
            self.buttons.append(button)
        frame = ttk.Frame(root, padding=(12, 0))
        frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(frame, columns=('name', 'path', 'date'), show='headings', selectmode='extended')
        for column, label, width in [('name', 'リポジトリ名', 180), ('path', 'ローカルリポジトリのパス', 500), ('date', '最後にプルした日時', 220)]:
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=100)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.table.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        update_bar = ttk.Frame(root, padding=(12, 8, 12, 0))
        update_bar.pack(fill='x')
        update_button = ttk.Button(update_bar, text='すべて更新', command=self.pull_all)
        update_button.pack(side='left')
        self.buttons.append(update_button)
        self.status = tk.StringVar(value='ライブラリを追加して更新を開始してください。')
        ttk.Label(root, textvariable=self.status, padding=12).pack(fill='x')
        self.log = tk.Text(root, height=7, state='disabled', wrap='word')
        self.log.pack(fill='x', padx=12, pady=(0, 12))
        self.refresh()
        root.after(100, self.poll)

    def refresh(self):
        self.table.delete(*self.table.get_children())
        for index, row in enumerate(self.rows):
            self.table.insert('', 'end', iid=str(index), values=(row['name'], row['path'], row['last_pull'] or '未実行'))

    def write_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def run(self, work):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state='disabled')
        def worker():
            try:
                work()
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                self.events.put(('done', None))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log':
                    self.write_log(value)
                    self.status.set(value.split('\n')[0])
                elif kind == 'rows':
                    self.rows = value
                    self.refresh()
                elif kind == 'error':
                    self.write_log(value)
                    messagebox.showerror('処理エラー', value)
                elif kind == 'done':
                    self.busy = False
                    for button in self.buttons:
                        button.configure(state='normal')
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def add(self):
        self.repository_dialog()

    def edit(self):
        if self.busy:
            return
        selected = self.table.selection()
        if len(selected) != 1:
            messagebox.showinfo('登録の編集', '編集するライブラリを1件選択してください。')
            return
        self.repository_dialog(int(selected[0]))

    def repository_dialog(self, index=None):
        if self.busy:
            return
        editing = index is not None
        original = self.rows[index] if editing else None
        dialog = tk.Toplevel(self.root)
        dialog.title('登録を編集' if editing else 'ライブラリを追加')
        dialog.transient(self.root)
        dialog.grab_set()
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill='both', expand=True)
        url = tk.StringVar(value=original['url'] if editing else '')
        path = tk.StringVar(value=original['path'] if editing else '')
        ttk.Label(body, text='GitHubリポジトリURL').grid(row=0, column=0, sticky='w')
        entry = ttk.Entry(body, textvariable=url, width=65)
        entry.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 12))
        ttk.Label(body, text='ローカルリポジトリのパス（クローン先のフォルダー）').grid(row=2, column=0, sticky='w')
        ttk.Entry(body, textvariable=path, width=55).grid(row=3, column=0, sticky='ew', pady=4)
        def browse():
            parent = filedialog.askdirectory(parent=dialog, title='既存リポジトリのフォルダーを選択' if editing else 'ライブラリの保存先となる親フォルダーを選択')
            if parent:
                if editing:
                    path.set(parent)
                    return
                try:
                    path.set(str(Path(parent) / repository_name(url.get())))
                except ValueError:
                    path.set(parent)
        ttk.Button(body, text='参照…', command=browse).grid(row=3, column=1, padx=(8, 0))
        help_text = ('名前はURLから自動取得します。変更先にはURLと一致する既存リポジトリを指定してください。\n'
                     'ファイルの移動やoriginの変更は行いません。URLまたはパスの変更時は最終プル日時をリセットします。'
                     if editing else '既存リポジトリも登録できます。新規クローン先は空のフォルダーを指定してください。')
        ttk.Label(body, text=help_text).grid(row=4, column=0, columnspan=2, pady=8)
        def submit():
            try:
                remote = url.get().strip().rstrip('/')
                name = repository_name(remote)
                if not path.get().strip():
                    raise ValueError('ローカルパスを指定してください。')
                target = Path(path.get().strip()).expanduser().resolve()
                if any(Path(row['path']).resolve() == target for row_index, row in enumerate(self.rows) if row_index != index):
                    raise ValueError('このローカルパスは登録済みです。')
                if target.exists() and not target.is_dir():
                    raise ValueError('ローカルパスにはフォルダーを指定してください。')
                if editing and not target.is_dir():
                    raise ValueError('編集時は既存のローカルリポジトリを指定してください。')
            except Exception as exc:
                messagebox.showerror('入力エラー', str(exc), parent=dialog)
                return
            dialog.destroy()
            rows = [dict(row) for row in self.rows]
            def work():
                self.events.put(('log', f'{name}: 登録の保存中…'))
                if editing or (target.exists() and any(target.iterdir())):
                    check_repository(target, remote)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    git('clone', '--', remote, str(target))
                updated = dict(name=name, url=remote, path=str(target), last_pull='')
                if editing:
                    if remote == original['url'] and target == Path(original['path']).resolve():
                        updated['last_pull'] = original['last_pull']
                    rows[index] = updated
                else:
                    rows.append(updated)
                save_repositories(rows)
                self.events.put(('rows', rows))
                self.events.put(('log', f'{name}: 登録を保存しました。'))
            self.run(work)
        ttk.Button(body, text='保存' if editing else '追加', command=submit).grid(row=5, column=1, sticky='e')
        entry.focus_set()

    def remove(self):
        selected = set(self.table.selection())
        if not selected:
            messagebox.showinfo('登録の削除', '一覧から削除するライブラリを選択してください。')
            return
        if not messagebox.askyesno('登録の削除', f'{len(selected)}件の登録を削除しますか？\nローカルのファイルは残ります。'):
            return
        rows = [row for index, row in enumerate(self.rows) if str(index) not in selected]
        try:
            save_repositories(rows)
        except Exception as exc:
            messagebox.showerror('保存エラー', str(exc))
            return
        self.rows = rows
        self.refresh()

    def pull_all(self):
        if not self.rows:
            messagebox.showinfo('一括更新', 'ライブラリを追加してください。')
            return
        rows = [dict(row) for row in self.rows]
        def work():
            success = 0
            for row in rows:
                self.events.put(('log', f"{row['name']}: プル中…"))
                try:
                    check_repository(row['path'], row['url'])
                    output = git('pull', '--ff-only', cwd=row['path'])
                except Exception as exc:
                    self.events.put(('log', f"{row['name']}: 失敗\n{exc}"))
                    continue
                row['last_pull'] = datetime.now().astimezone().isoformat(sep=' ', timespec='seconds')
                save_repositories(rows)
                success += 1
                self.events.put(('rows', [dict(item) for item in rows]))
                self.events.put(('log', f"{row['name']}: 成功\n{output}"))
            self.events.put(('log', f'一括更新完了: 成功 {success}件 / 失敗 {len(rows) - success}件'))
        self.run(work)

    def close(self):
        if self.busy:
            messagebox.showinfo('処理中', '処理が完了してから終了してください。')
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    if not shutil.which('git'):
        messagebox.showerror('Gitが必要です', 'Gitをインストールし、PATHに追加してください。')
        root.destroy()
        return
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
