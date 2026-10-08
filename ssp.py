#!/usr/bin/env python3
"""ssp.py - a portable port of SSP.exe, the SYSTEMSHOCK-Portable 1.2 launcher.

SSP.exe (Nicolai Sandow, GPL) is the batch file SSP.bat wrapped by a
"Bat To Exe Converter": the exe writes the script to a temporary folder and
runs it with cmd.exe in the current directory.  This is that script, label by
label, in Python 3 (standard library only), so it runs on macOS, Linux and
Windows without Wine.  The script's own 7za.exe and sed.exe calls are done
here directly: a small 7z reader (LZMA, LZMA2, BCJ) and the three sed
substitutions on CYB.CFG.

Run it from anywhere; it works in its own folder (the one holding RES), or in
the folder given with -C.  See README.md.

Copyright 2006-2010 Nicolai Sandow (SSP.bat), 2026 Gunther Schmidl (this port).
This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.  It is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details
(RES/SSP/src/gpl.txt, or <https://www.gnu.org/licenses/>).
"""

import argparse
import getpass
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import time
import zlib

try:
    import lzma
except ImportError:             # a Python built without liblzma: menus work, mods do not
    lzma = None

__version__ = '1.0'

SSPVER = '1.2'
WINDOWS = os.name == 'nt'
MACOS = sys.platform == 'darwin'


# ----------------------------------------------------------------------------
# Paths the way Windows sees them

def winpath(path):
    """PATH (relative, either slash) as this system names it.  On a
    case-sensitive file system every component that exists under another
    case is used under that name, as Windows would find it."""
    drive, rest = os.path.splitdrive(path)
    root = drive + (os.sep if rest[:1] in ('/', '\\') else '')
    parts = [p for p in re.split(r'[\\/]+', rest) if p not in ('', '.')]
    if not parts:
        return root or '.'
    if WINDOWS:
        return os.path.join(root, *parts)
    cur = root
    for part in parts:
        cand = os.path.join(cur, part) if cur else part
        if part != '..' and not os.path.lexists(cand):
            try:
                low = part.lower()
                same = sorted(n for n in os.listdir(cur or '.') if n.lower() == low)
            except OSError:
                same = []
            if same:
                cand = os.path.join(cur, same[0]) if cur else same[0]
        cur = cand
    return cur


def exists(path):
    return os.path.exists(winpath(path))


def delete(path):
    """DEL: a missing or read-only file stays as it is (cmd's message for it
    is cleared by the CLS that follows in every case)"""
    p = winpath(path)
    try:
        if os.path.isfile(p) and (WINDOWS or os.access(p, os.W_OK)):
            os.remove(p)
    except OSError:
        pass


def append_flag(path):
    """ECHO flag >> PATH"""
    try:
        with open(winpath(path), 'ab') as f:
            f.write(b'flag \r\n')
    except OSError as e:
        print(e, file=sys.stderr)


def set_readonly(path, on):
    """ATTRIB +R / -R"""
    p = winpath(path)
    try:
        mode = os.stat(p).st_mode
        if on:
            os.chmod(p, stat.S_IMODE(mode) & ~0o222)
        else:
            os.chmod(p, stat.S_IMODE(mode) | stat.S_IWRITE)
    except OSError:
        pass


def remove_any_case(folder, name):
    """delete FOLDER/NAME, under any case on a case-sensitive system"""
    names = [name]
    if not WINDOWS:
        try:
            names = [n for n in os.listdir(folder or '.') if n.lower() == name.lower()]
        except OSError:
            names = []
    for n in names:
        p = os.path.join(folder, n) if folder else n
        if os.path.isfile(p) or os.path.islink(p):
            try:
                os.chmod(p, stat.S_IMODE(os.lstat(p).st_mode) | stat.S_IWRITE)
            except OSError:
                pass
            os.remove(p)


# ----------------------------------------------------------------------------
# 7z archives (what 7za 4.42 "x -y" does with SSP's mods)

class SevenZipError(Exception):
    pass


K_END, K_HEADER, K_ARCHIVE_PROPERTIES, K_ADDITIONAL_STREAMS_INFO = 0x00, 0x01, 0x02, 0x03
K_MAIN_STREAMS_INFO, K_FILES_INFO, K_PACK_INFO, K_UNPACK_INFO = 0x04, 0x05, 0x06, 0x07
K_SUBSTREAMS_INFO, K_SIZE, K_CRC, K_FOLDER = 0x08, 0x09, 0x0A, 0x0B
K_CODERS_UNPACK_SIZE, K_NUM_UNPACK_STREAM, K_EMPTY_STREAM, K_EMPTY_FILE = 0x0C, 0x0D, 0x0E, 0x0F
K_ANTI, K_NAME, K_MTIME, K_WIN_ATTRIBUTES, K_ENCODED_HEADER = 0x10, 0x11, 0x14, 0x15, 0x17

ATTR_READONLY = 0x01
ATTR_DIRECTORY = 0x10


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def byte(self):
        if self.p >= len(self.d):
            raise SevenZipError('truncated header')
        self.p += 1
        return self.d[self.p - 1]

    def take(self, n):
        if self.p + n > len(self.d):
            raise SevenZipError('truncated header')
        self.p += n
        return self.d[self.p - n:self.p]

    def num(self):
        first = self.byte()
        mask = 0x80
        value = 0
        for i in range(8):
            if not first & mask:
                return value | ((first & (mask - 1)) << (8 * i))
            value |= self.byte() << (8 * i)
            mask >>= 1
        return value

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def u64(self):
        return struct.unpack('<Q', self.take(8))[0]

    def bits(self, n):
        out = []
        b = mask = 0
        for _ in range(n):
            if not mask:
                b, mask = self.byte(), 0x80
            out.append(bool(b & mask))
            mask >>= 1
        return out

    def defined(self, n):
        return [True] * n if self.byte() else self.bits(n)


class _Folder:
    def __init__(self):
        self.coders = []            # (method id, properties)
        self.bind_pairs = []        # (in stream, out stream)
        self.packed = []            # in streams fed from the archive
        self.unpack_sizes = []
        self.crc = None
        self.sub_sizes = []
        self.sub_crcs = []

    def main_out(self):
        bound = {o for _, o in self.bind_pairs}
        return next(o for o in range(len(self.unpack_sizes)) if o not in bound)

    def size(self):
        return self.unpack_sizes[self.main_out()]


class _Streams:
    def __init__(self):
        self.pack_pos = 0
        self.pack_sizes = []
        self.folders = []


