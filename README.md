# ssp.py

A portable port of **SSP.exe**, the launcher and configurator of
*SYSTEMSHOCK-Portable 1.2* (Nicolai Sandow, 2006-2010), which eXoDOS ships
with *System Shock* (1994) as the "SSP Configurator".

SSP.exe is a Windows program. On macOS and Linux it has needed Wine. This
port is one Python 3 script, standard library only, that runs natively on
macOS, Linux and Windows.

SSP.exe is a batch file, SSP.bat, wrapped by a "Bat To Exe Converter": the exe
writes the script to a temporary folder and runs it with `cmd.exe`. The script
itself ships with SSP (`RES/SSP/src/SSP.bat`, GPL). ssp.py is that script,
label by label, in Python. It also takes over the two Windows tools the
script calls: `7za.exe` (unpacking the mods) and `sed.exe` (editing
`CYB.CFG`). A test drives the original and the port through the same key
presses and compares every screen and every file they leave behind (see
[Tests](#tests)). Four bugs of the original are fixed; `--no-fixes` keeps
them. [NOTES.md](NOTES.md) has the details.

## Requirements

Python 3.8 or later with the `lzma` module (all usual builds have it).
macOS: the `python3` of Apple's Command Line Tools (`xcode-select --install`)
or Homebrew. Linux: the distribution's `python3`. Windows: any python.org
install.

## Running it

```bash
python3 ssp.py
```

ssp.py works in its own folder, so put it next to `SSP.exe` (the folder that
holds `RES`), or point it there with `-C`. Under eXo that is
`eXoDOS/SystemSh/SSP`. The original works in the *current* folder instead.
eXo's launcher changes into that folder first, so the two behave the same
there.

## Patches for eXo

Two patches, each a folder with a patch script
(`make_release.py` builds them as zips in `release/`):

| Patch | What it does |
|---|---|
| `ssp-windows-fix` | Replaces `eXoDOS\SystemSh\SSP\SSP.exe` with a fixed SSP.exe: the original program with the [four fixes](#bugs-of-the-original) in its script. For Windows, without Python. |
| `ssp-port` | Puts ssp.py into `util\ssp`. System Shock's launcher (`eXoDOS\!dos\SystemSh\exception.bat`) then runs it as the "SSP Configurator" when Python (`py`) is there, and SSP.EXE otherwise. |

```bash
python fix_windows.py [--check | --revert] EXO_FOLDER
python install_port.py [--check | --revert] EXO_FOLDER
```

EXO_FOLDER is eXoDOS's `eXo` folder, the one with `eXoDOS`, `emulators` and
`util` in it. `--check` shows what would change, `--revert` undoes it.
`SSP.exe.orig` and `exception.bat.orig` keep the originals. The two patches
go together: with both applied, the launcher uses the port if it can and the
fixed exe if not.

- The fixed SSP.exe is built by `exo/build_fix.py` from the original
  (unpacked with UPX: `--upx`, `$UPX_PATH` or `upx` on the PATH). It
  replaces the exe's script resource with `exo/SSP.bat`, which is the
  original script with the fixes. The odd-answer fix reads the answers with
  cmd's delayed expansion, and the script is embedded with CRLF line ends (see
NOTES.md for why). The new exe is not UPX-packed (214 KB).
- `fix_windows.py` only replaces the SSP.exe it was made for (SHA-1
  `836c6b4e...`); another one is left alone unless `--force` is given. Only
  the installed game is patched, so after reinstalling System Shock, apply it
  again.
- `install_port.py` keeps the port in `util\ssp`, outside the game folder,
  and runs it with `-C .` from the game's SSP folder. So reinstalling the
  game keeps it.

| Option | Meaning |
|---|---|
| `-C`, `--directory DIR` | the SSP folder (the one holding `RES`), instead of the script's own |
| `--dosbox PATH` | the DOSBox that "b: Start SSP in ... DOSbox" runs (see below) |
| `--no-fixes` | keep the original's bugs too (see [below](#bugs-of-the-original)) |
| `--extract ARCHIVE DIR` | only unpack a 7z archive the way SSP does, then exit |
| `--version` | print the version |

## What it does

The menus, their wording and their effects are the original's:

- **Options**: switches Malba Tahan's mouselook mod, Gigaquad's text and
  texture mods, the 800x600/1024x768/640x480 game executables and the DOSBox
  build. It does this by unpacking the archives in `RES/SSP/mods` into `RES`
  and keeping flag files in `RES/SSP/flags`.
- **Config edit menu**: write-protects or unprotects `RES/CYB.CFG`, resets it,
  switches SSP's automatic sound settings, and opens the config files in an
  editor.
- **Main menu, b**: writes the sound settings into `CYB.CFG` and starts the
  game in DOSBox.
- **Information**: the help pages.

On Windows every console command and every program start is the original's
own command line, run through `cmd.exe` (`COLOR 1F`, `mode con`, `CLS`,
`PAUSE`, `START "" /d RES\gulikoza dosbox.exe`, `notepad`, ...). So the
window looks the same, and is left the same, as with SSP.exe.

On macOS and Linux the console work is done with ANSI/xterm escape
sequences: white on blue, a 72x26 window (where the terminal allows it),
the title. PAUSE says "Press any key to continue . . .". Programs are
started like this:

| Menu entry | Windows | macOS / Linux |
|---|---|---|
| b: Start SSP in DOSBox | the bundled `RES/gulikoza/dosbox.exe` (or `RES/dosbox`) | `--dosbox`, else `$DOSBOX`, else `dosbox`, `dosbox-staging` or `dosbox-x` on the PATH, started in the same folder with the same `dosbox.conf` |
| Config edit: e, b, c | Notepad | macOS: the default text editor (`open -t`); Linux: `xdg-open` on a desktop, else `$VISUAL`/`$EDITOR` |
| Info: s (systemshock.org) | the browser | the browser |
| Info: a (Cast SHODAN) | `madplay.exe` | `afplay`, `mpg123`, `ffplay`, `mpv` or `cvlc`, whichever exists |
| NTVDM modes (d, k), VDMSound, dgVoodoo setup, Speedset, the DOS installer, the DOS command reference | as the original | a note that it cannot be started there |

The NTVDM entries only appear on 32-bit Windows with NTVDM (or after
"d: Disregard determined OS"), as in the original.

## Differences from the original

Only where the port has to differ:

- The mods are unpacked by ssp.py itself, before the next screen appears.
  The original starts `7za.exe` in a window of its own and carries on at once.
  The results are identical, file by file, including timestamps and the
  read-only attribute.
- `CYB.CFG` is edited by ssp.py itself, with the same result as the
  original's `COPY /A` + `sed.exe` 4.2 + `ATTRIB` sequence, byte for byte.
  That includes sed's LF line endings and COPY's trailing Ctrl-Z.
- The SSP folder is the script's folder, not the current folder.
- On a case-sensitive file system, names are matched without regard to case,
  as Windows does (`citmat.7z` finds `CITMAT.7z`).
- macOS/Linux only: everything in the table above.

### Bugs of the original

ssp.py fixes these four. `--no-fixes` brings them back, exactly as SSP.exe
has them:

- **Disabling the mouselook mod** deletes `RES/dos4gw.exe`, but then asks 7za
  for `SSP/mods/SSP/mods/640x480.7z`, which does not exist. So the mouselook
  `CDSHOCK.EXE`, which needs `dos4gw.exe`, stays in place and the game no
  longer starts (until a resolution is chosen in Options). Fixed: the stock
  640x480 `cdshock.exe` is unpacked, as intended.
- **Disabling the scaled textures** unpacks `CITMAT.7z`, whose `CITMAT.RES`
  sits at the archive's top level. So it lands in `RES/`, not `RES/DATA/`, and
  the scaled `RES/DATA/CITMAT.RES` most likely stays in use. Fixed: it is
  unpacked into `RES/DATA/`.
- **Config edit menu → Edit CYB.CFG**: an invalid choice falls through into
  "r: remove write protection". Fixed: the menu comes back.
- **Answers containing cmd's special characters** are parsed by cmd as part of
  the script. Some answers make SSP close at once with exit code 255, because
  cmd hits a syntax error: an odd number of `"`, a leading `"`, a `"` with a
  space outside the quotes, or a leading `<`, `>` or `|`. A leading `&`
  counts as an empty answer (`"" is not a valid choice.`). A leading `^`
  swallows the menu's first line of choices, which then shows as the answer
  (`"if ""=="d" GOTO VESA" is not a valid choice.`). Fixed: they are invalid
  choices like any other.

Kept, as harmless:

- "Disregard determined OS" says "your OS () does not have the NTVDM": the
  script never sets `win_name`.
- The main menu's "p" (the Windows XP command reference) works for everyone,
  though it is only listed for the author. Info's "u" and Options' "u", "v"
  and "a" work when hidden too.

## Tests

The tests need an SSP installation as it comes, for example
`SystemSh\SSP` extracted from eXo's `System Shock (1994).zip`. One that has
been used has other flags, and then `compare_posix.py` and some scenarios no
longer fit. None of the tests starts DOSBox, an editor, a browser or anything
else, and all work on scratch copies.

```bash
py tests/compare_7z.py SSP_FOLDER
```

Each mod archive is unpacked by the original `7za.exe` 4.42 and by ssp.py
into scratch folders seeded with read-only and differently-cased files. Names,
contents, times and attributes are compared.

```bash
py tests/compare_cybcfg.py SSP_FOLDER
```

Ten sample `CYB.CFG` files go through the original's
`COPY /A`/`sed.exe`/`ATTRIB` lines and through ssp.py.

```bash
py tests/compare_console.py [--save sessions.json] [--exe EXE --fixes] SSP_FOLDER [SCENARIO ...]
```

SSP.exe and `ssp.py --no-fixes` each run in a hidden pseudo console on its
own scratch copy and get the same key presses (35 scenarios: every menu and
page, every toggle, the config menu, the NTVDM override, the sound-settings
paths, odd answers). The screen after every key, the titles, the exit code and
the files left behind are compared. `--exe exo/SSP.exe --fixes` compares the
fixed SSP.exe with ssp.py's fixes the same way. `--save sessions.json` also
records the original's sessions for:

```bash
python3 tests/compare_posix.py SSP_FOLDER sessions.json
```

This runs on macOS or Linux: `ssp.py --no-fixes` in a pty with the same keys,
compared with the recorded original.

```bash
python3 tests/test_fixes.py SSP_FOLDER
```

Any system: the four fixes, and that `--no-fixes` keeps each bug.

```bash
py tests/test_patches.py EXO_FOLDER
```

Both patches on a scratch eXo folder made from the real one's SSP.exe and
`exception.bat`: check, apply, apply again, revert, unknown SSP.exe.

## License

GPL version 3 or later, like SSP.bat, of which this is a translation.
Copyright 2006-2010 Nicolai Sandow (SSP.bat), 2026 Gunther Schmidl (the port).
