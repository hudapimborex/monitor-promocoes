# -*- mode: python ; coding: utf-8 -*-
#
# Spec do PyInstaller pro app desktop (.exe). Gerado uma vez e ajustado à
# mão; depois disso, é só rodar (dentro de backend/, com o venv ativado):
#
#   pyinstaller PromoMonitor.spec
#
# O .exe final fica em backend/dist/PromoMonitor.exe. Ver README (seção
# "App Desktop (.exe)") para detalhes.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['passlib.handlers.bcrypt', 'apscheduler.triggers.cron', 'apscheduler.jobstores.memory', 'apscheduler.executors.pool']
hiddenimports += collect_submodules('pystray')


a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[('../config/categories.yml', 'config'), ('app/web/templates', 'app/web/templates')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PromoMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
