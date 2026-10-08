#!/usr/bin/env python3
"""Patch 2: the portable SSP configurator (ssp.py) for eXoDOS's System Shock (1994).

System Shock's launcher (eXoDOS\\!dos\\SystemSh\\exception.bat) then runs
ssp.py, the Python port of SSP.exe, as the "SSP Configurator", with Python
("py") when there is one; SSP.EXE otherwise, as before.

- util\\ssp: ssp.py, README.md, NOTES.md, LICENSE.
- exception.bat: the SSP.EXE line runs ssp.py first; exception.bat.orig keeps
  the launcher as it was.

usage: python install_port.py [--check | --revert] EXO_FOLDER

EXO_FOLDER is eXoDOS's "eXo" folder, the one with eXoDOS, emulators and util
in it. --check shows what would change, --revert undoes it. The port lives in
util\\ssp, so reinstalling the game does not remove it.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ('ssp.py', 'README.md', 'NOTES.md', 'LICENSE')
DEST = Path('util') / 'ssp'
LAUNCHER = Path('eXoDOS') / '!dos' / 'SystemSh' / 'exception.bat'
OURS = 'py ..\\..\\..\\util\\ssp\\ssp.py -C .'
BLOCK = [                              # in eXoDOS\SystemSh\SSP, like SSP.EXE
    'where py >nul 2>nul',
    'if errorlevel 1 goto sspcfg_exe',
    'if not exist ..\\..\\..\\util\\ssp\\ssp.py goto sspcfg_exe',
    OURS,
    'goto ssp',
    ':sspcfg_exe',
]


def convert(text):
    """the launcher with the port before its SSP.EXE line; None if it has none"""
    nl = '\r\n' if '\r\n' in text else '\n'
    out, found = [], False
    for line in text.split(nl):
        if line.strip().lower() == 'ssp.exe' and not found:
            found = True
            out += BLOCK
        out.append(line)
    return nl.join(out) if found else None


def source(name):
    """NAME from the release zip (beside this script) or the repository (one up)"""
    for p in (HERE / name, HERE.parent / name):
        if p.is_file():
            return p
    sys.exit(f'{name} is missing (it belongs beside install_port.py)')


class Patcher:
    def __init__(self, exo, check):
        self.exo, self.check = exo, check

    def say(self, text):
        print(('would ' if self.check else '') + text)

    def apply(self):
        for name in FILES:
            data = source(name).read_bytes()
            dest = self.exo / DEST / name
            if dest.is_file() and dest.read_bytes() == data:
                continue
            self.say(f'write {DEST / name}')
            if not self.check:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        bat = self.exo / LAUNCHER
        orig = bat.with_name('exception.bat.orig')
        if not bat.is_file():
            print(f'{LAUNCHER} is missing: launcher not changed')
            return
        text = bat.read_bytes().decode('latin-1')
        if OURS in text:
            return
        new = convert(text)
        if new is None:
            print(f'{LAUNCHER} has no SSP.EXE line: launcher not changed')
            return
        self.say(f'switch {LAUNCHER} to ssp.py (old one kept as {orig.name})')
        if not self.check:
            orig.write_bytes(text.encode('latin-1'))
            bat.write_bytes(new.encode('latin-1'))

    def revert(self):
        bat = self.exo / LAUNCHER
        orig = bat.with_name('exception.bat.orig')
        if bat.is_file() and OURS in bat.read_bytes().decode('latin-1'):
            if orig.is_file():
                self.say(f'restore {LAUNCHER}')
                if not self.check:
                    bat.write_bytes(orig.read_bytes())
                    orig.unlink()
            else:
                print(f'warning: {LAUNCHER} has no {orig.name}; left as it is')
        folder = self.exo / DEST
        for name in FILES:
            if (folder / name).is_file():
                self.say(f'delete {DEST / name}')
                if not self.check:
                    (folder / name).unlink()
        if folder.is_dir() and not self.check and not any(folder.iterdir()):
            folder.rmdir()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true', help='only show what would change')
    group.add_argument('--revert', action='store_true', help='undo the patch')
    ap.add_argument('exo', metavar='EXO_FOLDER')
    args = ap.parse_args()
    exo = Path(args.exo)
    if not (exo / 'eXoDOS').is_dir():
        sys.exit(f'{exo} is not eXoDOS\'s "eXo" folder (no eXoDOS in it)')
    p = Patcher(exo, args.check)
    p.revert() if args.revert else p.apply()
    return 0


if __name__ == '__main__':
    sys.exit(main())