def _lzma_filter(method, props):
    if lzma is None:
        raise SevenZipError('this Python has no lzma module')
    if method == b'\x03\x01\x01':                       # LZMA
        if len(props) < 5:
            raise SevenZipError('bad LZMA properties')
        d = props[0]
        return {'id': lzma.FILTER_LZMA1, 'lc': d % 9, 'lp': d // 9 % 5, 'pb': d // 45,
                'dict_size': struct.unpack('<I', props[1:5])[0]}
    if method == b'\x21':                               # LZMA2
        d = props[0] if props else 0
        size = 0xFFFFFFFF if d >= 40 else (2 | (d & 1)) << (d // 2 + 11)
        return {'id': lzma.FILTER_LZMA2, 'dict_size': size}
    if method == b'\x03\x03\x01\x03':                   # BCJ (x86)
        f = {'id': lzma.FILTER_X86}
        if len(props) == 4:
            f['start_offset'] = struct.unpack('<I', props)[0]
        return f
    if method == b'\x03':                               # Delta
        return {'id': lzma.FILTER_DELTA, 'dist': (props[0] if props else 0) + 1}
    raise SevenZipError('unsupported compression method %s' % method.hex())


class SevenZip:
    """a 7z archive: the files it holds, and their extraction"""

    def __init__(self, path):
        with open(path, 'rb') as f:
            self.data = f.read()
        d = self.data
        if d[:6] != b"7z\xbc\xaf'\x1c" or len(d) < 32:
            raise SevenZipError('not a 7z archive')
        if zlib.crc32(d[12:32]) != struct.unpack_from('<I', d, 8)[0]:
            raise SevenZipError('damaged archive (start header)')
        off, size, crc = struct.unpack_from('<QQI', d, 12)
        header = d[32 + off:32 + off + size]
        if len(header) != size or zlib.crc32(header) != crc:
            raise SevenZipError('damaged archive (header)')
        self.streams = _Streams()
        self.files = []
        if not header:
            return
        r = _Reader(header)
        kind = r.byte()
        while kind == K_ENCODED_HEADER:
            streams = self._streams_info(r)
            r = _Reader(b''.join(self._unpack(streams, i) for i in range(len(streams.folders))))
            kind = r.byte()
        if kind != K_HEADER:
            raise SevenZipError('bad header')
        self._header(r)

    # -- header

    def _header(self, r):
        kind = r.byte()
        if kind == K_ARCHIVE_PROPERTIES:
            while r.byte() != K_END:
                r.take(r.num())
            kind = r.byte()
        if kind == K_ADDITIONAL_STREAMS_INFO:
            raise SevenZipError('unsupported archive (additional streams)')
        if kind == K_MAIN_STREAMS_INFO:
            self.streams = self._streams_info(r)
            kind = r.byte()
        if kind == K_FILES_INFO:
            self._files_info(r)
            kind = r.byte()
        if kind != K_END:
            raise SevenZipError('bad header')

    def _streams_info(self, r):
        s = _Streams()
        kind = r.byte()
        if kind == K_PACK_INFO:
            s.pack_pos = r.num()
            n = r.num()
            kind = r.byte()
            if kind == K_SIZE:
                s.pack_sizes = [r.num() for _ in range(n)]
                kind = r.byte()
            if kind == K_CRC:
                for ok in r.defined(n):
                    if ok:
                        r.u32()
                kind = r.byte()
            if kind != K_END:
                raise SevenZipError('bad pack info')
            kind = r.byte()
        if kind == K_UNPACK_INFO:
            if r.byte() != K_FOLDER:
                raise SevenZipError('bad unpack info')
            n = r.num()
            if r.byte():
                raise SevenZipError('unsupported archive (external folders)')
            s.folders = [self._folder(r) for _ in range(n)]
            if r.byte() != K_CODERS_UNPACK_SIZE:
                raise SevenZipError('bad unpack info')
            for f in s.folders:
                f.unpack_sizes = [r.num() for _ in range(f.num_out)]
            kind = r.byte()
            if kind == K_CRC:
                for f, ok in zip(s.folders, r.defined(n)):
                    f.crc = r.u32() if ok else None
                kind = r.byte()
            if kind != K_END:
                raise SevenZipError('bad unpack info')
            kind = r.byte()
        counts = [1] * len(s.folders)
        if kind == K_SUBSTREAMS_INFO:
            kind = r.byte()
            if kind == K_NUM_UNPACK_STREAM:
                counts = [r.num() for _ in s.folders]
                kind = r.byte()
            sized = kind == K_SIZE
            for f, n in zip(s.folders, counts):
                if not n:
                    continue
                sizes = [r.num() for _ in range(n - 1)] if sized else []
                f.sub_sizes = sizes + [f.size() - sum(sizes)]
            if sized:
                kind = r.byte()
            need = sum(n for f, n in zip(s.folders, counts) if not (n == 1 and f.crc is not None))
            crcs = [None] * need
            if kind == K_CRC:
                crcs = [r.u32() if ok else None for ok in r.defined(need)]
                kind = r.byte()
            for f, n in zip(s.folders, counts):
                if n == 1 and f.crc is not None:
                    f.sub_crcs = [f.crc]
                else:
                    f.sub_crcs, crcs = crcs[:n], crcs[n:]
            if kind != K_END:
                raise SevenZipError('bad substreams info')
            kind = r.byte()
        else:
            for f in s.folders:
                f.sub_sizes, f.sub_crcs = [f.size()], [f.crc]
        if kind != K_END:
            raise SevenZipError('bad streams info')
        return s

    def _folder(self, r):
        f = _Folder()
        num_in = num_out = 0
        for _ in range(r.num()):
            flags = r.byte()
            if flags & 0x80:
                raise SevenZipError('unsupported archive (alternative methods)')
            method = r.take(flags & 0x0F)
            ins, outs = (r.num(), r.num()) if flags & 0x10 else (1, 1)
            if ins != 1 or outs != 1:
                raise SevenZipError('unsupported compression method %s' % method.hex())
            props = r.take(r.num()) if flags & 0x20 else b''
            f.coders.append((method, props))
            num_in += ins
            num_out += outs
        f.num_out = num_out
        f.bind_pairs = [(r.num(), r.num()) for _ in range(num_out - 1)]
        packed = num_in - len(f.bind_pairs)
        if packed == 1:
            bound = {i for i, _ in f.bind_pairs}
            f.packed = [i for i in range(num_in) if i not in bound][:1]
        else:
            f.packed = [r.num() for _ in range(packed)]
        return f

    def _files_info(self, r):
        n = r.num()
        files = [{'name': '', 'empty_stream': False, 'empty_file': False, 'anti': False,
                  'mtime': None, 'attrib': None} for _ in range(n)]
        empty = []
        while True:
            kind = r.byte()
            if kind == K_END:
                break
            sub = _Reader(r.take(r.num()))
            if kind == K_EMPTY_STREAM:
                for f, b in zip(files, sub.bits(n)):
                    f['empty_stream'] = b
                empty = [f for f in files if f['empty_stream']]
            elif kind in (K_EMPTY_FILE, K_ANTI):
                key = 'empty_file' if kind == K_EMPTY_FILE else 'anti'
                for f, b in zip(empty, sub.bits(len(empty))):
                    f[key] = b
            elif kind == K_NAME:
                if sub.byte():
                    raise SevenZipError('unsupported archive (external names)')
                names = sub.d[sub.p:].decode('utf-16-le', 'replace').split('\0')
                for f, name in zip(files, names):
                    f['name'] = name
            elif kind in (K_MTIME, K_WIN_ATTRIBUTES):
                ok = sub.defined(n)
                if sub.byte():
                    raise SevenZipError('unsupported archive (external properties)')
                key = 'mtime' if kind == K_MTIME else 'attrib'
                for f, d in zip(files, ok):
                    if d:
                        f[key] = sub.u64() if kind == K_MTIME else sub.u32()
        # the files with data take the streams in order
        streams = [(fi, si) for fi, f in enumerate(self.streams.folders)
                   for si in range(len(f.sub_sizes))]
        k = 0
        for f in files:
            f['stream'] = None
            if not f['empty_stream']:
                if k >= len(streams):
                    raise SevenZipError('bad header (more files than streams)')
                f['stream'] = streams[k]
                k += 1
        self.files = files

    # -- data

    def _unpack(self, s, fi):
        f = s.folders[fi]
        if len(f.packed) != 1:
            raise SevenZipError('unsupported compression method (BCJ2)')
        first = sum(len(g.packed) for g in s.folders[:fi])
        start = 32 + s.pack_pos + sum(s.pack_sizes[:first])
        data = self.data[start:start + s.pack_sizes[first]]
        # follow the chain from the folder's output back to the packed stream
        # (every coder has one input and one output, so stream n is coder n's)
        feeds = {i: o for i, o in f.bind_pairs}
        chain = []
        out = f.main_out()
        for _ in f.coders:
            method, props = f.coders[out]
            if method != b'\x00':
                chain.append(_lzma_filter(method, props))
            if out not in feeds:
                break
            out = feeds[out]
        if out != f.packed[0]:
            raise SevenZipError('bad folder')
        size = f.size()
        if not chain:
            result = data[:size]
        else:
            result = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=chain).decompress(data)
            if len(result) < size and len(chain) > 1 and chain[0]['id'] == lzma.FILTER_X86:
                # without an end marker the x86 filter keeps its last (unconverted) bytes
                rest = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=chain[1:]).decompress(data)
                result += rest[len(result):size]
            result = result[:size]
        if len(result) != size:
            raise SevenZipError('data error')
        if f.crc is not None and zlib.crc32(result) != f.crc:
            raise SevenZipError('CRC error')
        return result

    def extract(self, dest):
        """7za x -y: every file to DEST under its folder names, replacing
        files that exist (read-only ones too), with the archive's
        modification time and attributes"""
        cache = {}
        for f in self.files:
            parts = [p for p in re.split(r'[\\/]+', f['name']) if p not in ('', '.', '..')]
            if not parts or f['anti']:
                continue
            attrib = f['attrib'] if f['attrib'] is not None else 0
            is_dir = (f['empty_stream'] and not f['empty_file']) or attrib & ATTR_DIRECTORY
            parent = winpath(os.path.join(dest, *parts[:-1])) if len(parts) > 1 else dest
            if is_dir:
                target = winpath(os.path.join(dest, *parts))
                os.makedirs(target, exist_ok=True)
                if WINDOWS:                         # (but not the folder's time)
                    _set_attributes(target, attrib)
                continue
            os.makedirs(parent, exist_ok=True)
            if f['stream'] is None:
                body = b''
            else:
                fi, si = f['stream']
                if fi not in cache:
                    cache = {fi: self._unpack(self.streams, fi)}
                folder = self.streams.folders[fi]
                at = sum(folder.sub_sizes[:si])
                body = cache[fi][at:at + folder.sub_sizes[si]]
                crc = folder.sub_crcs[si] if si < len(folder.sub_crcs) else None
                if crc is not None and zlib.crc32(body) != crc:
                    raise SevenZipError('CRC error in %s' % f['name'])
            remove_any_case(parent, parts[-1])
            target = os.path.join(parent, parts[-1])
            with open(target, 'wb') as out:
                out.write(body)
            if f['mtime'] is not None:
                ns = (f['mtime'] - 116444736000000000) * 100
                os.utime(target, ns=(ns, ns))
            _set_attributes(target, attrib)


