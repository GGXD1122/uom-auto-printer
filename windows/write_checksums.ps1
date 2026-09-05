param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDir
)

$resolved = Resolve-Path -LiteralPath $ReleaseDir
$manifest = Join-Path $resolved "release-manifest.sha256.txt"
$lines = Get-ChildItem -LiteralPath $resolved -File -Recurse |
    Where-Object { $_.FullName -ne $manifest } |
    Sort-Object FullName |
    ForEach-Object {
        $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
        $relative = $_.FullName.Substring($resolved.Path.Length).TrimStart('\')
        "{0}  {1}" -f $hash.Hash.ToLowerInvariant(), $relative
    }
$lines | Set-Content -LiteralPath $manifest -Encoding UTF8
Write-Host "已生成校验清单：$manifest"
