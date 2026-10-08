#!/usr/bin/env python3
"""Patch 1: the fixed SSP.exe for eXoDOS's System Shock (1994).

SSP.exe, System Shock Portable's configurator, with its script's four bugs
fixed (see README.md): disabling mouselook no longer leaves a game that will
not start, disabling the scaled textures restores the original ones, a wrong
key in the CYB.CFG menu no longer removes its write protection, and odd
answers (" & < > | ^) are ordinary wrong answers instead of closing it.
Everything else is the original program; it still needs Windows.

- eXoDOS\\SystemSh\\SSP\\SSP.exe is replaced with the SSP.exe next to this
  script; SSP.exe.orig keeps the original.

usage: python fix_windows.py [--check | --revert] EXO_FOLDER

EXO_FOLDER is eXoDOS's "eXo" folder, the one with eXoDOS, emulators and util
in it. --check shows what would change, --revert undoes it. Only the installed
game is patched: its zip is left alone, so after a reinstall run this again.
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL_SHA1 = '836c6b4e77782d2aa21e57b80d754e46819d3a24'     # SSP 1.2's SSP.exe in eXoDOS
TARGET = Path('eXoDOS') / 'SystemSh' / 'SSP' / 'SSP.exe'


def sha1(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    group = ap.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true', help='only show what would change')
    group.add_argument('--revert', action='store_true', help='put the original SSP.exe back')
    ap.add_argument('--force', action='store_true',
                    help='replace an SSP.exe that is neither the original nor the fixed one')
    ap.add_argument('exo', metavar='EXO_FOLDER')
    args = ap.parse_args()

    exo = Path(args.exo)
    if not (exo / 'eXoDOS').is_dir():
        sys.exit(f'{exo} is not eXoDOS\'s "eXo" folder (no eXoDOS in it)')
    fixed = HERE / 'SSP.exe'
    target = exo / TARGET
    orig = target.with_name('SSP.exe.orig')
    if not target.is_file():
        print(f'System Shock is not installed ({TARGET} is missing): nothing to do')
        return 0
    now = sha1(target)
    is_fixed = now == sha1(fixed)
    would = 'would ' if args.check else ''

    if args.revert:
        if not orig.is_file():
            print(f'{TARGET} has no {orig.name}: nothing to undo')
            return 0
        if not is_fixed and not args.force:
            sys.exit(f'{TARGET} is not the fixed SSP.exe any more; left alone (--force restores '
                     f'{orig.name} anyway)')
        print(f'{would}restore {TARGET} from {orig.name}')
        if not args.check:
            shutil.copy2(orig, target)
            orig.unlink()
        return 0

    if is_fixed:
        print(f'{TARGET} is already the fixed one')
        return 0
    if now != ORIGINAL_SHA1 and not args.force:
        sys.exit(f'{TARGET} is not the SSP.exe this patch was made for (sha1 {now}); left alone '
                 f'(--force replaces it anyway)')
    print(f'{would}replace {TARGET} with the fixed one (the original kept as {orig.name})')
    if not args.check:
        if not orig.is_file():
            shutil.copy2(target, orig)
        shutil.copyfile(fixed, target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
