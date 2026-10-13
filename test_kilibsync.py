import json
import tempfile
import unittest
from pathlib import Path

from kilibsync import check_repository, git, repository_name, save_repositories


class RepositoryTests(unittest.TestCase):
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
