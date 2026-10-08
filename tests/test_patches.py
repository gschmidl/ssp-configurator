"""The two eXo patches (exo/fix_windows.py, exo/install_port.py) on a scratch eXo folder.

    py tests/test_patches.py EXO_FOLDER

EXO_FOLDER is an eXoDOS "eXo" folder; only its SSP.exe (from the installed game or the game's
zip) and !dos\\SystemSh\\exception.bat (or exception.bat.orig, if a patch is applied there) are
read.
Each patch is checked, applied, applied again, reverted; the files must end up as they were.
The patched launcher's "SSP Configurator" lines also run, in a pseudo console: with Python
(a stub ssp.py says how it was started), without ssp.py and without py (SSP.EXE runs).
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from conpty import Window  # noqa: E402

EXO = os.path.join(HERE, '..', 'exo')
SHA1_ORIGINAL = '836c6b4e77782d2aa21e57b80d754e46819d3a24'
STUB = "import os, sys\nprint('PORT-RAN', sys.argv[1:], os.path.basename(os.getcwd()))\n"


def configurator(launcher, folder, no_py=False):
    """run the launcher's :SSPCFG lines from FOLDER (its !dos\\SystemSh); the screen at the end"""
    lines = launcher.decode('latin-1').split('\r\n')
    start = lines.index(':SSPCFG')
    end = lines.index(':sspcfg_exe', start) + 3          # SSP.EXE, goto ssp
    bat = ['@echo off'] + (['set "PATH=%SystemRoot%\\System32"'] if no_py else [])
    bat += ['goto SSPCFG'] + lines[start:end] + [':ssp', 'echo LAUNCHER-BACK']
    test = os.path.join(folder, 'test.bat')
    with open(test, 'w', newline='\r\n') as f:
        f.write('\n'.join(bat) + '\n')
    # as from eXo: programs in the current folder are found (SSP.EXE; not MSYS's ssp on the PATH)
    saved = os.environ.pop('NoDefaultCurrentDirectoryInExePath', None)
    try:
        w = Window('launcher', 'cmd /c test.bat', cwd=folder)
    finally:
        if saved is not None:
            os.environ['NoDefaultCurrentDirectoryInExePath'] = saved
    try:
        w.settle(1.0)
        if 'SHODAN' in ''.join(w.screen()):              # SSP.EXE: past the splash, then quit
            w.type(' ')
            w.settle(0.8)
            w.type('q\r')
        w.wait_exit(20)
        w.settle(0.5)
        return '\n'.join(r for r in w.screen() if r.strip())
    finally:
        w.close()
        os.remove(test)


