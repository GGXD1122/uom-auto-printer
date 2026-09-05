param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDir,
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$resolved = Resolve-Path -LiteralPath $ReleaseDir
$installer = Get-ChildItem -LiteralPath $resolved -File -Filter "*-Setup-v$Version.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $installer) {
    throw "未找到 v$Version 安装包"
}

$hash = Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256
$manifest = Join-Path $resolved "安装包-SHA256.txt"
"{0}  {1}" -f $hash.Hash.ToLowerInvariant(), $installer.Name |
    Set-Content -LiteralPath $manifest -Encoding UTF8
Write-Host "已生成安装包校验：$manifest"
