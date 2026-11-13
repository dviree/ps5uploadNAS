"""quer3q's game reports (issues on quer3q/ampr-emu-ng, its game-report form)."""
import unittest
from urllib.parse import parse_qs, urlparse
from test_community import app


def issue(number, title, packs, result, game='Example Game, PPSA01234, 01.002', version='v0.3.4', **kw):
    body = (f"### Game, title ID and game version\n\n{game}\n\n### ampr-emu-ng version\n\n{version}\n\n"
            f"### Build\n\nrelease (libSceAmpr.sprx)\n\n### Packs\n\n{packs}\n\n### Result\n\n{result}\n\n"
            "### Setup\n\nFirmware: 10.01\n\n### What happened\n\ntext\n\n### Logs\n\n_No response_")
    return {'number': number, 'title': title, 'body': body, 'state': 'open',
            'labels': [{'name': 'test report'}], 'created_at': f'2026-11-0{number}T00:00:00Z', **kw}


class NgReportTests(unittest.TestCase):
    def test_counts_per_title_and_pack_kind(self):
        data = app.ng_reports_aggregate([
            issue(1, '[PPSA01234] Example Game: works', 'zstd', 'Works (played past the first level load)'),
            issue(2, '[PPSA01234] Example Game: crash', 'zstd', 'Crashes later'),
            issue(3, 'Example Game hangs', 'lz4', 'Hangs (loading screen or black screen)'),
            issue(4, '[PPSA01234] slow', 'plain (no packs)', 'Runs, but slow or stutters'),
            issue(5, 'no title id here', 'zstd', 'Works (played past the first level load)', game='Some game'),
            issue(6, '[PPSA01234] a pull request', 'zstd', 'Works', pull_request={'url': 'x'}),
            {**issue(7, '[PPSA01234] dup', 'zstd', 'Works'), 'labels': [{'name': 'duplicate'}]},
        ])
        g = data['games']['PPSA01234']
        self.assertEqual((g['zstd']['works'], g['zstd']['crash'], g['zstd']['reports']), (1, 1, 2))
        self.assertEqual(g['lz4']['hang'], 1)
        self.assertEqual(g['plain']['issues'], 1)
        self.assertEqual(g['name'], 'Example Game')
        self.assertEqual((g['latest']['issue'], g['latest']['packs'], g['latest']['version']), (4, 'plain', 'v0.3.4'))
        self.assertEqual(list(data['games']), ['PPSA01234'])

    def test_report_link_fills_the_form(self):
        url = app.ng_report_url('PPSA01234', 'Example Game', 'nostart', 'zstd', '01.002', '10.01')
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.assertTrue(url.startswith('https://github.com/quer3q/ampr-emu-ng/issues/new?'))
        self.assertEqual(q['template'], 'game-report.yml')
        self.assertEqual(q['packs'], 'zstd')
        self.assertEqual(q['game'], 'Example Game, PPSA01234, 01.002')
        self.assertTrue(q['result'].startswith('Fails at launch'))
        self.assertIn('Firmware: 10.01', q['setup'])
        self.assertIn('ps5-dump-forge', q['setup'])
        self.assertTrue(q['title'].startswith('[PPSA01234] Example Game: Fails at launch'))
        # every answer offered is one of the form's own options
        form = [full for _s, _k, full in app.NG_RESULTS]
        self.assertTrue(all(v in form for v in app.NG_FORM_RESULT.values()))



class NgListReportTests(unittest.TestCase):
    def test_a_report_listing_several_games_counts_for_each(self):
        table = ("### Compatibility Table\n\n| Game ID | Title | Status (ZSTD) |\n|---|---|---|\n"
                 "| **PPSA00001** | Example One | ok |\n| **PPSA00002** | Example Two | ok |\n")
        one = issue(1, 'List of games tested', 'zstd', 'Works (played past the first level load)', game='List of games')
        one['body'] += "\n\n" + table
        one['labels'].append({'name': 'works'})
        two = issue(2, '[PPSA00003] Example Three', 'zstd', '', game='Example Three')
        two['labels'].append({'name': 'works'})
        games = app.ng_reports_aggregate([one, two])['games']
        self.assertEqual(sorted(games), ['PPSA00001', 'PPSA00002', 'PPSA00003'])
        self.assertEqual((games['PPSA00002']['name'], games['PPSA00002']['zstd']['works']), ('Example Two', 1))
        self.assertEqual(games['PPSA00003']['zstd']['works'], 1)  # no Result answer: the "works" label counts


class NgSubmitTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'reports').mkdir()
        self.p = [patch.object(app, k, v) for k, v in {'STATE': root, 'REPORTS': root / 'reports',
                  'GITHUB_TOKEN_PATH': root / 'github-token', 'NG_SUBMITTED': root / 'ng-submitted.json'}.items()]
        for x in self.p: x.start(); self.addCleanup(x.stop)
        app.write_json(root / 'reports' / 'G1.json', {'title_id': 'PPSA00001', 'title_name': 'Example One',
                                                       'pack_codec': 'zstd', 'pack_runtime': 'ng', 'codec': 'Zstd level 5'})
        self.fields = {'result': 'Hangs (loading screen or black screen)', 'firmware': '13.40', 'loader': 'SMP',
                       'install': 'folder', 'storage': 'USB exFAT', 'what': 'Black screen after the logo, every time.'}

    def test_issue_body_matches_the_form_and_parses_back(self):
        issue = app.ng_report_issue('G1', self.fields)
        self.assertEqual(issue['title'], '[PPSA00001] Example One: Hangs')
        f = app.ng_form_sections(issue['body'])
        self.assertEqual(f['packs'], 'zstd')
        self.assertTrue(f['result'].startswith('Hangs'))
        self.assertIn('Firmware: 13.40', f['setup'])
        g = app.ng_reports_aggregate([{'number': 9, 'title': issue['title'], 'body': issue['body'], 'state': 'open',
                                       'labels': [{'name': 'test report'}], 'created_at': '2026-11-13T00:00:00Z'}])
        self.assertEqual(g['games']['PPSA00001']['zstd']['hang'], 1)
        with self.assertRaises(ValueError):
            app.ng_report_issue('G1', {**self.fields, 'what': 'short'})
        with self.assertRaises(ValueError):
            app.ng_report_issue('missing', self.fields)

    def test_submit_needs_a_token_posts_once_and_keeps_it_private(self):
        import io, json
        from unittest.mock import patch
        with self.assertRaisesRegex(ValueError, 'token'):
            app.ng_report_submit('G1', self.fields)
        with self.assertRaises(ValueError):
            app.set_github_token('not-a-token')
        self.assertEqual(app.set_github_token('ghp_' + 'a' * 36), {'github_token': 'set'})
        self.assertEqual(oct(app.GITHUB_TOKEN_PATH.stat().st_mode & 0o777), '0o600')
        sent = []
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): pass
        def fake(req, timeout=0):
            sent.append(req)
            return R(json.dumps({'number': 77, 'html_url': 'https://github.com/quer3q/ampr-emu-ng/issues/77'}).encode())
        with patch('urllib.request.urlopen', fake):
            res = app.ng_report_submit('G1', self.fields)
            self.assertEqual(res['number'], 77)
            self.assertEqual(sent[0].full_url, 'https://api.github.com/repos/quer3q/ampr-emu-ng/issues')
            self.assertEqual(sent[0].get_header('Authorization'), 'Bearer ghp_' + 'a' * 36)
            self.assertEqual(json.loads(sent[0].data)['labels'], ['test report'])
            with self.assertRaisesRegex(ValueError, 'already sent'):
                app.ng_report_submit('G1', self.fields)
        self.assertEqual(app.set_github_token(''), {'github_token': ''})
        self.assertFalse(app.GITHUB_TOKEN_PATH.exists())


if __name__ == '__main__':
    unittest.main()
