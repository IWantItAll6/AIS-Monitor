# PyInstaller build spec. Run with: pyinstaller AISMonitor.spec
#
# Builds a onedir (not onefile) distribution deliberately: the app's own
# code resolves data/, assets/, and resources/ as plain relative paths (see
# main.py's frozen-mode chdir), so a onedir build lets those just be real
# files sitting next to the exe — no onefile temp-extraction on every
# launch, which matters given ~20-30MB of bundled coastline/places data.
#
# Only resources/README.md and resources/sample_replay.log are bundled
# from resources/ — never resources/* wholesale, since a developer's local
# checkout may hold private field-test logs (gitignored, never meant to
# ship). data/settings.json, data/recordings/, and data/crash.log are
# likewise runtime output, not build input, and are not listed below.

import sys

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("LICENSE", "."),
        ("assets/app_icon.png", "assets"),
        ("data/naturalearth/ne_10m_land", "data/naturalearth/ne_10m_land"),
        ("data/naturalearth/ne_10m_populated_places", "data/naturalearth/ne_10m_populated_places"),
        ("data/geonames/gb_towns.json", "data/geonames"),
        ("resources/README.md", "resources"),
        ("resources/sample_replay.log", "resources"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AISMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/app_icon.ico" if sys.platform == "win32" else None,
    # Flattens the layout to exe + data/assets/resources/etc. side by side,
    # instead of PyInstaller's newer default of burying everything but the
    # exe in an _internal/ subfolder. The app's own relative paths
    # (data/naturalearth/..., assets/app_icon.png, ...) expect to sit next
    # to the exe's own directory (see main.py's frozen-mode chdir).
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="AISMonitor",
)
