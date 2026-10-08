"""The CYB.CFG audio settings: the original's COPY /A + sed.exe + ATTRIB sequence against ssp.py.

    py tests/compare_cybcfg.py SSP_FOLDER

SSP_FOLDER is an SSP installation (RES\\SED\\sed.exe is used).  Windows only.  Each sample
CYB.CFG goes through the lines of SSP.bat's :DOSBOX label in cmd.exe, and through ssp.py, in
two scratch folders; the resulting RES\\CYB.CFG (bytes, read-only attribute) must be the same.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import ssp  # noqa: E402

BAT = r'''@echo off
COPY /A /V /Y RES\CYB.CFG RES\SED\CYB.CFG~TEMP >nul
CD RES/SED
sed.exe -e "s:digi_list.*:digi_list 0:g" -e "s:digi_card.*:digi_card 3:g" -e "s:digi_irq.*:digi_irq 7:g" <CYB.CFG~TEMP >CYB.CFG
CD ../..
ATTRIB -R RES\CYB.CFG
COPY /A /V /Y RES\SED\CYB.CFG RES\CYB.CFG >nul
ATTRIB +R RES\CYB.CFG
DEL RES\SED\CYB.CFG~TEMP
DEL RES\SED\CYB.CFG
'''

CFG = (b'midi_list 9\r\nlowres_cutscenes 0\r\nmidi_io -1\r\nmidi_irq -1\r\ninp6d -1\r\n'
       b'digi_list 3\r\njoystick 128\r\nmidi_card 12\r\nmidi_dma -1\r\nmidi_drq -1\r\n'
       b'cd_data_dir_path D:\\cdrom\\data\r\ndigi_io -1\r\ndigi_irq -1\r\ndigi_card 1\r\n'
       b'digi_dma -1\r\nlanguage 0\r\ndigi_drq -1\r\n')

SAMPLES = {
    'plain': CFG,
    'with Ctrl-Z': CFG + b'\x1a',
    'junk after Ctrl-Z': CFG + b'\x1adigi_list 5\r\n',
    'no final newline': CFG.rstrip(b'\r\n'),
    'LF only': CFG.replace(b'\r\n', b'\n'),
    'lone CR, CR CR LF': CFG.replace(b'joystick 128\r\n', b'joy\rstick\r\r\n'),
    'mid-line match': CFG + b'xdigi_list_extra  9 9\r\ndigi_irq\r\n',
    'empty': b'',
    'read-only': CFG,
    'eXo': None,
}


def run(base, sample, readonly, port):
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(os.path.join(base, 'RES', 'SED'))
    for n in os.listdir(os.path.join(SRC, 'RES', 'SED')):
        shutil.copy(os.path.join(SRC, 'RES', 'SED', n), os.path.join(base, 'RES', 'SED'))
    cfg = os.path.join(base, 'RES', 'CYB.CFG')
    with open(cfg, 'wb') as f:
        f.write(sample)
    if readonly:
        os.chmod(cfg, stat.S_IREAD)
    if port:
        old = os.getcwd()
        os.chdir(base)
        try:
            ssp.SSP(None, None, 'test').sed_cyb_cfg(b'0', b'3', b'7')
        finally:
            os.chdir(old)
    else:
        with open(os.path.join(base, 'go.bat'), 'w', newline='\r\n') as f:
            f.write(BAT)
        subprocess.run(['cmd', '/c', 'go.bat'], cwd=base, capture_output=True)
        os.remove(os.path.join(base, 'go.bat'))
    with open(cfg, 'rb') as f:
        body = f.read()
    left = sorted(os.listdir(os.path.join(base, 'RES', 'SED')))
    ro = not os.access(cfg, os.W_OK)
    os.chmod(cfg, stat.S_IWRITE)
    return body, ro, left


SRC = None


def main():
    global SRC
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    SRC = sys.argv[1]
    with open(os.path.join(SRC, 'RES', 'CYB.CFG'), 'rb') as f:
        SAMPLES['eXo'] = f.read()
    tmp = tempfile.mkdtemp(prefix='sspcyb-')
    bad = 0
    try:
        for name, sample in SAMPLES.items():
            a = run(os.path.join(tmp, 'a'), sample, name == 'read-only', False)
            b = run(os.path.join(tmp, 'b'), sample, name == 'read-only', True)
            ok = a[:2] == b[:2]
            print('%-4s %-20s %r' % ('ok' if ok else 'FAIL', name, a[0][-24:]))
            if not ok:
                print('     sed.exe: %r read-only=%s\n     ssp.py:  %r read-only=%s'
                      % (a[0], a[1], b[0], b[1]))
                bad += 1
            if a[2] != b[2][:0] + a[2]:
                print('     SED folder left: %s' % a[2])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
