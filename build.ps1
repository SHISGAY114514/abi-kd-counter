$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonExe = Join-Path $PSScriptRoot '.python\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $pythonExe)) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
$abiOriginalPath = $env:PATH
$abiOriginalEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONIOENCODING = 'utf-8'
    # Keep unrelated application DLL directories out of PyInstaller discovery.
    $env:PATH = "$(Split-Path $pythonExe);$env:SystemRoot\System32;$env:SystemRoot"
    $runtimeDir = & $pythonExe -c 'import pathlib,shiboken6; print(pathlib.Path(shiboken6.__file__).parent)'
    $runtimeArgs = @()
    foreach ($dll in @('msvcp140.dll','msvcp140_1.dll','msvcp140_2.dll','msvcp140_codecvt_ids.dll','vcruntime140.dll','vcruntime140_1.dll','concrt140.dll')) {
        if (Test-Path -LiteralPath (Join-Path $runtimeDir $dll)) {
            $runtimeArgs += @('--add-binary',"$(Join-Path $runtimeDir $dll);.")
        }
    }
    & $pythonExe make_icon.py
    if ($LASTEXITCODE -ne 0) { throw '图标生成失败' }
    & $pythonExe -m PyInstaller --noconfirm --clean --onefile --windowed --name ABI-KD-1.2.1 --distpath dist-public --icon assets/app-icon.ico --add-data 'assets;assets' --collect-all rapidocr_onnxruntime --collect-all onnxruntime --add-data '使用说明.txt;.' --add-data 'LICENSE;.' --add-data 'THIRD_PARTY_NOTICES.md;.' --add-data 'THIRD_PARTY_LICENSES;THIRD_PARTY_LICENSES' --exclude-module pytest --exclude-module tkinter @runtimeArgs app.py
    if ($LASTEXITCODE -ne 0) { throw '打包失败' }
} finally { $env:PATH = $abiOriginalPath; $env:PYTHONIOENCODING = $abiOriginalEncoding }
