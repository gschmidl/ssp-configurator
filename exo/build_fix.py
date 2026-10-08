"""Builds the fixed SSP.exe: the original with SSP.bat (this folder's) as its script.

    py build_fix.py [--upx UPX] [-o OUT] ORIGINAL_SSP_EXE

ORIGINAL_SSP_EXE is SSP 1.2's SSP.exe (eXo's eXoDOS/SystemSh/SSP/SSP.exe).  It is UPX-packed;
UPX (--upx, else $UPX_PATH, else upx on the PATH) unpacks it.  The script is the exe's RCDATA
resource "B"; it is replaced with this folder's SSP.bat (with CRLF line ends), everything
else stays.  OUT defaults
to SSP.exe in this folder.  Windows only (the resource is replaced with UpdateResource).
"""
import argparse
import ctypes
import ctypes.wintypes as W
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RT_RCDATA = 10
LOAD_LIBRARY_AS_DATAFILE = 0x2

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.LoadLibraryExW.restype = W.HMODULE
k32.LoadLibraryExW.argtypes = [W.LPCWSTR, W.HANDLE, W.DWORD]
k32.FreeLibrary.argtypes = [W.HMODULE]
ENUMLANG = ctypes.WINFUNCTYPE(W.BOOL, W.HMODULE, ctypes.c_void_p, ctypes.c_void_p, W.WORD,
                              ctypes.c_void_p)
k32.EnumResourceLanguagesW.argtypes = [W.HMODULE, ctypes.c_void_p, W.LPCWSTR, ENUMLANG,
                                       ctypes.c_void_p]
k32.FindResourceExW.restype = ctypes.c_void_p
k32.FindResourceExW.argtypes = [W.HMODULE, ctypes.c_void_p, W.LPCWSTR, W.WORD]
k32.LoadResource.restype = ctypes.c_void_p
k32.LoadResource.argtypes = [W.HMODULE, ctypes.c_void_p]
k32.SizeofResource.argtypes = [W.HMODULE, ctypes.c_void_p]
k32.LockResource.restype = ctypes.c_void_p
k32.LockResource.argtypes = [ctypes.c_void_p]
k32.BeginUpdateResourceW.restype = W.HANDLE
k32.BeginUpdateResourceW.argtypes = [W.LPCWSTR, W.BOOL]
k32.UpdateResourceW.argtypes = [W.HANDLE, ctypes.c_void_p, W.LPCWSTR, W.WORD, ctypes.c_void_p,
                                W.DWORD]
k32.EndUpdateResourceW.argtypes = [W.HANDLE, W.BOOL]


def script(path):
    """(language, bytes) of PATH's script resource"""
    h = k32.LoadLibraryExW(path, None, LOAD_LIBRARY_AS_DATAFILE)
    if not h:
        raise OSError('cannot open %s: %d' % (path, ctypes.get_last_error()))
    try:
        langs = []
        cb = ENUMLANG(lambda m, t, n, lang, p: langs.append(lang) or True)
        k32.EnumResourceLanguagesW(h, RT_RCDATA, 'B', cb, None)
        if len(langs) != 1:
            raise ValueError('%s: %d script resources, expected 1' % (path, len(langs)))
        res = k32.FindResourceExW(h, RT_RCDATA, 'B', langs[0])
        size = k32.SizeofResource(h, res)
        data = ctypes.string_at(k32.LockResource(k32.LoadResource(h, res)), size)
        return langs[0], data
    finally:
        k32.FreeLibrary(h)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('original')
    ap.add_argument('--upx', default=os.environ.get('UPX_PATH') or shutil.which('upx'))
    ap.add_argument('-o', '--output', default=os.path.join(HERE, 'SSP.exe'))
    args = ap.parse_args()
    if not args.upx:
        sys.exit('build_fix.py: UPX is needed to unpack SSP.exe '
                 '(--upx, $UPX_PATH or upx on the PATH)')
    with open(os.path.join(HERE, 'SSP.bat'), 'rb') as f:
        # CRLF: the original's script has LF line ends, and in an LF-only batch file cmd's
        # GOTO can find a label inside a line ("clicking: Options" for :OPTIONS)
        fixed = f.read().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    tmp = tempfile.mkdtemp(prefix='sspfix-')
    try:
        work = os.path.join(tmp, 'SSP.exe')
        env = {k: v for k, v in os.environ.items() if k.upper() != 'UPX'}  # UPX's own options
        r = subprocess.run([args.upx, '-d', '-q', '-o', work, args.original],
                           capture_output=True, text=True, env=env)
        if r.returncode:
            sys.exit('build_fix.py: upx -d failed:\n' + r.stdout + r.stderr)
        lang, old = script(work)
        h = k32.BeginUpdateResourceW(work, False)
        if not h:
            sys.exit('build_fix.py: BeginUpdateResource: %d' % ctypes.get_last_error())
        buf = ctypes.create_string_buffer(fixed, len(fixed))
        if not k32.UpdateResourceW(h, RT_RCDATA, 'B', lang, buf, len(fixed)):
            k32.EndUpdateResourceW(h, True)
            sys.exit('build_fix.py: UpdateResource: %d' % ctypes.get_last_error())
        if not k32.EndUpdateResourceW(h, False):
            sys.exit('build_fix.py: EndUpdateResource: %d' % ctypes.get_last_error())
        if script(work) != (lang, fixed):
            sys.exit('build_fix.py: the new exe does not hold the new script')
        shutil.copyfile(work, args.output)
        print('%s: script %d -> %d bytes (language %d), %d bytes' % (
            args.output, len(old), len(fixed), lang, os.path.getsize(args.output)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
