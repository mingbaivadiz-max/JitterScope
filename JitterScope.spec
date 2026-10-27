# Build for Windows 10/11 x64 with: python -m PyInstaller JitterScope.spec
from pathlib import Path
import PyQt6

root = Path(SPECPATH)
qt_bin = Path(PyQt6.__file__).parent / 'Qt6' / 'bin'
a = Analysis([str(root / 'jitterscope.py')], pathex=[], binaries=[],
             datas=[(str(root/'licenses'),'licenses'),(str(root/'assets'),'assets'),(str(root/'LICENSE'),'.')], hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
# Windows 10/11 provide UCRT/API sets. Do not bundle older compatibility DLLs
# found on the build machine's PATH. Use Qt's matching VC runtime at the root.
clean = []
for dest, source, kind in a.binaries:
    name = Path(dest).name.lower()
    if name.startswith('api-ms-win-') or name == 'ucrtbase.dll':
        continue
    if name in ('vcruntime140.dll', 'vcruntime140_1.dll') and (qt_bin / name).exists():
        source = str(qt_bin / name)
    clean.append((dest, source, kind))
a.binaries = clean
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='JitterScope',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False,
          icon=str(root/'assets'/'app.ico'),version=str(root/'version_info.txt'))
