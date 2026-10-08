"""What a terminal shows after a stream of text and escape sequences (enough for SSP)."""
import re


def screen_rows(raw, cols=80, rows=25):
    """the rows a terminal shows after RAW (CSI H f A-D G d J K X, CSI 8;rows;cols t;
    CR LF BS)"""
    cells = [[' '] * cols for _ in range(rows)]
    r = c = 0
    i = 0
    while i < len(raw):
        m = re.match(r'\x1b\[([?]?)([0-9;]*)[ -/]*([@-~])', raw[i:])
        if m:
            i += m.end()
            if m.group(1):
                continue
            ps = [int(p) if p else 0 for p in m.group(2).split(';')] if m.group(2) else []
            n = ps[0] if ps and ps[0] else 1
            f = m.group(3)
            if f == 't' and len(ps) == 3 and ps[0] == 8:
                rows, cols = ps[1], ps[2]
                cells = [[' '] * cols for _ in range(rows)]
                r = c = 0
            elif f in 'Hf':
                r = min((ps[0] if ps and ps[0] else 1) - 1, rows - 1)
                c = min((ps[1] if len(ps) > 1 and ps[1] else 1) - 1, cols - 1)
            elif f == 'A':
                r = max(0, r - n)
            elif f == 'B':
                r = min(rows - 1, r + n)
            elif f == 'C':
                c = min(cols - 1, c + n)
            elif f == 'D':
                c = max(0, c - n)
            elif f == 'G':
                c = min(n - 1, cols - 1)
            elif f == 'd':
                r = min(n - 1, rows - 1)
            elif f == 'J' and (ps[0] if ps else 0) in (2, 3):
                cells = [[' '] * cols for _ in range(rows)]
            elif f == 'J':
                cells[r][c:] = [' '] * (cols - c)
                for k in range(r + 1, rows):
                    cells[k] = [' '] * cols
            elif f == 'K':
                cells[r][c:] = [' '] * (cols - c)
            elif f == 'X':
                cells[r][c:c + n] = [' '] * len(cells[r][c:c + n])
            continue
        m = re.match(r'\x1b\][^\x07\x1b]*(\x07|\x1b\\)', raw[i:])
        if m:
            i += m.end()
            continue
        ch = raw[i]
        i += 1
        if ch == '\r':
            c = 0
        elif ch == '\n':
            if r == rows - 1:
                cells = cells[1:] + [[' '] * cols]
            else:
                r += 1
        elif ch == '\b':
            c = max(0, c - 1)
        elif ch >= ' ' and ch != '\x7f':
            if c >= cols:
                c = 0
                if r == rows - 1:
                    cells = cells[1:] + [[' '] * cols]
                else:
                    r += 1
            cells[r][c] = ch
            c += 1
    return [''.join(row).rstrip() for row in cells]


def squeezed(raw):
    t = re.sub(r'\x1b\][^\x07\x1b]*(\x07|\x1b\\)', '', raw)
    t = re.sub(r'\x1b\[[0-9;?]*[ -/]*[@-~]', ' ', t)
    return re.sub(r'\s+', '', t)


def titles(raw):
    return re.findall(r'\x1b\]0;([^\x07\x1b]*)(?:\x07|\x1b\\)', raw)
