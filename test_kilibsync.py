import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from kilibsync import App, check_repository, git, repository_name, save_repositories


class RepositoryTests(unittest.TestCase):
    def test_edit_dialog_saves_and_preserves_data_on_failure(self):
        try:
            window = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'GUIを使用できません: {exc}')
        window.withdraw()
        self.addCleanup(window.destroy)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'repositories.json'
            original = dict(name='library', url='https://github.com/example/library',
                            path=directory, last_pull='2026-10-13 12:00:00+09:00')
            save_repositories([original], destination)
            with patch('kilibsync.CONFIG', destination), patch('kilibsync.save_repositories',
                    side_effect=lambda rows: save_repositories(rows, destination)):
                app = App(window)
                # Execute work synchronously so events can be inspected deterministically.
                app.run = lambda work: work()
                def submit(remote):
                    app.table.selection_set('0')
                    app.edit()
                    dialog = next(child for child in window.winfo_children() if isinstance(child, tk.Toplevel))
                    body = dialog.winfo_children()[0]
                    entries = [child for child in body.winfo_children() if isinstance(child, ttk.Entry)]
                    self.assertEqual(entries[0].get(), app.rows[0]['url'])
                    entries[0].delete(0, 'end')
                    entries[0].insert(0, remote)
                    button = next(child for child in body.winfo_children()
                                  if isinstance(child, ttk.Button) and child.cget('text') == '保存')
                    button.invoke()
                    app.poll()
                with patch('kilibsync.check_repository') as check:
                    submit(original['url'])
                    self.assertEqual(app.rows[0]['last_pull'], original['last_pull'])
                    submit('https://github.com/example/renamed')
                    check.assert_called_with(Path(directory).resolve(), 'https://github.com/example/renamed')
                    self.assertEqual(app.rows[0]['name'], 'renamed')
                    self.assertEqual(app.rows[0]['last_pull'], '')
                    self.assertEqual(json.loads(destination.read_text(encoding='utf-8')), app.rows)
                before = destination.read_text(encoding='utf-8')
                def run_failure(work):
                    with self.assertRaises(ValueError):
                        work()
                app.run = run_failure
                with patch('kilibsync.check_repository', side_effect=ValueError('origin mismatch')):
                    submit('https://github.com/example/wrong')
                self.assertEqual(destination.read_text(encoding='utf-8'), before)
                self.assertEqual(app.rows[0]['name'], 'renamed')

    def test_github_urls(self):
        for url in ('https://github.com/example/library', 'https://github.com/example/library.git/', 'git@github.com:example/library.git'):
            self.assertEqual(repository_name(url), 'library')
        for url in ('https://example.com/a/b', 'https://github.com/a/b/tree/main', 'https://github.com/a/..', '--upload-pack=bad'):
            with self.assertRaises(ValueError):
                repository_name(url)

    def test_atomic_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'settings' / 'repositories.json'
            rows = [{'name': '日本語', 'path': directory, 'url': 'https://github.com/a/b', 'last_pull': ''}]
            save_repositories(rows, destination)
            self.assertEqual(json.loads(destination.read_text(encoding='utf-8')), rows)
            self.assertFalse(destination.with_suffix('.tmp').exists())

    def test_clone_pull_and_remote_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, clone = root / 'source', root / 'clone'
            git('init', str(source))
            git('config', 'user.name', 'KiLibSync Test', cwd=source)
            git('config', 'user.email', 'test@example.invalid', cwd=source)
            (source / 'library.txt').write_text('v1', encoding='utf-8')
            git('add', '.', cwd=source)
            git('commit', '-m', 'initial', cwd=source)
            git('clone', '--', str(source), str(clone))
            (source / 'library.txt').write_text('v2', encoding='utf-8')
            git('commit', '-am', 'update', cwd=source)
            git('pull', '--ff-only', cwd=clone)
            self.assertEqual((clone / 'library.txt').read_text(encoding='utf-8'), 'v2')
            git('remote', 'set-url', 'origin', 'git@github.com:example/library.git', cwd=clone)
            check_repository(clone, 'https://github.com/example/library')
            with self.assertRaises(ValueError):
                check_repository(clone, 'https://github.com/example/other')
            nested = clone / 'nested'
            nested.mkdir()
            with self.assertRaises(ValueError):
                check_repository(nested, 'https://github.com/example/library')


if __name__ == '__main__':
    unittest.main()
