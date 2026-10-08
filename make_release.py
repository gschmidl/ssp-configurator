#!/usr/bin/env python3
"""Builds the two eXo patches in release/, each one folder with its patch script:

- ssp-windows-fix-<version>.zip: fix_windows.py and the fixed SSP.exe (exo/build_fix.py makes it),
  with its script SSP.bat;
- ssp-port-<version>.zip: install_port.py and the port.
"""
import pathlib
import re
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
PATCHES = {
    'ssp-windows-fix': ['exo/fix_windows.py', 'exo/SSP.exe', 'exo/SSP.bat', 'README.md',
                        'LICENSE'],
    'ssp-port': ['exo/install_port.py', 'ssp.py', 'README.md', 'NOTES.md', 'LICENSE'],
}


def main():
    version = re.search(r"^__version__ = '([^']+)'", (HERE / 'ssp.py').read_text(),
                        re.M).group(1)
    (HERE / 'release').mkdir(exist_ok=True)
    for name, files in PATCHES.items():
        top = f'{name}-{version}'
        out = HERE / 'release' / f'{top}.zip'
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(HERE / f, f'{top}/{pathlib.Path(f).name}')
        print(f'{out}: {out.stat().st_size} bytes, {len(files)} files')


if __name__ == '__main__':
    main()
