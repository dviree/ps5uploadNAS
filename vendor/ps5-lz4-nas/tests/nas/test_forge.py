"""FORGE_TEST_BINARY=/path/to/ps5-dump-forge python -m unittest discover -s tests/nas -v"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_community import app


class ForgeOptionsTests(unittest.TestCase):
    def test_lz4_report_does_not_skip_new_zstd_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library, output, zstd, reports, logs = (root / name for name in
                                                     ('library', 'output', 'zstd', 'reports', 'logs'))
            for path in (library, output, zstd, reports, logs):
                path.mkdir()
            source = library / 'PPSA01234'
            source.mkdir()
            (output / 'PPSA01234-lz4').mkdir()
            (reports / 'PPSA01234.json').write_text(json.dumps({'pack_codec': 'lz4', 'saved_percent': 20}))
            with patch.object(app, 'LIBRARY', library):
                entry = app.Entry(source, 'folder')
            opts = SimpleNamespace(codec='zstd', level=5, runtime='ng', no_restore_test=True,
                                   require_vhash=False, force_image=False, no_profile=False,
                                   all=True, resume=False, targets=[])
            with patch.multiple(app, LIBRARY=library, OUTPUT=output, ZSTD_OUTPUT=zstd,
                                REPORTS=reports, LOGS=logs, STATE=root,
                                QUEUE_PATH=root / 'queue.json', LOCK_PATH=root / 'lock'), \
                 patch.object(app, 'ensure_dirs'), patch.object(app, 'scan_library', return_value=[entry]), \
                 patch.object(app.subprocess, 'Popen', return_value=SimpleNamespace(pid=42)), \
                 contextlib.redirect_stdout(io.StringIO()):
                app.cmd_start(opts)
                self.assertEqual(app.read_json(app.QUEUE_PATH)['remaining'], ['PPSA01234'])
                with patch.object(app, 'Job') as job:
                    self.assertEqual(app.process_one(entry, opts), 'ok')
                    job.assert_called_once()
                    self.assertEqual(entry.output, zstd / 'PPSA01234-zstd')

    def test_commands_pin_codec_runtime_and_full_verification(self):
        for codec in ('zstd',):
            cmd = app.forge_command(Path('/src'), Path('/out'), codec, 5)
            self.assertIn('--full-verify', cmd)
            self.assertNotIn('--delete-source', cmd)
            self.assertIn('--' + codec + '-pack', cmd)
            if codec == 'lz4':
                self.assertEqual(cmd[cmd.index('--lz4-runtime') + 1], 'ng')
        for codec, level in [('zip', 5), ('zstd', 23), ('lz4', 5), ('lz4', 13)]:
            with self.assertRaises(app.JobError):
                app.forge_command(Path('/src'), Path('/out'), codec, level)

    def test_request_queue_retains_options(self):
        req = app.queued_request({'action': 'start', 'game': 'test', 'codec': 'zstd', 'runtime': 'ng', 'level': 5, 'unexpected': 'x'})
        self.assertNotIn('unexpected', req)
        with patch.object(app.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as run:
            self.assertTrue(app.run_request(req)['ok'])
            cmd = run.call_args.args[0]
            for key, value in [('codec','zstd'), ('runtime','ng'), ('level','5')]:
                self.assertEqual(cmd[cmd.index('--' + key) + 1], value)
        with patch.object(app.subprocess, 'run') as run:
            self.assertFalse(app.run_request({**req, 'runtime': 'legacy'})['ok'])
            self.assertFalse(app.run_request({**req, 'level': 23})['ok'])
            run.assert_not_called()

    def test_a_request_without_options_is_zstd_ng(self):
        with patch.object(app.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')) as run:
            app.run_request(app.queued_request({'action': 'start', 'game': 'test'}))
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[cmd.index('--runtime') + 1], 'ng')
            self.assertEqual(cmd[cmd.index('--codec') + 1], 'zstd')
            self.assertEqual(cmd[cmd.index('--level') + 1], '5')
        with self.assertRaisesRegex(app.JobError, 'no longer packed'):
            app.Job(None, 9, True, False, 'lz4', 'legacy')


@unittest.skipUnless(os.environ.get('FORGE_TEST_BINARY'), 'set FORGE_TEST_BINARY for real binary round trips')
class ForgeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        paths = dict(LIBRARY=self.root/'library', OUTPUT=self.root/'output', STATE=self.root/'state',
                     WORK=self.root/'work', LOGS=self.root/'logs', REPORTS=self.root/'reports')
        for path in paths.values(): path.mkdir()
        self.context = contextlib.ExitStack()
        self.addCleanup(self.context.close)
        for key, value in paths.items(): self.context.enter_context(patch.object(app, key, value))
        self.context.enter_context(patch.object(app, 'FORGE', os.environ['FORGE_TEST_BINARY']))
        self.context.enter_context(patch.object(app, 'HOST_OUTPUT', str(app.OUTPUT)))
        self.context.enter_context(patch.object(app, 'HOST_LIBRARY', str(app.LIBRARY)))
        self.context.enter_context(patch.object(app, 'DB_PATH', app.STATE/'test.db'))
        self.src = app.LIBRARY/'PPSA01234'
        (self.src/'data').mkdir(parents=True)
        (self.src/'sce_sys').mkdir()
        (self.src/'eboot.bin').write_bytes(b'\x7fELF fixture libSceAmpr.sprx')
        (self.src/'sce_sys/param.json').write_text(json.dumps({'titleId':'PPSA01234','contentId':'UP0000-PPSA01234_00-TESTTESTTESTTEST'}))
        (self.src/'data/text.bin').write_bytes(b'compressible data '*50000)
        (self.src/'data/noise.bin').write_bytes(os.urandom(300000))
        (self.src/'data/empty').touch()
        self.before = {p.relative_to(self.src):p.read_bytes() for p in self.src.rglob('*') if p.is_file()}

    def pack(self, codec):
        job = app.Job(app.Entry(self.src, 'folder'), 5, True, False, codec, 'ng')
        with contextlib.redirect_stdout(io.StringIO()): report = job.run()
        return job.e.output, report

    def test_zstd_is_made_from_the_original_even_with_an_lz4_copy(self):
        # Always folder/exFAT -> LZ4 or folder/exFAT -> Zstd, never LZ4 -> Zstd.
        lz4_out, _ = self.pack('lz4')
        zstd_out, report = self.pack('zstd')
        self.assertNotEqual(lz4_out, zstd_out)
        self.assertTrue(lz4_out.is_dir() and zstd_out.is_dir())
        self.assertEqual(report['source'], str(self.src))
        self.assertEqual(report['verification']['extraction'], 'none (folder used as is)')
        self.assertEqual({p.relative_to(self.src): p.read_bytes() for p in self.src.rglob('*') if p.is_file()}, self.before)

    def test_zstd_roundtrip_discovery_and_corruption(self):
        out, report = self.pack('zstd')
        self.assertEqual(report['pack_codec'], 'zstd')
        self.assertIn('byte-identical', report['verification']['restore_test'])
        self.assertEqual(app.runtime_sha(out), app.NG_SHA256)
        self.assertIsNone(app.lz4_format_problem(out))
        self.assertEqual(app.Entry(self.src, 'folder').output, out)
        self.assertEqual(app.output_for('PPSA01234'), out)
        self.assertEqual(app.lz4_folder_info(out)['pack_codec'], 'zstd')
        self.assertEqual(self.before, {p.relative_to(self.src):p.read_bytes() for p in self.src.rglob('*') if p.is_file()})
        volume = next(out.glob('ampr_zstd-*.pak'))
        with volume.open('r+b') as f: f.seek(64); f.write(b'BROKEN FRAME')
        result = app.subprocess.run(app.forge_command(out, self.root/'bad', 'zstd', 5, True), capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_zstd_destination(self):
        target = self.root/'zstd-output'; target.mkdir()
        with patch.object(app,'ZSTD_OUTPUT',target), patch.object(app,'HOST_ZSTD_OUTPUT','/volume1/games/ps5zstd'):
            out, report = self.pack('zstd')
            self.assertEqual(out.parent,target)
            self.assertEqual(report['output'],'/volume1/games/ps5zstd/PPSA01234-zstd')
            self.assertEqual(app.output_for('PPSA01234'),out)
            self.assertEqual(app.lz4_image_path(out).parent,target)
            lz4=app.Entry(app.LIBRARY/'other','folder')
            self.assertEqual(lz4.output.parent,app.OUTPUT)

    def test_lz4_ng_repair_never_downgrades(self):
        out, report = self.pack('lz4')
        self.assertEqual(report['pack_runtime'], 'ng')
        self.assertTrue(app.runtime_ok(out, app.NG_SHA256))
        self.assertFalse(app.runtime_ok(out, app.RUNTIME_SHA256))
        # Repair must restore NG even when its original file is missing.
        runtime = out/app.RUNTIME_REL
        ng = self.root/'ng.sprx'; ng.write_bytes(runtime.read_bytes()); runtime.unlink()
        with patch.object(app, 'NG_FILE', ng), \
             patch.object(app, 'ensure_dirs'), patch.object(app.subprocess, 'run') as tool, contextlib.redirect_stdout(io.StringIO()):
            app.cmd_apr(SimpleNamespace(fix=True, full=True))
            tool.assert_not_called()  # repair copies the runtime; no packer is run
        self.assertEqual(app.runtime_sha(out), app.NG_SHA256)

    def test_resume_rejects_different_mode(self):
        entry = app.Entry(self.src, 'folder')
        entry.work.mkdir()
        app.write_json(entry.work/'state.json', {'done':['source'], 'codec':'lz4', 'runtime':'legacy', 'level':9})
        with self.assertRaisesRegex(app.JobError, 'different compression settings'):
            app.Job(entry, 5, True, False, 'zstd', 'ng').run()

    def test_boot_check_keeps_packed_index(self):
        out, _ = self.pack('zstd')
        before = (out/'ampr_emu.index').read_bytes()
        app.boot_files(out, repair=True)
        self.assertEqual((out/'ampr_emu.index').read_bytes(), before)
        self.assertFalse((out/'ampr_emu.index.stale').exists())

class RuntimeIndexTests(unittest.TestCase):
    def test_replacement_updates_runtime_record_only(self):
        import struct
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / app.RUNTIME_REL
            runtime.parent.mkdir()
            runtime.write_bytes(b'updated runtime')
            paths = [b'/app0/data/packed.bin', ('/app0/' + app.RUNTIME_REL).encode()]
            strings = b'\0'.join(paths) + b'\0'
            header = bytearray(48)
            header[:8] = b'AMPRIDX3'
            struct.pack_into('<IIQQ', header, 8, 3, 24, 2, len(strings))
            first = struct.pack('<IIQq', 0, len(paths[0]), 12345, 1)
            second = struct.pack('<IIQq', len(paths[0])+1, len(paths[1]), 1, 1)
            before = bytes(header) + first + second + strings + b'HASH-TABLE'
            index = root / 'ampr_emu.index'
            index.write_bytes(before)
            app.update_runtime_index(root, runtime)
            after = index.read_bytes()
            self.assertEqual(before[:80], after[:80])
            self.assertEqual(before[96:], after[96:])
            self.assertEqual(struct.unpack_from('<Q', after, 80)[0], len(b'updated runtime'))

    def test_invalid_index_fails_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / 'ampr_emu.index'
            index.write_bytes(b'invalid')
            with self.assertRaises(app.JobError):
                app.update_runtime_index(root, root / app.RUNTIME_REL)
            self.assertEqual(index.read_bytes(), b'invalid')