def _set_attributes(path, attrib):
    if WINDOWS:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(path, attrib & 0x7FFF or 0x80)
    elif attrib & ATTR_READONLY:
        os.chmod(path, stat.S_IMODE(os.stat(path).st_mode) & ~0o222)


# ----------------------------------------------------------------------------
# The console window

class Console:
    """what SSP.bat does to its console window.  On Windows the very cmd.exe
    commands it uses (COLOR, MODE, CLS, PAUSE, CHCP), so the window looks and
    stays as after the original; elsewhere ANSI/xterm sequences"""

    def __init__(self):
        self.out = sys.stdout
        self.ansi = not WINDOWS and self.out.isatty()

    def write(self, text):
        self.out.write(text)

    def echo(self, text=''):
        self.out.write(text + '\n')

    def _cmd(self, line):
        self.out.flush()
        subprocess.call(line, shell=True)

    def chcp850(self):
        if WINDOWS:
            self._cmd('chcp 850 >nul')

    def color(self):
        """COLOR 1F: bright white on blue"""
        if WINDOWS:
            self._cmd('COLOR 1F')
        elif self.ansi:
            self.write('\x1b[0;97;44m')

    def mode(self):
        """mode con: cols=72 lines=26 (which also clears the window)"""
        if WINDOWS:
            self._cmd('mode con: cols=72 lines=26')
        elif self.ansi:
            self.write('\x1b[8;26;72t')
            self.cls()

    def cls(self):
        if WINDOWS:
            self._cmd('CLS')
        elif self.ansi:
            self.write('\x1b[H\x1b[2J\x1b[3J')
        else:
            self.write('\f')

    def title(self, text):
        if WINDOWS:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(text)
        elif self.ansi:
            self.write('\x1b]0;%s\x07' % text)

    def pause(self):
        if WINDOWS:
            self._cmd('PAUSE')
            return
        self.write('Press any key to continue . . . ')
        self.out.flush()
        if not self.getkey():
            raise EOFError
        self.write('\n')

    def getkey(self):
        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return sys.stdin.read(1)
        import select
        import termios
        import tty
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            key = os.read(fd, 1)
            while select.select([fd], [], [], 0.05)[0]:     # the rest of an escape sequence
                os.read(fd, 64)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return key

    def readline(self):
        """set /p choice="""
        self.out.flush()
        return input()

    def finish(self):
        if self.ansi:
            self.write('\x1b[0m')
        self.out.flush()


# ----------------------------------------------------------------------------
# Starting other programs

def _which(*names):
    for name in names:
        if name and (os.path.isfile(name) and os.access(name, os.X_OK)):
            return name
        found = name and shutil.which(name)
        if found:
            return found
    return None


def _spawn(argv, cwd=None, wait=False):
    """start ARGV (detached unless WAIT); False if it could not be started"""
    try:
        if wait:
            subprocess.call(argv, cwd=cwd)
        else:
            subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