def sha1(path):
    with open(path, 'rb') as f:
        return hashlib.sha1(f.read()).hexdigest()


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(EXO, script)] + list(args),
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    real = sys.argv[1]
    tmp = tempfile.mkdtemp(prefix='sspexo-')
    exo = os.path.join(tmp, 'eXo')
    ssp = os.path.join(exo, 'eXoDOS', 'SystemSh', 'SSP')
    dos = os.path.join(exo, 'eXoDOS', '!dos', 'SystemSh')
    os.makedirs(ssp)
    os.makedirs(dos)
    os.makedirs(os.path.join(exo, 'util'))
    exe = os.path.join(tmp, 'SSP.exe.original')
    for p in ('SSP.exe', 'SSP.exe.orig'):
        p = os.path.join(real, 'eXoDOS', 'SystemSh', 'SSP', p)
        if os.path.isfile(p) and sha1(p) == SHA1_ORIGINAL:
            shutil.copy2(p, exe)
            break
    else:                                   # not installed (or patched without .orig): the zip
        with zipfile.ZipFile(os.path.join(real, 'eXoDOS', 'System Shock (1994).zip')) as z:
            with open(exe, 'wb') as f:
                f.write(z.read('SystemSh/SSP/SSP.exe'))
    shutil.copy2(exe, os.path.join(ssp, 'SSP.exe'))
    bat = os.path.join(real, 'eXoDOS', '!dos', 'SystemSh', 'exception.bat')
    if os.path.exists(bat + '.orig'):
        bat += '.orig'
    shutil.copy2(bat, os.path.join(dos, 'exception.bat'))
    with open(os.path.join(dos, 'exception.bat'), 'rb') as f:
        launcher = f.read()
    bad = 0

    def check(ok, what, out=''):
        nonlocal bad
        print('%-4s %s' % ('ok' if ok else 'FAIL', what))
        if not ok and out:
            print('     ' + out.replace('\n', '\n     '))
        bad += not ok

    try:
        target = os.path.join(ssp, 'SSP.exe')
        code, out = run('fix_windows.py', '--check', exo)
        check(code == 0 and out.startswith('would replace') and sha1(target) == SHA1_ORIGINAL,
              'fix_windows --check: says it would replace, changes nothing', out)
        code, out = run('fix_windows.py', exo)
        check(code == 0 and sha1(target) == sha1(os.path.join(EXO, 'SSP.exe'))
              and sha1(target + '.orig') == SHA1_ORIGINAL, 'fix_windows: fixed exe in, .orig kept',
              out)
        code, out = run('fix_windows.py', exo)
        check(code == 0 and 'already' in out, 'fix_windows again: already done', out)
        code, out = run('fix_windows.py', '--revert', exo)
        check(code == 0 and sha1(target) == SHA1_ORIGINAL and not os.path.exists(target + '.orig'),
              'fix_windows --revert: original back, .orig gone', out)

        with open(target, 'ab') as f:
            f.write(b'x')
        code, out = run('fix_windows.py', exo)
        check(code != 0 and 'left alone' in out, 'fix_windows: an unknown SSP.exe is left alone',
              out)

        bat = os.path.join(dos, 'exception.bat')
        code, out = run('install_port.py', '--check', exo)
        check(code == 0 and 'would switch' in out and not os.path.exists(os.path.join(exo, 'util',
                                                                                     'ssp')),
              'install_port --check: says what it would do, changes nothing', out)
        code, out = run('install_port.py', exo)
        with open(bat, 'rb') as f:
            new = f.read()
        files = sorted(os.listdir(os.path.join(exo, 'util', 'ssp')))
        check(code == 0 and files == ['LICENSE', 'NOTES.md', 'README.md', 'ssp.py']
              and new.count(b'\r\n') == launcher.count(b'\r\n') + 6
              and new.count(b'\n') == new.count(b'\r\n')
              and b'\r\npy ..\\..\\..\\util\\ssp\\ssp.py -C .\r\ngoto ssp\r\n:sspcfg_exe\r\nSSP.EXE'
              b'\r\ngoto ssp\r\n' in new, 'install_port: util\\ssp filled, launcher patched (CRLF)',
              out)
        code, out = run('install_port.py', exo)
        check(code == 0 and out == '', 'install_port again: nothing to do', out)

        shutil.copy2(exe, os.path.join(ssp, 'SSP.exe'))      # the earlier test spoilt it
        port = os.path.join(exo, 'util', 'ssp', 'ssp.py')
        with open(port, 'rb') as f:
            real_port = f.read()
        with open(port, 'w') as f:
            f.write(STUB)
        screen = configurator(new, dos)
        check("PORT-RAN ['-C', '.'] SSP" in screen and 'LAUNCHER-BACK' in screen
              and 'Main Menu' not in screen, 'launcher with py: runs util\\ssp\\ssp.py -C . in '
              'the SSP folder, then back to the menu', screen)
        screen = configurator(new, dos, no_py=True)
        check('PORT-RAN' not in screen and 'Main Menu' in screen and 'LAUNCHER-BACK' in screen,
              'launcher without py: SSP.EXE, then back to the menu', screen)
        os.remove(port)
        screen = configurator(new, dos)
        check('PORT-RAN' not in screen and 'Main Menu' in screen and 'LAUNCHER-BACK' in screen,
              'launcher without util\\ssp\\ssp.py: SSP.EXE, then back to the menu', screen)
        with open(port, 'wb') as f:
            f.write(real_port)
        code, out = run('install_port.py', '--revert', exo)
        with open(bat, 'rb') as f:
            back = f.read()
        check(code == 0 and back == launcher and not os.path.exists(bat + '.orig')
              and not os.path.exists(os.path.join(exo, 'util', 'ssp')),
              'install_port --revert: launcher as it was, util\\ssp gone', out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
