"""Build public release archives from an explicit, personal-data-free allowlist."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).parent
VERSION = '1.2.1'
PUBLIC_FILES = [
    '.gitignore', 'README.md', 'LICENSE',
    'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md', '使用说明.txt', 'requirements.txt',
    'app.py', 'core.py', 'ocr.py', 'dashboard.py', 'capture.py',
    'capture_windows.py', 'capture_ui.py', 'make_icon.py', 'build.ps1',
    'package_release.py', 'test_core.py', 'test_capture.py', 'test_ui.py',
    'test_import_pipeline.py',
]
PUBLIC_DIRS = ['assets', 'THIRD_PARTY_LICENSES']


def source_paths():
    result = [ROOT / name for name in PUBLIC_FILES]
    for folder in PUBLIC_DIRS:
        result.extend(p for p in (ROOT / folder).rglob('*') if p.is_file())
    return sorted(result)


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    exe = ROOT / f'dist-public/ABI-KD-{VERSION}.exe'
    entries = list(CArchiveReader(str(exe)).toc)
    forbidden = ('history.json', 'evidence/', 'ocr_cache/', 'qa-', 'local-backups/', '.sqlite3')
    assert not any(any(token in entry.replace('\\', '/') for token in forbidden) for entry in entries)
    source = source_paths()
    assert exe.stat().st_mtime > max(p.stat().st_mtime for p in source if p.suffix == '.py' and p.name != 'package_release.py')
    out = ROOT / '交付'
    out.mkdir(exist_ok=True)
    target = out / exe.name
    shutil.copy2(exe, target)
    shutil.copy2(ROOT/'使用说明.txt', out/'使用说明.txt')
    portable = out/f'ABI-KD-{VERSION}-Windows-x64.zip'
    with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(exe, exe.name)
        for name in ('LICENSE', 'README.md', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md', '使用说明.txt'):
            z.write(ROOT/name, name)
        for p in (ROOT/'THIRD_PARTY_LICENSES').rglob('*'):
            if p.is_file(): z.write(p, p.relative_to(ROOT).as_posix())
    source_zip = out/f'ABI-KD-{VERSION}-Source.zip'
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in source:
            z.write(p, f'ABI-KD-{VERSION}/'+p.relative_to(ROOT).as_posix())
    for p in (portable, source_zip):
        with zipfile.ZipFile(p) as z:
            assert z.testzip() is None
            assert not any(any(token in name for token in forbidden) for name in z.namelist())
    (out/'SHA256SUMS.txt').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in (target, portable, source_zip)), encoding='utf8')
    print(json.dumps({'version':VERSION, 'exe_sha256':digest(exe), 'public_source_files':len(source),
                      'embedded_resources':len(entries), 'personal_data_check':'passed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