class Programs:
    """the programs SSP.bat starts.  On Windows the same command lines through
    cmd.exe; elsewhere the nearest native equivalent, or a note why there is
    none"""

    def __init__(self, con, dosbox=None):
        self.con = con
        self.dosbox = dosbox

    def cmd(self, line):
        """a command line of the original, on Windows only"""
        self.con.out.flush()
        subprocess.call(line, shell=True)

    def unavailable(self, what):
        self.con.echo(' %s cannot be started on this system.' % what)

    def edit(self, path):
        """START "" notepad PATH"""
        if WINDOWS:
            self.cmd('START "" notepad %s' % path)
            return
        p = winpath(path)
        if MACOS and _spawn(['open', '-t', p]):
            return
        opener = _which('xdg-open')
        desktop = os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
        if opener and desktop and _spawn([opener, p]):
            return
        editor = os.environ.get('VISUAL') or os.environ.get('EDITOR')
        if editor:
            try:
                subprocess.call(shlex.split(editor) + [p])
                return
            except OSError:
                pass
        if opener and _spawn([opener, p]):
            return
        self.unavailable('A text editor')

    def browse(self, url):
        """START URL"""
        if WINDOWS:
            self.cmd('START %s' % url)
            return
        import webbrowser
        webbrowser.open(url)

    def dosbox_build(self, folder, exe):
        """START "" /d RES\\FOLDER EXE: the bundled DOSBox with its dosbox.conf"""
        if WINDOWS and not self.dosbox:
            self.cmd('START "" /d RES\\%s %s' % (folder, exe))
            return
        d = winpath('RES/' + folder)
        dosbox = _which(self.dosbox, os.environ.get('DOSBOX'), 'dosbox', 'dosbox-staging',
                        'dosbox-x')
        conf = winpath(os.path.join(d, 'dosbox.conf'))
        if not dosbox:
            self.unavailable('DOSBox (set DOSBOX or use --dosbox)')
            self.con.pause()
            return
        if not os.path.isdir(d) or not _spawn([dosbox, '-conf', os.path.basename(conf)], cwd=d):
            self.unavailable(os.path.basename(dosbox))
            self.con.pause()

    def play(self, folder, mp3, title):
        """START "TITLE" /wait /min /d FOLDER madplay.exe MP3"""
        if WINDOWS:
            self.cmd('START "%s" /wait /min /d %s madplay.exe %s' % (title, folder, mp3))
            return
        p = os.path.abspath(winpath(os.path.join(folder, mp3)))
        for argv in (['afplay'], ['mpg123', '-q'], ['ffplay', '-nodisp', '-autoexit',
                                                    '-loglevel', 'quiet'],
                     ['mpv', '--no-video', '--really-quiet'], ['cvlc', '--play-and-exit', '-q']):
            exe = _which(argv[0])
            if exe:
                try:
                    subprocess.call([exe] + argv[1:] + [p], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    continue
                return

    def windows_only(self, line, what):
        """a Windows program (NTVDM modes, installers, setup tools)"""
        if WINDOWS:
            self.cmd(line)
        else:
            self.unavailable(what)
            self.con.pause()


# ----------------------------------------------------------------------------
# SSP.bat

class BatchAbort(Exception):
    """a syntax error, which ends a batch file (and SSP.exe, with exit code 255)"""


def cmd_date_time():
    """%date% %time:~0,5% as cmd.exe shows them (short date, hour padded with a space)"""
    if WINDOWS:
        import ctypes
        buf = ctypes.create_unicode_buffer(80)
        ctypes.windll.kernel32.GetDateFormatW(0x0400, 0, None, None, buf, 80)
        date = buf.value
    else:
        import locale
        try:
            locale.setlocale(locale.LC_TIME, '')
        except locale.Error:
            pass
        date = time.strftime('%x')
    now = time.localtime()
    return '%s %2d:%02d' % (date, now.tm_hour, now.tm_min)


class SSP:
    def __init__(self, con, programs, username, fixes=True):
        self.con = con
        self.run = programs
        self.username = username
        self.fixes = fixes              # False: the original's bugs too (--no-fixes)
        self.show_ntvdm = 0

    # helpers for the script's idioms

    def echo(self, *lines):
        for line in lines:
            self.con.echo(line)

    def flag(self, name):
        return exists('RES/SSP/flags/' + name)

    def choice(self, first):
        """set choice= / set /p choice= / if not "%choice%"=="" set choice=%choice:~0,1%:
        the first character of the answer, after cmd.exe has parsed those lines with the
        answer in them.  FIRST is the key and label of the menu's first
        `if "%choice%"=="key" GOTO label` line.  Fixed: just the first character."""
        line = self.con.readline()
        if self.fixes:
            return line[:1]
        quoted = True                   # inside "%choice%"
        for ch in line:
            if ch == '"':
                quoted = not quoted
            elif not quoted and ch in ' \t,;=':
                raise BatchAbort        # the IF has a stray word: syntax error
        if not quoted or line[:1] in ('"', '<', '>', '|'):
            raise BatchAbort            # unbalanced quotes, or set choice=" < > |
        if line[:1] == '&':
            return ''                   # set choice=& empties it
        if line[:1] == '^':             # set choice=^ swallows the next line
            return 'if "%s"=="%s" GOTO %s' % (line[1:], first[0], first[1])
        return line[:1]

    def invalid(self, choice):
        self.echo('', '"%s" is not a valid choice. Please try again.' % choice)
        self.con.pause()

    def extract(self, archive, dest='RES'):
        """START /d RES 7za.exe x -y ARCHIVE (7za's errors appear and vanish
        in a window of its own)"""
        path = winpath('RES/' + archive)
        if not os.path.isfile(path):
            return
        try:
            SevenZip(path).extract(winpath(dest))
        except (SevenZipError, OSError) as e:
            print('7za: %s: %s' % (archive, e), file=sys.stderr)

    def sed_cyb_cfg(self, digi_list, digi_card, digi_irq):
        """The COPY /A, sed, ATTRIB, COPY /A, ATTRIB +R sequence on RES\\CYB.CFG"""
        path = winpath('RES/CYB.CFG')
        try:
            with open(path, 'rb') as f:
                data = f.read()
        except OSError:
            return
        data = data.split(b'\x1a', 1)[0]            # COPY /A: up to the first Ctrl-Z
        text = data.replace(b'\r\n', b'\n')         # sed 4.2 reads in text mode...
        lines = text.split(b'\n')
        last_nl = text.endswith(b'\n')
        if last_nl:
            lines.pop()
        subs = [(re.compile(br'digi_list.*'), b'digi_list ' + digi_list),
                (re.compile(br'digi_card.*'), b'digi_card ' + digi_card),
                (re.compile(br'digi_irq.*'), b'digi_irq ' + digi_irq)]
        out = []
        for line in lines:
            for rx, rep in subs:
                line = rx.sub(lambda m, rep=rep: rep, line)
            out.append(line)
        result = b'\n'.join(out) + (b'\n' if last_nl else b'')     # ...and writes LF
        set_readonly(path, False)
        try:
            with open(path, 'wb') as f:
                f.write(result + b'\x1a')            # COPY /A adds a Ctrl-Z
        except OSError as e:
            print(e, file=sys.stderr)
        set_readonly(path, True)

    # the script

    def main(self):
        con = self.con
        con.chcp850()
        con.color()
        con.mode()
        con.title('SYSTEMSHOCK-Portable %s%s%s' % (SSPVER, ' ' * 53, cmd_date_time()))
        # Delete the CYB.CFG clones that cdshock produces when CYB.CFG is write protected
        res = winpath('RES')
        try:
            for name in os.listdir(res):
                if re.match(r'(?i)^AA.{0,4}\.TMP$', name):
                    delete(os.path.join('RES', name))
        except OSError:
            pass
        label = 'SPLASH'
        while label != 'EOF':
            label = getattr(self, label)()

    def SPLASH(self):
        self.echo(
            '',
            '  MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM',
            '  MP""""""`MMM""MMMM""MMP""""""`MMM""""""""MMM""""""""`MM"""""`\'"""`YM',
            '  M  mmmmm..MM. `MM\' .MM  mmmmm..MMmmm  mmmMMM  mmmmmmmMM  mm.  mm.  M',
            '  M.      `YMMM.    .MMM.      `YMMMMM  MMMMM`      MMMMM  MMM  MMM  M',
            '  MMMMMMM.  MMMMb  dMMMMMMMMMM.  MMMMM  MMMMMM  MMMMMMMMM  MMM  MMM  M',
            '  M. .MMM\'  MMMMM  MMMMM. .MMM\'  MMMMM  MMMMMM  MMMMMMMMM  MMM  MMM  M',
            '  Mb.     .dMMMMM  MMMMMb.     .dMMMMM  MMMMMM        .MM  MMM  MMM  M',
            '  MP""""""`MMM""MMMMM""MMMMP"""""YMMMM\'""""\'YMMM""MMMMM""MMMMMMMMMMMMM',
            '  M  mmmmm..MM  MMMMM  MMM\' .mmm. `MM\' .mmm. `MM  MMMM\' .MMMMMMMMMMMMM',
            '  M.      `YMM         `MM  MMMMM  MM  MMMMMooMM       .MMMMMMMMMMMMMM',
            '  MMMMMMM.  MM  MMMMM  MMM  MMMMM  MM  MMMMMMMMM  MMMb. YMMMMMMMMMMMMM',
            '  M. .MMM\'  MM  MMMMM  MMM. `MMM\' .MM. `MMM\' .MM  MMMMb  MMMMMMMMMMMMM',
            '  Mb.     .dMM  MMMMM  MMMMb     dMMMM.     .dMM  MMMMM  MMMMMMMMMMMMM',
            '  MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM',
            '  MM"""""""`YM                    dP           dP       dP          MM',
            '  MM  mmmmm  M                    88           88       88          MM',
            '  M\'        .M .d8888b. 88d888b.d8888P.d8888b. 88d888b. 88 .d8888b. MM',
            '  MM  MMMMMMMM 88\'  `88 88\'  `88  88  88\'  `88 88\'  `88 88 88ooood8 MM',
            '  MM  MMMMMMMM 88.  .88 88        88  88.  .88 88.  .88 88 88.  ... MM',
            '  MM  MMMMMMMM `88888P\' dP        dP  `88888P8 88Y8888\' dP `88888P\' MM',
            '  MMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMMM')
        # Let's check for NTVDM
        windir = os.environ.get('windir', '')
        if os.path.exists(windir + '/system32/NTVDM.exe'):
            self.show_ntvdm = 1
            self.con.title('SYSTEMSHOCK-Portable %s on NTVDM enabled system' % SSPVER)
            self.echo('', '  Welcome back, %s. NTVDM was detected on this system. ' % self.username,
                      '')
        else:
            self.con.title('SYSTEMSHOCK-Portable %s on DOSbox' % SSPVER)
            self.echo('', '  Welcome back, %s. SHODAN is waiting for you.' % self.username, '')
        self.con.pause()
        return 'MAIN'

    def MAIN(self):
        self.con.cls()
        self.con.color()
        self.echo('', '', '           Main Menu', '', '')
        if self.show_ntvdm >= 1:
            self.echo(' d: Start SSP with DGVESA ')
            # Mouselook and Mouse2kv are incompatible
            if not self.flag('mouselook_enabled'):
                self.echo(' k: Start SSP with Mouse2kv')
        if self.flag('dosbox_enabled'):
            self.echo(' b: Start SSP in the Official DOSbox ')
        if self.flag('gulikoza_enabled'):
            self.echo(" b: Start SSP in Gulikoza's DOSbox build ")
        if self.username == 'Kolya':
            self.echo(' p: DOS command reference ')
        self.echo(' o: Options', ' i: Information', ' q: Quit', '')
        c = self.choice(('d', 'VESA'))
        go = {'d': 'VESA', 'k': 'MOUSE2KV', 'b': 'DOSBOX', 'p': 'DOSCMD', 'o': 'OPTIONS',
              'i': 'INFO', 'q': 'EOF'}
        if c in go:
            return go[c]
        self.invalid(c)
        return 'MAIN'

    def VESA(self):
        self.run.windows_only('START "" /d RES vesa.pif', 'DGVESA mode (vesa.pif, NTVDM)')
        if self.flag('affinity_1'):
            self.run.windows_only('START "" /d RES affinity.exe -a ntvdm.exe 01', 'affinity.exe')
        return 'EOF'

    def MOUSE2KV(self):
        # Using SED to set some values in CYB.CFG
        vdms = os.path.exists(os.environ.get('VDMSPath', '') + '/dosdrv.exe')
        if vdms:
            if self.flag('auto_cyb'):
                self.sed_cyb_cfg(b'3', b'3', b'-1')
            self.run.windows_only('dosdrv.exe "-i:./RES/vdms.ini" >nul', 'VDMSound')
        elif self.flag('auto_cyb'):
            self.sed_cyb_cfg(b'10', b'1', b'-1')
        # CD RES
        for res, args in (('640x480', '640 480'), ('800x600', '800 600'),
                          ('1024x768', '1024 768'), ('mouselook_enabled', '640 480')):
            if self.flag(res):
                self.run.windows_only('cd RES && MOUSE2KV.exe %s 8 8 cdshock.exe' % args,
                                      'Mouse2kv mode (Mouse2kv.exe, NTVDM)')
        # still relative to RES: never there
        if exists('RES/RES/SSP/flags/affinity_1'):
            self.run.windows_only('START "" /d RES\\RES affinity.exe -a ntvdm.exe 01',
                                  'affinity.exe')
        return 'EOF'

    def DOSBOX(self):
        # Using SED to set some digi sound values in CYB.CFG for dosbox
        if self.flag('auto_cyb'):
            self.sed_cyb_cfg(b'0', b'3', b'7')
        # And which dosbox should we use?
        if self.flag('dosbox_enabled'):
            self.run.dosbox_build('dosbox', 'dosbox.exe')
        if self.flag('gulikoza_enabled'):
            self.run.dosbox_build('gulikoza', 'dosbox.exe')
        return 'EOF'

    def DOSCMD(self):
        # Show me your commands, baby
        windir = os.environ.get('windir', '')
        self.run.windows_only('%s\\hh.exe ms-its:c:\\Windows\\Help\\ntcmds.chm::/ntcmds.htm'
                              % windir, 'The Windows command reference (hh.exe)')
        return 'EOF'

    def OPTIONS(self):
        self.con.cls()
        self.con.color()
        self.echo('', '           Options', '', '')
        if self.flag('mouselook_enabled'):
            self.echo(" e: Disable Malba Tahan's mouselook mod")
        else:
            self.echo(" e: Enable Malba Tahan's mouselook mod")
        if self.flag('enhanced_text_enabled'):
            self.echo(" t: Disable Gigaquad's true2speech text mod")
        else:
            self.echo(" t: Enable Gigaquad's true2speech text mod")
        if self.flag('scaled_object_textures_enabled'):
            self.echo(" p: Disable Gigaquad's scaled object textures mod")
        else:
            self.echo(" p: Enable Gigaquad's scaled object textures mod")
        if self.flag('gulikoza_enabled'):
            self.echo(' b: Use Official DOSbox build')
        else:
            self.echo(" b: Use Gulikoza's custom DOSbox build")
        vdms = os.path.exists(os.environ.get('VDMSPath', '') + '/dosdrv.exe')
        if self.show_ntvdm >= 1:
            if vdms:
                self.echo(' u: VDMSound is installed. SFX will be stereo.')
            else:
                self.echo(' u: Install VDMSound')
        if self.show_ntvdm >= 1:
            self.echo(' v: Change DGVESA-settings (Check "Platform: DOS" on the pop-up)')
            if self.flag('affinity_1'):
                self.echo(' a: Run NTVDM process affinity at system default')
            else:
                self.echo(' a: Limit NTVDM process affinity to the 1st CPU')
        if not self.flag('mouselook_enabled'):
            if not self.flag('800x600'):
                self.echo(' 8: Enable 800x600 resolution')
            if not self.flag('1024x768'):
                self.echo(' 1: Enable 1024x768 resolution')
            if not self.flag('640x480'):
                self.echo(' 6: Restore 640x480 resolution')
        self.echo(' c: Config edit menu')
        if self.show_ntvdm <= 0:
            self.echo(' d: Disregard determined OS')
        if self.show_ntvdm == 2:
            self.echo(' d: Heed determined OS')
        self.echo(' m: Main menu', ' i: Information', ' q: Quit', '')
        c = self.choice(('e', 'XDSHOCK'))
        go = {'e': 'XDSHOCK', 't': 'ENHANCEDTEXT', 'p': 'SCALEDTEXTURES', 'b': 'GULIKOZA',
              'u': 'VDMS', 'v': 'VESASET', 'a': 'AFFINITY', '8': 'R800x600', '1': 'R1024x768',
              '6': 'R640x480', 'c': 'CFGEDIT', 'd': 'FORCESHOWNTVDM', 'm': 'MAIN', 'i': 'INFO',
              'q': 'EOF'}
        if c in go:
            return go[c]
        self.invalid(c)
        return 'OPTIONS'

    def XDSHOCK(self):
        # Toggle mouselook mod
        if self.flag('mouselook_enabled'):
            delete('RES/SSP/flags/mouselook_enabled')
            delete('RES/dos4gw.exe')
            # the original names SSP/mods/SSP/mods/640x480.7z, which is not there: the mouselook
            # CDSHOCK.EXE stays, without the dos4gw.exe it needs
            self.extract('SSP/mods/640x480.7z' if self.fixes else 'SSP/mods/SSP/mods/640x480.7z')
            append_flag('RES/SSP/flags/640x480')
            self.con.cls()
            self.echo('', ' Mouselook mod was disabled.', ' Resolution has been reset to 640x480.',
                      '')
        else:
            for res in ('1024x768', '800x600', '640x480'):
                if self.flag(res):
                    delete('RES/SSP/flags/' + res)
            append_flag('RES/SSP/flags/mouselook_enabled')
            self.extract('SSP/mods/xcdshock.7z')
            self.con.cls()
            self.echo('', ' Mouselook mod has been enabled.',
                      " Press 'e' in game to use mouselook.",
                      '', ' Higher resolutions are also set in game by pressing:',
                      ' ESC - Options - Video - Video Mode ', '',
                      ' Note that Mouse2kv mode is incompatible with Mouselook mod and ',
                      ' therefor will not be available.', '')
        self.con.pause()
        return 'OPTIONS'

    def ENHANCEDTEXT(self):
        # Toggle enhanced text mod
        if self.flag('enhanced_text_enabled'):
            delete('RES/SSP/flags/enhanced_text_enabled')
            self.extract('SSP/mods/text_original.7z')
            self.con.cls()
            self.echo('', ' Original log file texts have been restored.', '')
        else:
            append_flag('RES/SSP/flags/enhanced_text_enabled')
            self.extract('SSP/mods/text_enhanced.7z')
            self.con.cls()
            self.echo('', " Gigaquad's enhanced text mod has been enabled.",
                      ' Log file texts will be true to the speech heard.', '')
        self.con.pause()
        return 'OPTIONS'

    def SCALEDTEXTURES(self):
        # Toggle scaled up object textures
        if self.flag('scaled_object_textures_enabled'):
            delete('RES/SSP/flags/scaled_object_textures_enabled')
            # CITMAT.7z has CITMAT.RES at its top: the original unpacks it into RES, beside the
            # DATA folder where the scaled one stays
            self.extract('SSP/mods/citmat.7z', 'RES/DATA' if self.fixes else 'RES')
            self.con.cls()
            self.echo('', ' Original object textures have been restored.', '')
        else:
            append_flag('RES/SSP/flags/scaled_object_textures_enabled')
            self.extract('SSP/mods/citmat_scaled.7z')
            self.con.cls()
            self.echo('', " Gigaquad's scaled up object textures mod has been enabled.", '')
        self.con.pause()
        return 'OPTIONS'

    def GULIKOZA(self):
        # Toggle official/gulikoza dosbox
        if self.flag('gulikoza_enabled'):
            delete('RES/SSP/flags/gulikoza_enabled')
            append_flag('RES/SSP/flags/dosbox_enabled')
            self.con.cls()
            self.echo('', ' Official DOSbox version will be used.', '')
        else:
            delete('RES/SSP/flags/dosbox_enabled')
            append_flag('RES/SSP/flags/gulikoza_enabled')
            self.con.cls()
            self.echo('', " Gulikoza's custom DOSbox build will be used.", '')
        self.con.pause()
        return 'OPTIONS'

    def VDMS(self):
        # Yay! VDMSound is already installed.
        self.con.cls()
        self.echo('', ' VDMSound allows stereo sound effects in DGVESA & Mouse2kv modes.')
        if os.path.exists(os.environ.get('VDMSPath', '') + '/dosdrv.exe'):
            self.echo(' VDMSound was detected on the system. SFX will be stereo.', '')
            self.con.pause()
            return 'OPTIONS'
        return 'NOVDMS'

    def NOVDMS(self):
        # If there's no VDMSound, offer to install it
        self.con.cls()
        self.echo('', ' VDMSound was NOT found on the system. SFX will be mono. ',
                  ' If you just installed VDMSound, please reboot.',
                  ' Do not install on Windows NT.  ', '', ' i: Install VDMSound now.',
                  ' Any other key: Go back to the options menu.', '')
        if self.choice(('i', 'VDMSINST')) == 'i':
            return 'VDMSINST'
        return 'OPTIONS'

    def VDMSINST(self):
        self.run.windows_only('START "" /d RES VDMSound2.1.0.exe', 'The VDMSound installer')
        return 'EOF'

    def AFFINITY(self):
        # Toggle affinity mask for NTVDM.exe (just a flag checked at runtime)
        if self.flag('affinity_1'):
            delete('RES/SSP/flags/affinity_1')
            self.con.cls()
            self.echo('', ' NTVDM process affinity mask has been restored to system default.  ', '')
        else:
            append_flag('RES/SSP/flags/affinity_1')
            self.con.cls()
            self.echo('', ' NTVDM process affinity mask has been set to the first processor.', '')
        self.con.pause()
        return 'OPTIONS'

    def VESASET(self):
        # Change some VESA settings
        self.run.windows_only('START "" /d RES dgVoodooSetup.exe', 'dgVoodooSetup.exe')
        return 'OPTIONS'

    def _resolution(self, res, others, message):
        self.extract('SSP/mods/%s.7z' % res)
        for name in ('mouselook_enabled',) + others:
            if self.flag(name):
                delete('RES/SSP/flags/' + name)
        append_flag('RES/SSP/flags/' + res)
        self.con.cls()
        self.echo('', message, '')
        self.con.pause()
        return 'OPTIONS'

    def R800x600(self):
        return self._resolution('800x600', ('1024x768', '640x480'), ' 800x600 resolution set.')

    def R1024x768(self):
        return self._resolution('1024x768', ('800x600', '640x480'), ' 1024x768 resolution set.')

    def R640x480(self):
        return self._resolution('640x480', ('800x600', '1024x768'),
                                ' Original 640x480 resolution reset.')

    def CFGEDIT(self):
        # Edit config files or run the original installer
        self.con.cls()
        self.echo('', '', '           Config Edit Menu', '  ', '')
        if self.flag('mouselook_enabled'):
            self.echo(' e: Edit XCYB.CFG (mouselook mod settings & key binds) ')
        if self.flag('dosbox_enabled'):
            self.echo(' b: Edit official dosbox.conf ')
        if self.flag('gulikoza_enabled'):
            self.echo(' b: Edit Gulikoza dosbox.conf ')
        self.echo(' c: Edit CYB.CFG', ' i: Original installer', ' m: Main menu', ' o: Options',
                  ' q: Quit', '')
        c = self.choice(('e', 'EDITXCYBCFG'))
        go = {'e': 'EDITXCYBCFG', 'b': 'EDITDOSBOXCONF', 'c': 'EDITCYBCFG', 'i': 'ORIINST',
              'm': 'MAIN', 'o': 'OPTIONS', 'q': 'EOF'}
        if c in go:
            return go[c]
        self.invalid(c)
        return 'CFGEDIT'

    def EDITXCYBCFG(self):
        self.run.edit('RES/XCYB.cfg')
        return 'CFGEDIT'

    def EDITDOSBOXCONF(self):
        # Which dosbox will it be?
        if self.flag('dosbox_enabled'):
            self.run.edit('RES/dosbox/dosbox.conf')
        if self.flag('gulikoza_enabled'):
            self.run.edit('RES/gulikoza/dosbox.conf')
        return 'CFGEDIT'

    def EDITCYBCFG(self):
        self.con.cls()
        self.echo('')
        if self.flag('auto_cyb'):
            self.echo(' Please note that SSP writes a few audio settings (digi_list,',
                      ' digi_irq, digi_card) to CYB.CFG during game startup that ',
                      ' depend on whether VDMSound is installed and how the game is',
                      ' started (DGVESA, Mouse2kv, DOSbox).',
                      " You can disable SSP's automatic settings below. (Not recommended.)")
        else:
            self.echo(" SSP's automatic audio settings are disabled. ")
        self.echo('', ' CYB.CFG is usually write protected to save the language setting ',
                  ' which the game otherwise resets to English. ', '',
                  ' r: remove write protection', ' e: edit CYB.CFG', ' s: set write protection')
        if self.flag('auto_cyb'):
            self.echo(" x: Disable SSP's automatic settings")
        else:
            self.echo(" x: Enable SSP's automatic settings and reset CYB.CFG ")
        self.echo(' m: Main menu', ' o: Options', ' c: Config edit menu', ' q: Quit', '')
        c = self.choice(('r', 'UNPRTCYBCFG'))
        go = {'r': 'UNPRTCYBCFG', 's': 'WPRTCYBCFG', 'e': 'EDCYBCFG', 'x': 'AUTOCYB', 'm': 'MAIN',
              'o': 'OPTIONS', 'c': 'CFGEDIT', 'q': 'EOF'}
        if c in go:
            return go[c]
        self.invalid(c)
        if self.fixes:
            return 'EDITCYBCFG'
        return 'UNPRTCYBCFG'        # no GOTO after the PAUSE: on into :UNPRTCYBCFG

    def UNPRTCYBCFG(self):
        set_readonly('RES/CYB.CFG', False)
        self.con.cls()
        self.echo('', ' CYB.CFG is writable now.', '')
        self.con.pause()
        return 'EDITCYBCFG'

    def WPRTCYBCFG(self):
        set_readonly('RES/CYB.CFG', True)
        self.con.cls()
        self.echo('', ' CYB.CFG is write protected now.', '')
        self.con.pause()
        return 'EDITCYBCFG'

    def EDCYBCFG(self):
        self.run.edit('RES/CYB.cfg')
        return 'EDITCYBCFG'

    def AUTOCYB(self):
        self.con.cls()
        if self.flag('auto_cyb'):
            delete('RES/SSP/flags/auto_cyb')
            self.echo('', " SSP will not make automatic adjustments to CYB.CFG any more.  ", '')
        else:
            self.extract('SSP/mods/DEFAULT.CYB.CFG.7z')
            append_flag('RES/SSP/flags/auto_cyb')
            self.echo('', ' CYB.CFG has been reset.',
                      ' SSP will make automatic adjustments for best performance.', '')
        self.con.pause()
        return 'EDITCYBCFG'

    def ORIINST(self):
        # By rare request... :/
        self.con.cls()
        self.echo('', ' The original installer is provided here so you can create ',
                  ' your own CYB.CFG file and compare e.g. the sound settings ',
                  ' with the ones used in SSP.',
                  ' For the installer to run it needs to be in a DOS compatible',
                  ' path. If the installer doesn\'t run now, copy the folder "INST"',
                  ' from SHOCK/RES/INST to C:/INST and run INSTALL.EXE there.',
                  ' Note that the sound tests will not work.', '  ')
        self.con.pause()
        self.run.windows_only('START "" RES/INST/INSTALL.EXE', 'The DOS installer INSTALL.EXE')
        return 'CFGEDIT'

    def FORCESHOWNTVDM(self):
        # You don't have to trust me, feel free to see all the options that are useless to you!
        win_name = os.environ.get('win_name', '')
        if self.show_ntvdm <= 0:
            self.show_ntvdm = 2
            self.con.title('SYSTEMSHOCK-Portable %s, forced disregarding OS' % SSPVER)
            self.con.cls()
            self.echo('', ' Some game modes (DGVESA & Mouse2kv) require the',
                      ' Windows NT Virtual DOS machine (NTVDM) to run.',
                      ' These game modes are now available in the main menu.', '',
                      ' Note that your OS (%s) does not have the NTVDM' % win_name,
                      ' and the game will not run in these modes on your system. ', '')
            self.con.pause()
            return 'OPTIONS'
        if self.show_ntvdm == 2:
            self.show_ntvdm = 0
            self.con.title('SYSTEMSHOCK-Portable on %s' % win_name)
            self.con.cls()
            self.echo('', ' Incompatible game modes hidden.', '')
            self.con.pause()
            return 'OPTIONS'
        return 'INFO'               # on into :INFO

    def INFO(self):
        self.con.cls()
        self.echo('', '', '           Info Menu', '', '',
                  ' z: Game start help', ' c: Game controls', ' l: I cannot beat the final boss!',
                  " x: About SSP's startup modes", ' r: About resolution settings',
                  ' w: Running the game in a window', ' v: Screenshots and videos')
        if self.show_ntvdm >= 1:
            self.echo(' u: About VDMSound ')
        self.echo(' f: Playing in French or German',
                  ' s: Visit Systemshock.org for updates and French/German support.',
                  ' a: Cast SHODAN.', ' m: Main menu', ' o: Options', ' q: Quit', '')
        c = self.choice(('z', 'SINFO'))
        go = {'z': 'SINFO', 'c': 'CONTROLSINFO', 'l': 'WINFO', 'x': 'MODESINFO', 'r': 'RESINFO',
              'w': 'WINDOWEDINFO', 'v': 'SHOTSINFO', 'u': 'VDMSINFO', 'f': 'FRENGERINFO',
              's': 'SMA', 'a': 'HACKER', 'm': 'MAIN', 'o': 'OPTIONS', 'q': 'EOF'}
        if c in go:
            return go[c]
        self.invalid(c)
        return 'INFO'

    def _page(self, *lines):
        self.con.cls()
        self.echo('', *lines)
        self.echo('')
        self.con.pause()
        return 'INFO'

    def SINFO(self):
        return self._page(
            ' Due to different resolutions the cursor might move quite fast ',
            " on the game's start menu screen and the gameplay options screen.", '',
            ' After choosing your name and gameplay options, the game begins ',
            ' with an interface-help screen. When you\'re ready, hit SPACE to ', ' continue.', '',
            ' In the game hit the ESC-key and click Options - Video - Video Mode. ',
            ' Choose your resolution. To change the interface to fullscreen mode ',
            ' click on the square button on the left upper side. ', '',
            ' Finally press ESC again to find the save game menu. ',
            ' Saving the game also saves the settings. ')

    def CONTROLSINFO(self):
        return self._page(
            ' Read the included SSReferenceCard.pdf to learn the controls.',
            ' Keybinds and mouse sensitivity can be changed after enabling ',
            " Malba's mouselook mod in the Options menu. ",
            ' Next choose the Config edit menu and edit XCYB.CFG. ')

    def WINFO(self):
        self.con.cls()
        self.echo('', ' Keep shooting even when she has filled the screen. ',
                  ' Use the Recall-Software. (Tip by kodan50)',
                  ' If none of that helps, there is a processor slow-down program',
                  ' included (in RES/Speedset). Do you want to start this program now?', '', ' y/n')
        if self.choice(('y', 'SPEEDSET')) == 'y':
            return 'SPEEDSET'
        return 'INFO'

    def SPEEDSET(self):
        self.con.cls()
        if WINDOWS:
            self.run.cmd('START "Speedset" /d RES\\Speedset cmd /K speedset.exe')
        else:
            self.run.unavailable('Speedset (a Windows program)')
        self.echo('', ' To set your processor speed, in the window that just popped up type:',
                  ' speedset speed ',
                  ' ...where speed is a number between 100.0 (fastest) and -100.0 ', ' (slowest).',
                  ' Leave the Speedset window open, start the game and load your save ',
                  " game. If you want to disable Speedset, type EXIT in it's window.", '')
        self.con.pause()
        return 'MAIN'

    def MODESINFO(self):
        return self._page(
            ' There are 3 modes to start SYSTEMSHOCK-Portable. ',
            ' Depending on your operating system and game modifications not all ',
            ' modes may be available.', '',
            ' 1. DGVESA emulates the grafic mode: VESA BIOS Extensions 2.0.',
            ' This mode requires the NT Virtual DOS Machine (NTVDM) available',
            ' only on Windows XP, Windows 2000, Windows NT, Windows Server 2003.', '',
            ' 2. Mouse2kv mode leaves VESA up to your hardware and only ',
            ' adjusts mouse speed. It requires the NTVDM as well. ',
            ' It is incompatible with the Mouselook mod and therefor will not show',
            ' in the main menu when Mouselook mod is enabled in the Options menu.', '',
            ' 3. DOSbox emulates a DOS environment. It is the only way to run',
            ' the game on later Windows versions like Vista and Windows 7. ',
            ' There are two versions of DOSbox available: The official build and ',
            " Gulikoza's custom build.",
            ' When finished playing leave DOSbox by typing "exit".')

    def RESINFO(self):
        return self._page(
            ' If you are playing with Malba Tahan\'s mouselook mod enabled, all',
            ' available resolutions can be set in the game by pressing ESC then ',
            ' clicking: Options - Video - Video Mode.', ' ',
            ' Without this mod you have to enable your preferred resolution from',
            ' the Options menu first and then set it in game as described above.')

    def WINDOWEDINFO(self):
        lines = []
        if self.show_ntvdm >= 1:
            lines += [' To run the game in a window in DGVESA mode open the DGVESA ',
                      ' configuration from the Options menu. ',
                      ' Choose "Platform: DOS" on the popup. On the Global tab, change the ',
                      ' screen mode to "Windowed mode".']
        lines += [' To run the game in a window in DOSbox mode go to the Options menu, ',
                  ' then choose the Config edit menu and edit the file dosbox.conf from',
                  ' there. Change the line "fullscreen=true" to "fullscreen=false".']
        return self._page(*lines)

    def SHOTSINFO(self):
        lines = []
        if self.show_ntvdm >= 1:
            lines += [' The native screenshot function only works in Mouse2kv mode.',
                      ' Hit the [Prt Scrn] key. A message will appear onscreen saying ',
                      ' "SHOCKxxx.GIF SAVED" where x is the number of the screenshot. ',
                      ' You can find these screenshots in SHOCK/RES/GEN.', '']
        lines += [' In DOSbox you can record videos. To start recording press CTRL-ALT-F5.',
                  ' Press CTRL-ALT-F5 again to stop. You can find the videos in ',
                  ' SHOCK/RES/GEN. You may need to install the zmbv-codec to play them. ',
                  ' Go to SHOCK/GEN/zmbv_codec, rightclick zmbv.inf and choose install.']
        return self._page(*lines)

    def VDMSINFO(self):
        return self._page(
            ' VDMSound is a DOS sound emulation software. It is not necessary to ',
            ' install VDMSound to play, but if you run System Shock outside of a ',
            ' DOSbox emulation, you will get stereo SFX and an overall better sound ',
            ' quality with it. If you don\'t have VDMSound installed but could use ',
            ' it on your system you will see according info in the Options menu and',
            ' can install VDMSound from there.', '',
            ' Please install VDMSound while logged into the same Windows account ',
            ' you want to play SSP in. After the installation reboot your system. ',
            ' Note that VDMSound has been integrated in DOSbox, so installing it ',
            ' when you run SSP in DOSbox, will do nothing.')

    def FRENGERINFO(self):
        return self._page(
            ' System Shock was originally released trilingual but the German and ',
            ' French files have been stripped from SSP to make it smaller. ',
            ' You can download the language files at Systemshock.org. ')

    def SMA(self):
        self.run.browse('http://www.systemshock.org/index.php?topic=211.0')
        return 'INFO'

    def HACKER(self):
        self.run.play('RES\\SSP\\snd', 'test.mp3', 'Look at you %s!' % self.username)
        return 'INFO'


# ----------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='ssp.py',
        description='SYSTEMSHOCK-Portable %s launcher (a port of SSP.exe)' % SSPVER)
    ap.add_argument('-C', '--directory', metavar='DIR',
                    help='the SSP folder, the one holding RES (default: this script\'s folder)')
    ap.add_argument('--dosbox', metavar='PATH',
                    help='DOSBox to start the game with (default: on Windows the bundled build, '
                         'elsewhere $DOSBOX or dosbox, dosbox-staging, dosbox-x on the PATH)')
    ap.add_argument('--no-fixes', action='store_true',
                    help='keep the original\'s bugs (see README.md)')
    ap.add_argument('--extract', nargs=2, metavar=('ARCHIVE', 'DIR'),
                    help='just extract a 7z archive into DIR the way SSP does, and exit')
    ap.add_argument('--version', action='version', version='%(prog)s ' + __version__)
    args = ap.parse_args(argv)

    if args.extract:
        try:
            SevenZip(args.extract[0]).extract(args.extract[1])
        except (SevenZipError, OSError) as e:
            print('ssp.py: %s' % e, file=sys.stderr)
            return 1
        return 0

    folder = args.directory or os.path.dirname(os.path.abspath(__file__))
    try:
        os.chdir(folder)
    except OSError as e:
        print('ssp.py: %s' % e, file=sys.stderr)
        return 1
    username = os.environ.get('USERNAME' if WINDOWS else 'USER') or getpass.getuser()
    con = Console()
    try:
        SSP(con, Programs(con, args.dosbox), username, fixes=not args.no_fixes).main()
    except BatchAbort:
        return 255
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        con.finish()
    return 0


if __name__ == '__main__':
    sys.exit(main())
