"""ssp.py on macOS or Linux against recorded sessions of the original SSP.exe.

    py tests/compare_console.py --save SESSIONS.json SSP_FOLDER     (Windows: records)
    python3 tests/compare_posix.py SSP_FOLDER SESSIONS.json          (macOS, Linux)

Runs every recorded scenario (scenarios.py) with ssp.py --no-fixes in a pty, typing the same
keys, and compares the screens, the exit code and the files left behind with the original's.
PAUSE's prompt is compared only as "a PAUSE prompt": cmd.exe's is localized.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenarios import SCENARIOS, make_copy, remove, tree  # noqa: E402
from screen import screen_rows  # noqa: E402

PORT = os.path.join(HERE, '..', 'ssp.py')


def normal(screen):
    return ['<PAUSE>' if re.search(r'\S \. \. \. ?$', row) else row for row in screen]


def pty_session(argv, cwd, keys, env):
    import fcntl
    import struct
    import termios
    master, slave = os.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 25, 80, 0, 0))
    p = subprocess.Popen(argv, cwd=cwd, stdin=slave, stdout=slave, stderr=slave, env=env,
                         start_new_session=True)
    os.close(slave)
    raw = bytearray()
    lock = threading.Lock()

    def reader():
        while True:
            try:
                data = os.read(master, 65536)
            except OSError:
                return
            if not data:
                return
            with lock:
                raw.extend(data)

    threading.Thread(target=reader, daemon=True).start()

    def settle(quiet, timeout=20):
        end = time.time() + timeout
        last, since = -1, time.time()
        while time.time() < end:
            with lock:
                n = len(raw)
            if n != last:
                last, since = n, time.time()
            elif time.time() - since >= quiet:
                return
            time.sleep(0.05)

    def screen():
        with lock:
            return screen_rows(raw.decode('utf-8', 'replace'))

    screens = []
    try:
        settle(1.0)
        for k in keys:
            screens.append(screen())
            if p.poll() is not None:
                break
            os.write(master, k.encode('utf-8'))
            settle(0.5)
        screens.append(screen())
        try:
            code = p.wait(5)
        except subprocess.TimeoutExpired:
            code = 'still running'
        return screens, code
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        os.close(master)


def check(src, ref):
    with open(ref) as f:
        sessions = json.load(f)
    env = dict(os.environ, USER=sessions['username'])
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    tmp = tempfile.mkdtemp(prefix='sspchk-')
    bad = 0
    try:
        for name, flags_off, keys in SCENARIOS:
            want = sessions['scenarios'].get(name)
            if want is None:
                continue
            d = os.path.join(tmp, 'b')
            remove(d)
            make_copy(src, d, flags_off)
            start = time.time()
            screens, code = pty_session([sys.executable, os.path.abspath(PORT), '--no-fixes',
                                         '-C', d], d, keys, env)
            diffs = []
            got = [normal(s) for s in screens]
            for i, (a, b) in enumerate(zip([normal(s) for s in want['screens']], got)):
                if a != b:
                    diffs.append('screen %d (after %r):' % (i, keys[i - 1] if i else None))
                    n = max(len(a), len(b))
                    for la, lb in zip(a + [''] * (n - len(a)), b + [''] * (n - len(b))):
                        diffs.append('   %s %-74s| %s' % ('  ' if la == lb else '!=', la[:74], lb))
                    break
            if len(want['screens']) != len(got):
                diffs.append('%d screens vs %d' % (len(want['screens']), len(got)))
            if want['exit'] != code:
                diffs.append('exit: %r vs %r' % (want['exit'], code))
            files = tree(d, start)
            for k in sorted(set(want['files']) | set(files)):
                if want['files'].get(k) != files.get(k):
                    diffs.append('file %s: %s vs %s' % (k, want['files'].get(k), files.get(k)))
            print('%-4s %-16s %d keys, exit %r' % ('ok' if not diffs else 'FAIL', name, len(keys),
                                                  code))
            for line in diffs:
                print('     ' + line)
            sys.stdout.flush()
            bad += bool(diffs)
    finally:
        remove(os.path.join(tmp, 'b'))
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    return check(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    sys.exit(main())
