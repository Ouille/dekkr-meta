# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'pystray._win32',
        'PIL._tkinter_finder',
        # Modules du projet chargés dynamiquement par FastAPI / les threads
        'server',
        'matcher',
        'importer',
        'database',
        'cover_fetcher',
        'windows',
        'tray',
        # uvicorn résout ces modules à l'exécution
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # Parsing du dump + matching
        'xml.sax',
        'xml.sax.expatreader',
        'rapidfuzz',
        'rapidfuzz.fuzz',
        'discogs_client',
        'oauthlib',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Le service n'a pas besoin de la pile scientifique, qui alourdit
        # inutilement l'exécutable.
        'numpy', 'pandas', 'matplotlib', 'scipy', 'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='dekkr-meta',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # pas de fenêtre console
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
