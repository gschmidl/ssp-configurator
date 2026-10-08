"""ssp.py's fixes of the original's bugs, and that --no-fixes keeps the bugs.

    python3 tests/test_fixes.py SSP_FOLDER

SSP_FOLDER is an SSP installation (its RES).  Any system.  Each check runs the script with
scripted answers and a console that shows nothing, on a scratch copy.
"""
import os
import shutil
import stat
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
import ssp  # noqa: E402
from scenarios import make_copy, remove  # noqa: E402


class QuietConsole:
    """a console that takes its answers from a list and keeps what was printed"""

    def __init__(self, answers):
        self.answers = list(answers)
        self.text = []
        self.out = sys.stdout

    def readline(self):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def echo(self, text=''):
        self.text.append(text)

    def write(self, text):
        self.text.append(text)

    def chcp850(self):
        pass

    color = mode = cls = pause = finish = chcp850

    def title(self, text):
        pass


def run(folder, answers, fixes=True):
    """(what was printed, 'ok' or 'abort' or 'eof')"""
    con = QuietConsole(answers)
    old = os.getcwd()
    os.chdir(folder)
    try:
        ssp.SSP(con, None, 'test', fixes=fixes).main()
        how = 'ok'
    except ssp.BatchAbort:
        how = 'abort'
    except EOFError:
        how = 'eof'
    finally:
        os.chdir(old)
    return con.text, how


def member(src, archive, name):
    tmp = tempfile.mkdtemp(prefix='sspfx-')
    try:
        ssp.SevenZip(os.path.join(src, 'RES', 'SSP', 'mods', archive)).extract(tmp)
        with open(os.path.join(tmp, name), 'rb') as f:
            return f.read()
    finally:
        remove(tmp)


def read(path):
    with open(path, 'rb') as f:
        return f.read()


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    tmp = tempfile.mkdtemp(prefix='sspfix-')
    d = os.path.join(tmp, 'ssp')
    res = os.path.join(d, 'RES')
    bad = 0

    def check(ok, what):
        nonlocal bad
        print('%-4s %s' % ('ok' if ok else 'FAIL', what))
        bad += not ok

    try:
        # 1. mouselook off brings back the stock executable (the flags start with mouselook on)
        stock = member(src, '640x480.7z', 'cdshock.exe')
        for fixes in (True, False):
            remove(d)
            make_copy(src, d)
            run(d, ['o', 'e', 'q'], fixes)
            names = os.listdir(res)
            exe = [n for n in names if n.lower() == 'cdshock.exe']
            got = read(os.path.join(res, exe[0])) if len(exe) == 1 else None
            if fixes:
                check(got == stock and 'dos4gw.exe' not in names,
                      'mouselook off: the stock CauseWay cdshock.exe is back')
            else:
                check(got != stock and 'dos4gw.exe' not in names,
                      '--no-fixes: mouselook off leaves the DOS/4GW CDSHOCK.EXE without dos4gw.exe')

        # 2. scaled textures off puts the original CITMAT.RES into DATA, and on again the scaled one
        plain = member(src, 'CITMAT.7z', 'CITMAT.RES')
        scaled = member(src, 'citmat_scaled.7z', os.path.join('DATA', 'CITMAT.RES'))
        for fixes in (True, False):
            remove(d)
            make_copy(src, d)
            run(d, ['o', 'p', 'q'], fixes)
            data = read(os.path.join(res, 'DATA', 'CITMAT.RES'))
            stray = os.path.exists(os.path.join(res, 'CITMAT.RES'))
            if fixes:
                check(data == plain and not stray, 'textures off: DATA\\CITMAT.RES is the original')
                run(d, ['o', 'p', 'q'], fixes)
                check(read(os.path.join(res, 'DATA', 'CITMAT.RES')) == scaled,
                      'textures on again: DATA\\CITMAT.RES is the scaled one')
            else:
                check(data == scaled and stray,
                      '--no-fixes: textures off leaves the scaled one, CITMAT.RES lands in RES')

        # 3. a wrong key in "Edit CYB.CFG" leaves the write protection alone
        for fixes in (True, False):
            remove(d)
            make_copy(src, d)
            cfg = os.path.join(res, 'CYB.CFG')
            os.chmod(cfg, stat.S_IREAD)
            text, _ = run(d, ['o', 'c', 'c', 'z', 'q'], fixes)
            protected = not os.access(cfg, os.W_OK)
            if fixes:
                check(protected and ' CYB.CFG is writable now.' not in text,
                      'Edit CYB.CFG, wrong key: still write-protected')
            else:
                check(not protected and ' CYB.CFG is writable now.' in text,
                      '--no-fixes: wrong key removes the write protection')

        # 4. odd answers are ordinary wrong answers
        remove(d)
        make_copy(src, d)
        for answer, shown in (('"', '"""'), ('a b"c d"', '"a"'), ('>', '">"'), ('&', '"&"'),
                              ('^', '"^"')):
            text, how = run(d, [answer, 'q'])
            check(how == 'ok' and shown + ' is not a valid choice. Please try again.' in text,
                  'answer %r: %s is not a valid choice' % (answer, shown))
            text, how = run(d, [answer, 'q'], False)
            check(how == ('abort' if answer in ('"', 'a b"c d"', '>') else 'ok'),
                  '--no-fixes: answer %r as cmd parses it (%s)' % (answer, how))
    finally:
        remove(d)
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
