# SSP.exe notes

What SSP.exe is and does, as found by unpacking it and by running it in a
pseudo console against scratch copies of an SSP folder.

## The executable

- `SSP.exe`, 177,664 bytes, dated 2014-07-04, UPX-packed (unpacks to
  212,992 bytes; `upx -d`). PE32 console program, linked 2009-02-07.
  Version resource: ProductName "SYSTEMSHOCK-Portable Launcher",
  ProductVersion 1.2.3.0, CompanyName www.systemshock.org, InternalName
  SSP, LegalCopyright GPL.
- The code is a PureBasic program with German and English messages
  ("Bitte geben Sie das Passwort ein", "Choose a location to save the
  files", ...): one of the "Bat To Exe Converter" wrappers. Its RCDATA
  resources:
  - `N` = `SSP.bat`, the script's file name;
  - `B` = the script, 28,432 bytes, plain text with LF line ends;
  - `O` = `01 01 00 00 00 00`, the converter's options.
- At run time it makes a folder `%TEMP%\XXXX.tmp\`, writes `SSP.bat` there,
  runs `C:\WINDOWS\system32\cmd.exe /c ""%TEMP%\XXXX.tmp\SSP.bat""` (from a
  32-bit process, so the SysWOW64 cmd.exe) in the console it was started in,
  in the **current** directory, waits for it, deletes the folder and exits
  with cmd's exit code.

## The script

The embedded script is `RES/SSP/src/SSP.bat` (2010-08-01, 968 lines, CRLF)
with two changes:

- `chcp 850 >nul` after `@echo off`;
- the four menu headers drawn with CP437 box characters (`╔═╗ ║ Main Menu ║`)
  are plain text instead (`           Main Menu`, with blank lines around it,
  one fewer above "Options").

Everything else, comments included, is the same. SSP.bat's paths are
relative to the current directory (`./RES/SSP/flags/...`, `START /d RES ...`).
eXo's `!dos/SystemSh/exception.bat` changes to `eXoDOS\SystemSh\SSP` before
it runs `SSP.EXE`.

### State

- `RES/SSP/flags/<name>` files ("flag \r\n", appended with `ECHO flag >>`):
  `auto_cyb`, `mouselook_enabled`, `enhanced_text_enabled`,
  `scaled_object_textures_enabled`, `gulikoza_enabled` / `dosbox_enabled`,
  `640x480` / `800x600` / `1024x768`, `affinity_1`. eXo ships the first five.
- `showNTVDM`: 1 if `%windir%/system32/NTVDM.exe` exists (from the 32-bit
  cmd that is SysWOW64, so 0 on 64-bit Windows). Options' "d" sets 2 (show
  the NTVDM entries anyway) and back to 0.

### Mods (`START /d RES 7za.exe x -y SSP/mods/<archive>`)

| Archive | Holds | Used by |
|---|---|---|
| `xcdshock.7z` | `DATA\{CYB,FRN,GER}STRNG.RES`, `CDSHOCK.EXE` (DOS/4GW stub), `dos4gw.exe` | enable mouselook |
| `640x480.7z`, `800x600.7z`, `1024x768.7z` | the three `*STRNG.RES`, `cdshock.exe` (CauseWay) | 6, 8, 1 |
| `text_enhanced.7z`, `text_original.7z` | `DATA\CYBSTRNG.RES` | t |
| `citmat_scaled.7z` | `DATA\CITMAT.RES` | p (on) |
| `CITMAT.7z` | `CITMAT.RES` (top level) | p (off), named `citmat.7z` in the script |
| `DEFAULT.CYB.CFG.7z` | `CYB.CFG` (attributes R A) | config: x (on) |

Methods: LZMA, and BCJ + LZMA for the executables (7za 4.42). ssp.py's own
7z reader handles copy, LZMA, LZMA2, BCJ (x86) and Delta, with Python's
`lzma` module.

7za 4.42 `x -y`, as measured against seeded scratch folders:

- an existing file is replaced even if read-only, and takes the archive's
  name case (`cdshock.exe` replaces `CDSHOCK.EXE`);
- files get the archive's modification time and attributes (so `CYB.CFG`
  comes out read-only);
- folders get the archive's attributes (`D`, `DI`) but not its time.

Without an end marker, liblzma's x86 filter holds back up to four
unconverted bytes at the end of a raw stream. ssp.py takes those from the
plain LZMA output.

### CYB.CFG sound settings

With `auto_cyb`, starting the game rewrites three lines of `RES\CYB.CFG`:

```
COPY /A /V /Y RES\CYB.CFG RES\SED\CYB.CFG~TEMP >nul
CD RES/SED
sed.exe -e "s:digi_list.*:digi_list N:g" -e "s:digi_card.*:digi_card N:g" -e "s:digi_irq.*:digi_irq N:g" <CYB.CFG~TEMP >CYB.CFG
CD ../..
ATTRIB -R RES\CYB.CFG
COPY /A /V /Y RES\SED\CYB.CFG RES\CYB.CFG >nul
ATTRIB +R RES\CYB.CFG
DEL RES\SED\CYB.CFG~TEMP
DEL RES\SED\CYB.CFG
```

with 0/3/7 for DOSBox, 3/3/-1 (VDMSound) or 10/1/-1 for Mouse2kv. The result,
checked against the real tools: everything up to the first Ctrl-Z (COPY /A),
lines split at LF after CRLF→LF (GNU sed 4.2 reads in text mode), each line
substituted, written with **LF** line ends (sed writes in binary mode), no
newline added at the end if there was none, then one Ctrl-Z (COPY /A), and
the file is read-only.

### Console

`COLOR 1F`, `mode con: cols=72 lines=26`, `TITLE ...` (with `%date%
%time:~0,5%` in the first one), `CLS`, `PAUSE` (cmd's localized prompt),
`set /p choice=` and the first character of the answer, compared
case-sensitively. An empty answer prints `"" is not a valid choice.`.

Every menu reads its answer like this:

```
set choice=
set /p choice=
if not "%choice%"=="" set choice=%choice:~0,1%
if "%choice%"=="d" GOTO VESA
...
```

The answer is pasted into the third line before cmd parses it, so cmd's
special characters in it take effect. Measured with the original:

| Answer | Result |
|---|---|
| odd number of `"`; leading `"`; a space, tab, `,`, `;` or `=` outside quotes (`a b"c d"`) | the IF is a syntax error: the batch ends, SSP exits 255, nothing printed |
| leading `<`, `>`, `\|` | `set choice=>` etc.: syntax error, same |
| leading `&` | `set choice=&`: empty, `"" is not a valid choice.` |
| leading `^` | the caret joins the next line: choice becomes `if "REST"=="d" GOTO VESA` (REST = the answer after the caret) and that first comparison is gone |
| `a\|b`, `ab"c"`, `a""`, `%`, `(`, `)`, ` x`, `ä` | ordinary: the first character |

ssp.py applies those rules with `--no-fixes` (`SSP.choice`); by default it
takes the first character of any answer. The comma/semicolon/equals cases
are from cmd's delimiter list, not measured.

### Bugs

See the README (fixed by default, kept with `--no-fixes`). Two of them
affect the game:

- `:XDSHOCK` (disable mouselook): `START /d RES 7za.exe x -y
  SSP/mods/SSP/mods/640x480.7z`. The path is doubled, so nothing is unpacked,
  but `DEL .\RES\dos4gw.exe` already ran. The mouselook `CDSHOCK.EXE` needs it
  (`DOS4GPATH`, `dos4gw.exe` strings; the stock one has CauseWay bound in).
- `:SCALEDTEXTURES` (disable): `CITMAT.7z` puts `CITMAT.RES` in `RES\`. The
  game finds its resources through `data_dir_path` (default `data\`) and
  `cd_data_dir_path`, so the scaled `DATA\CITMAT.RES` most likely stays in
  use. Not checked in the game.

The other two fixed ones: `:EDITCYBCFG` has no `GOTO` after the
invalid-choice `PAUSE` and falls into `:UNPRTCYBCFG`; and the answers (see
Console). Harmless ones, kept: `%win_name%` is never set; `:MOUSE2KV` checks
`./RES/SSP/flags/affinity_1` after `CD RES`; the main menu's "p" opens
`ntcmds.chm`, which Windows has not had since XP.

## The fixed SSP.exe (`exo/`)

`exo/build_fix.py` unpacks the original with UPX and replaces RCDATA "B"
(language 0) with `exo/SSP.bat` through `UpdateResource`. Icons, version
and manifest stay as they are; the result is not UPX-packed again (214,016
bytes). `exo/fix_windows.py` puts it into an eXo installation (the
`ssp-windows-fix` patch). `exo/SSP.bat` is the embedded script with:

- `SSP/mods/640x480.7z` for `SSP/mods/SSP/mods/640x480.7z`;
- `7za.exe x -y -oDATA SSP/mods/citmat.7z`;
- `GOTO EDITCYBCFG` after the invalid-choice `PAUSE` in `:EDITCYBCFG`;
- `SETLOCAL EnableDelayedExpansion` at the start, and in all seven menus
  `if defined choice set "choice=!choice:~0,1!"`, `if "!choice!"==...` and
  `ECHO "!choice!" is not a valid choice.`. A delayed-expanded value is never
  parsed again, so any character is just a character. With delayed expansion
  on, a bare `!` disappears, so the two lines that print one have it escaped:
  `boss^^!` (unquoted) and `"Look at you %username%^!"` (quoted);
- **CRLF line ends.** The embedded original is LF-only. In an LF-only batch
  file cmd's label search can find a label inside a line. With the edits
  above (399 bytes more), `GOTO OPTIONS` after "Original 640x480 resolution
  reset." landed on `clicking: Options - Video - Video Mode.` in `:RESINFO`.
  With CRLF that cannot happen. The original's own GOTOs pass every scenario
  of the console test. The ones not tried are those that start other programs.

`tests/compare_console.py --exe exo/SSP.exe --fixes` checks it against
ssp.py's fixes, scenario by scenario.
