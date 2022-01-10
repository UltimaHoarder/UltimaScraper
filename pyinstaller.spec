import os
import user_agent
import subprocess
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct

a = Analysis(
    ['start_ofd.py'],
    pathex=[SPECPATH],
    binaries=[('extras/OFLogin/geckodriver.exe', '.')], # https://github.com/mozilla/geckodriver/releases/tag/v0.27.0
    datas=[
        (os.path.join(os.path.dirname(user_agent.__file__), 'data', '*'), 'user_agent/data'),
        ('database/databases', 'database/databases')
    ],
    hiddenimports=['logging.config'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

def git(*args):
    args = ['git', '-C', SPECPATH] + list(args)
    environ = dict(os.environ)
    environ['LC_ALL'] = 'C.UTF-8'

    return subprocess.run(
        args=args,
        stdout=subprocess.PIPE,
        env=environ,
        check=True,
        encoding='utf-8',
        errors='replace').stdout.strip()

major = 7
minor = 6
patch = 1
build = int(git('rev-list', 'HEAD', '--count'))
commit = git('rev-parse', '--short', 'HEAD')
branch = git('rev-parse', '--abbrev-ref', 'HEAD')

version = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(major, minor, patch, build),
        prodvers=(major, minor, patch, 0),
        mask=0x3f,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0)
    ),
    kids=[
        StringFileInfo([
            StringTable(
                '040904B0',
                [
                    StringStruct('FileDescription', 'OnlyFans DataScraper'),
                    StringStruct('FileVersion', '{}.{}.{}.{}'.format(major, minor, patch, build)),
                    StringStruct('LegalCopyright', 'GPLv3'),
                    StringStruct('ProductName', 'OnlyFans DataScraper'),
                    StringStruct('ProductVersion', '{}.{}.{}+{}@{}'.format(major, minor, patch, commit, branch))
                ])
            ]),
            VarFileInfo([VarStruct('Translation', [1033, 1200])])
    ]
)

exe = EXE(pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OF_DataScraper-{}.{}.{}'.format(major, minor, patch),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon='examples/icon.ico',
    version=version)
