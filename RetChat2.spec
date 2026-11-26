# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller RetChat2.spec   →  dist/RetChat_2.2.exe
a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('logo/*.png', 'logo'), ('logo/app.jpg', 'logo')],
    hiddenimports=['i18n', 'aiohttp', 'aiohttp_socks', 'python_socks', 'python_socks.async_.asyncio', 'truststore', 'PyQt6.QtNetwork'],
    excludes=['playwright', 'tkinter', 'cairosvg', 'cairocffi', 'bs4', 'lxml', 'matplotlib', 'numpy'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='RetChat_3.1',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=['logo/app.jpg'],
)
