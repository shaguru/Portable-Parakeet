$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$modelSource = Join-Path $projectRoot 'models'
$outputRoot = Join-Path $projectRoot 'dist\ParakeetDictation'

if (-not (Test-Path -LiteralPath (Join-Path $modelSource 'parakeet-cli.exe'))) {
    throw "Parakeet runtime not found in the local models folder: $modelSource"
}

Push-Location $projectRoot
try {
    if (Test-Path -LiteralPath $outputRoot) {
        Remove-Item -LiteralPath $outputRoot -Recurse -Force
    }
    python -m PyInstaller --noconfirm --clean --windowed --onedir --name ParakeetDictation --collect-all sounddevice --collect-all _sounddevice_data parakeet_dictation.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

    $modelTarget = Join-Path $outputRoot 'models'
    New-Item -ItemType Directory -Force -Path $modelTarget | Out-Null
    # CPU runtime works on PCs without NVIDIA/CUDA drivers and keeps the
    # portable package small. GGML chooses the best supported CPU backend.
    Get-ChildItem -LiteralPath $modelSource -File |
        Where-Object { $_.Name -notmatch 'cuda|cublas|nvrtc|nvblas' } |
        Copy-Item -Destination $modelTarget -Force
    Copy-Item -LiteralPath (Join-Path $projectRoot 'PORTABLE_README.txt') -Destination $outputRoot -Force

    $zipPath = Join-Path $projectRoot 'ParakeetDictation-portable.zip'
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -LiteralPath $outputRoot -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Output "Portable folder: $outputRoot"
    Write-Output "Portable ZIP: $zipPath"
} finally {
    Pop-Location
}
