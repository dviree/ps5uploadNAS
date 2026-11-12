#!/usr/bin/env python3
"""Add the existing Zstd folder to a NAS docker-run updater; never restart it here."""
import argparse
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile


def add_mount(text, folder, container='ps5upload'):
    if any(c in folder for c in ',\n\r\0'):
        raise ValueError('the folder path cannot contain commas or control characters')
    commands = []
    for match in re.finditer(r'(?m)^[ \t]*(?:sudo[ \t]+)?docker[ \t]+run\b', text):
        end = text.find('\n', match.end())
        end = len(text) if end < 0 else end + 1
        while end < len(text) and text[:end].rstrip('\r\n').endswith('\\'):
            following = text.find('\n', end)
            end = len(text) if following < 0 else following + 1
        tokens = shlex.split(text[match.start():end].replace('\\\n', ' '))
        named = any(t == '--name=' + container or
                    (t == '--name' and i + 1 < len(tokens) and tokens[i + 1] == container)
                    for i, t in enumerate(tokens))
        if named:
            commands.append((match.end(), tokens))
    if len(commands) != 1:
        raise ValueError('expected exactly one docker run with --name ' + container)
    insertion, tokens = commands[0]
    for i, token in enumerate(tokens):
        value = None
        if token in ('-v', '--volume', '--mount') and i + 1 < len(tokens):
            value = tokens[i + 1]
        elif token.startswith(('--volume=', '--mount=')):
            value = token.split('=', 1)[1]
        elif token.startswith('-v') and len(token) > 2:
            value = token[2:]
        if value is None:
            continue
        if token.startswith('--mount'):
            fields = dict(p.split('=', 1) for p in value.split(',') if '=' in p)
            target = fields.get('target', fields.get('dst', fields.get('destination')))
            source = fields.get('source', fields.get('src'))
        else:
            parts = value.split(':')
            source, target = (parts[0], parts[1]) if len(parts) > 1 else (None, None)
        if target and target.rstrip('/') == '/zstd':
            if source != folder:
                raise ValueError('/zstd already uses another host folder; leaving it unchanged')
            return text
    flag = ' --mount ' + shlex.quote('type=bind,source=' + folder + ',target=/zstd')
    return text[:insertion] + flag + text[insertion:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('updater', type=Path)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_dir():
        parser.error('the existing Zstd folder must be a directory')
    before = args.updater.read_text()
    try:
        after = add_mount(before, str(folder))
    except ValueError as error:
        parser.error(str(error))
    if before == after:
        print('The updater already mounts this folder at /zstd.')
        return
    backup = args.updater.with_name(args.updater.name + '.before-zstd')
    if not backup.exists():
        shutil.copy2(args.updater, backup)
    stat = args.updater.stat()
    with tempfile.NamedTemporaryFile(mode='w', dir=args.updater.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(after)
    try:
        temporary.chmod(stat.st_mode)
        if os.geteuid() == 0:
            os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, args.updater)
    finally:
        temporary.unlink(missing_ok=True)
    print('Added /zstd. Run your usual NAS updater after the image build completes.')


if __name__ == '__main__':
    main()
