# memory-analyzer 静态报告 (Windows PowerShell)。只读 HTML，无动作按钮（file:// 无法发请求）。
# 用法:  pwsh scripts/build_report.ps1 <analysis.json> [out.html]
# ⚠️ 未在真实 Windows 实测。

param(
    [Parameter(Position=0)][string]$AnalysisJson,
    [Parameter(Position=1)][string]$Out = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'memory-report.html')
)

$ErrorActionPreference = 'Stop'
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
$TEMPLATE = Join-Path $HERE '..\assets\report_template.html'

if (-not $AnalysisJson) { [Console]::Error.WriteLine('用法: build_report.ps1 <analysis.json> [out.html]'); exit 1 }

$analysis = Get-Content -Raw $AnalysisJson | ConvertFrom-Json
$tpl = Get-Content -Raw $TEMPLATE
$dataJson = $analysis | ConvertTo-Json -Depth 20 -Compress
$html = $tpl.Replace('__REPORT_DATA__', $dataJson).Replace('__DELETE_CONFIG__', 'null')

Set-Content -Path $Out -Value $html -Encoding UTF8
[Console]::Error.WriteLine("  已写出: $Out")
