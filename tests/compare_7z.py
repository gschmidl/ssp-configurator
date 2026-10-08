"""Extract every SSP mod archive with the original 7za.exe 4.42 and with ssp.py; compare.

    py tests/compare_7z.py SSP_FOLDER

SSP_FOLDER is an SSP installation (the folder holding SSP.exe and RES).  Windows only (7za.exe).
Both extractions start from the same scratch folder, seeded with files the archives overwrite:
read-only ones and ones whose names differ in case.  Compared: names (with case), contents,
modification times and Windows attributes of every file and folder.
"""
import ctypes
import os
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ssp  # noqa: E402

k32 = ctypes.windll.kernel32
k32.GetFileAttributesW.restype = ctypes.c_uint32


def seed(d):
    os.makedirs(os.path.join(d, 'DATA'))
    for name in ('DATA/CYBSTRNG.RES', 'CDSHOCK.EXE', 'CYB.CFG', 'CITMAT.RES', 'dos4gw.exe'):
        p = os.path.join(d, name)
        with open(p, 'wb') as f:
            f.write(b'old ' + name.encode())
        os.utime(p, (1e9, 1e9))
        os.chmod(p, stat.S_IREAD)
    os.utime(os.path.join(d, 'DATA'), (1e9, 1e9))


def snapshot(d):
    out = {}
    for dp, dns, fns in os.walk(d):
        for n in dns + fns:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, d)
            st = os.stat(p)
            body = None
            if os.path.isfile(p):
                with open(p, 'rb') as f:
                    body = f.read()
            out[rel] = (body, st.st_mtime_ns // 100, k32.GetFileAttributesW(p))
    return out


def unlock(d):
    for dp, dns, fns in os.walk(d):
        for n in fns:
            os.chmod(os.path.join(dp, n), stat.S_IWRITE)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    base = sys.argv[1]
    res = os.path.join(base, 'RES')
    za = os.path.join(res, '7za.exe')
    mods = os.path.join(res, 'SSP', 'mods')
    tmp = tempfile.mkdtemp(prefix='ssp7z-')
    bad = 0
    try:
        for name in sorted(os.listdir(mods)):
            if not name.lower().endswith('.7z'):
                continue
            arc = os.path.join(mods, name)
            a, b = os.path.join(tmp, 'a'), os.path.join(tmp, 'b')
            for d in (a, b):
                if os.path.exists(d):
                    unlock(d)
                    shutil.rmtree(d)
                seed(d)
            r = subprocess.run([za, 'x', '-y', arc], cwd=a, capture_output=True, text=True)
            ssp.SevenZip(arc).extract(b)
            sa, sb = snapshot(a), snapshot(b)
            diffs = []
            for k in sorted(set(sa) | set(sb)):
                if k not in sa or k not in sb:
                    diffs.append('%s only in %s' % (k, '7za' if k in sa else 'ssp.py'))
                    continue
                for what, x, y in zip(('content', 'mtime', 'attributes'), sa[k], sb[k]):
                    if what == 'mtime' and sa[k][0] is None:
                        continue            # neither sets a folder's time: both are "now"
                    if x != y:
                        diffs.append('%s: %s differs (7za %s, ssp.py %s)' % (
                            k, what, x if what != 'content' else len(x or b''),
                            y if what != 'content' else len(y or b'')))
            if r.returncode:
                diffs.append('7za exit %d: %s' % (r.returncode, r.stdout[-300:]))
            print('%-4s %-22s %d entries' % ('ok' if not diffs else 'FAIL', name, len(sa)))
            for line in diffs:
                print('       ' + line)
            bad += bool(diffs)
    finally:
        for d in ('a', 'b'):
            if os.path.exists(os.path.join(tmp, d)):
                unlock(os.path.join(tmp, d))
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
