"""The original SSP.exe and ssp.py side by side, in consoles nobody sees.

    py tests/compare_console.py [--save SESSIONS.json] SSP_FOLDER [SCENARIO ...]
    py tests/compare_console.py --exe exo/SSP.exe --fixes SSP_FOLDER [SCENARIO ...]

The second form compares the fixed SSP.exe (exo/build_fix.py) with ssp.py's fixes.

SSP_FOLDER is an SSP installation (SSP.exe, RES).  Windows only.  Each scenario (scenarios.py)
copies the installation's small files (and the DATA files the mods replace) to two scratch
folders, runs SSP.exe in one and ssp.py --no-fixes (bugs and all) in the other in a pseudo
console each, types the same
keys into both, and compares the screen after every key, the console titles, whether the
program ended, and the files left behind (names, contents, read-only attribute, archive
timestamps).  --save also writes the original's sessions for compare_posix.py.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from conpty import Window  # noqa: E402
from scenarios import SCENARIOS, make_copy, remove, tree  # noqa: E402

PORT = os.path.join(HERE, '..', 'ssp.py')


def session(cmdline, cwd, keys):
    """(screen before each key and at the end, console titles, exit code)"""
    w = Window('ssp', cmdline, cwd=cwd)
    screens = []
    try:
        w.settle(quiet=1.0, timeout=20)
        for k in keys:
            screens.append(w.screen())
            if w.exited():
                break
            w.type(k)
            w.settle(quiet=0.8, timeout=20)
        screens.append(w.screen())
        try:
            code = w.wait_exit(5)
        except AssertionError:
            code = 'still running'
        return screens, w.titles(), code
    finally:
        w.close()


def original(exe, folder, keys):
    shutil.copy2(exe, os.path.join(folder, 'SSP.exe'))
    return session('"%s"' % os.path.join(folder, 'SSP.exe'), folder, keys)


def screen_diff(sa, sb, keys):
    """the first screen that differs, side by side"""
    for i, (a, b) in enumerate(zip(sa, sb)):
        if a != b:
            out = ['screen %d (after %r):' % (i, keys[i - 1] if i else None)]
            n = max(len(a), len(b))
            for la, lb in zip(a + [''] * (n - len(a)), b + [''] * (n - len(b))):
                out.append('   %s %-74s| %s' % ('  ' if la == lb else '!=', la[:74], lb))
            return out
    if len(sa) != len(sb):
        return ['%d screens vs %d' % (len(sa), len(sb))]
    return []


def tree_diff(fa, fb):
    return ['file %s: %s vs %s' % (k, fa.get(k), fb.get(k))
            for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)]


def main():
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument('--save', metavar='SESSIONS.json')
    ap.add_argument('--exe', help='run this SSP.exe instead of SSP_FOLDER\'s (exo/SSP.exe: the '
                                  'fixed one)')
    ap.add_argument('--fixes', action='store_true', help='run ssp.py with its fixes')
    ap.add_argument('src', metavar='SSP_FOLDER')
    ap.add_argument('only', metavar='SCENARIO', nargs='*')
    args = ap.parse_args()
    src, only, save = args.src, args.only, args.save
    exe = args.exe or os.path.join(src, 'SSP.exe')
    port_opts = '' if args.fixes else ' --no-fixes'
    sessions = {'username': os.environ.get('USERNAME', ''), 'scenarios': {}}
    tmp = tempfile.mkdtemp(prefix='sspcon-')
    bad = 0
    try:
        for name, flags_off, keys in SCENARIOS:
            if only and name not in only:
                continue
            a, b = os.path.join(tmp, 'a'), os.path.join(tmp, 'b')
            for d in (a, b):
                remove(d)
                make_copy(src, d, flags_off)
            start = time.time()
            ra = original(exe, a, keys)
            port = '"%s" "%s"%s -C "%s"' % (sys.executable, os.path.abspath(PORT), port_opts, b)
            rb = session(port, b, keys)
            diffs = screen_diff(ra[0], rb[0], keys)
            # the first title is the program's path; the dated one is often merged away by the
            # pseudo console when the next title follows within a frame
            ta = [t for t in ra[1][1:] if not re.search(r'\d:\d\d$', t)]
            tb = [t for t in rb[1][1:] if not re.search(r'\d:\d\d$', t)]
            if ta != tb:
                diffs.append('titles: %r vs %r' % (ta, tb))
            if ra[2] != rb[2]:
                diffs.append('exit: %r vs %r' % (ra[2], rb[2]))
            files = tree(a, start)
            diffs += tree_diff(files, tree(b, start))
            sessions['scenarios'][name] = {'screens': ra[0], 'exit': ra[2], 'files': files}
            print('%-4s %-16s %d keys, exit %r' % ('ok' if not diffs else 'FAIL', name, len(keys),
                                                  ra[2]))
            for line in diffs:
                print('     ' + line)
            sys.stdout.flush()
            bad += bool(diffs)
    finally:
        remove(os.path.join(tmp, 'a'))
        remove(os.path.join(tmp, 'b'))
        shutil.rmtree(tmp, ignore_errors=True)
    if save:
        with open(save, 'w') as f:
            json.dump(sessions, f, indent=0)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
