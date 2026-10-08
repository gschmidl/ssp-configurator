"""The key sequences the comparison tests type, and the scratch SSP folders they run in."""
import hashlib
import os
import shutil
import stat

FLAGS = ('auto_cyb', 'enhanced_text_enabled', 'gulikoza_enabled', 'mouselook_enabled',
         'scaled_object_textures_enabled')

# (name, flags to remove before, keys).  Each key string is sent once the screen is quiet.
# None of them starts another program: no DOSBox, editor, browser, sound or installer.
P = ' '         # a key for PAUSE
SCENARIOS = [
    ('menus', (), ['\r', 'x\r', P, 'o\r', 'z\r', P, 'i\r', 'z\r', P, 'c\r', P, 'x\r', P, 'r\r', P,
                   'w\r', P, 'v\r', P, 'u\r', P, 'f\r', P, '?\r', P, 'l\r', 'n\r', 'm\r', 'q\r']),
    ('toggles', (), [P, 'o\r', 'e\r', P, 'e\r', P, 't\r', P, 't\r', P, 'p\r', P, 'p\r', P,
                     'b\r', P, 'b\r', P, 'a\r', P, 'a\r', P, 'e\r', P, '8\r', P, '1\r', P,
                     '6\r', P, 'q\r']),
    ('cyb', (), [P, 'o\r', 'c\r', 'z\r', P, 'c\r', 'r\r', P, 's\r', P, 'x\r', P, 'x\r', P,
                 'z\r', P, P, 'c\r', 'm\r', 'q\r']),
    ('ntvdm', (), [P, 'o\r', 'd\r', P, 'm\r', 'i\r', 'u\r', P, 'w\r', P, 'v\r', P, 'o\r', 'u\r',
                   '\r', 'd\r', P, 'q\r']),
    ('ntvdm-k', ('mouselook_enabled',), [P, 'o\r', 'd\r', P, 'm\r', 'q\r']),
    ('dosbox-sed', ('gulikoza_enabled',), [P, 'b\r']),
    ('mouse2kv-sed', ('mouselook_enabled',), [P, 'k\r']),
    ('no-flags', FLAGS, [P, 'o\r', 'c\r', 'b\r', 'c\r', 'x\r', P, 'm\r', 'q\r']),
    # a caret answer swallows each menu's first `if` line
    ('caret', (), [P, 'o\r', '^\r', P, 'c\r', '^\r', P, 'c\r', '^\r', P, P, 'm\r', 'i\r', '^\r',
                   P, 'l\r', '^\r', 'o\r', 'u\r', '^\r', 'q\r']),
] + [('input %r' % s, (), [P, s + '\r', P, 'q\r'])
     for s in ('"', '&', '>', '<', '|', '^', ' x', '%', ')', '(', '\xe4', 'D', '', 'qq',
               'ab"c"', 'a""', '""', 'a"b"c"', '>a', 'o"', '^x', 'a b"c d"', 'a|b', '&q', '!',
               '!o')]


def make_copy(src, dest, remove=()):
    """a scratch SSP folder at DEST: the small files of SRC's RES, the DATA files the mods
    replace, minus the flags REMOVE, plus a CYB.CFG clone for the start-up clean-up"""
    res, out = os.path.join(src, 'RES'), os.path.join(dest, 'RES')
    os.makedirs(os.path.join(out, 'DATA'))
    for name in os.listdir(res):
        p = os.path.join(res, name)
        if os.path.isfile(p) and os.path.getsize(p) < 2000000:
            shutil.copy2(p, out)
    for name in ('SED', 'SSP', 'SB16', 'SC55'):
        shutil.copytree(os.path.join(res, name), os.path.join(out, name))
    for name in ('CYBSTRNG.RES', 'FRNSTRNG.RES', 'GERSTRNG.RES', 'CITMAT.RES'):
        shutil.copy2(os.path.join(res, 'DATA', name), os.path.join(out, 'DATA'))
    for name in remove:
        os.remove(os.path.join(out, 'SSP', 'flags', name))
    with open(os.path.join(out, 'AA1234.TMP'), 'w') as f:
        f.write('clone')


def tree(d, start):
    """{relative path: (size, sha1, read-only, 'new' or modification time in ns)}"""
    out = {}
    for dp, dns, fns in os.walk(d):
        for n in fns:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, d).replace(os.sep, '/')
            if rel == 'SSP.exe':
                continue
            st = os.stat(p)
            with open(p, 'rb') as f:
                body = f.read()
            when = 'new' if st.st_mtime >= start - 2 else st.st_mtime_ns
            out[rel] = [len(body), hashlib.sha1(body).hexdigest(), not os.access(p, os.W_OK), when]
    return out


def unlock(d):
    for dp, dns, fns in os.walk(d):
        for n in fns:
            p = os.path.join(dp, n)
            os.chmod(p, stat.S_IMODE(os.stat(p).st_mode) | stat.S_IWRITE)


def remove(d):
    if os.path.exists(d):
        unlock(d)
        shutil.rmtree(d)
