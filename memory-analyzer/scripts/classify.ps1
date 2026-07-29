# memory-analyzer 规则分类器 (Windows PowerShell)。scan.json → analysis.json。
# 与 classify.py 同规则。供 agent 参考 + server 的 /refresh 实时刷新。
# ⚠️ 未在真实 Windows 实测。
# 用法:  pwsh scripts/classify.ps1 <scan.json> [analysis.json]

param(
    [Parameter(Position=0)][string]$ScanPath = "$env:TEMP\mem_scan.json",
    [Parameter(Position=1)][string]$OutPath = "$env:TEMP\mem_analysis.json"
)
$ErrorActionPreference = 'Stop'
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path

# 系统黑名单（与 safety.py 一致）
$SYSTEM_BLACKLIST = @(
    'kernel_task','launchd','WindowServer','loginwindow','Dock','SystemUIServer','Finder',
    'coreaudiod','bluetoothd','thermald','cfprefsd','distnoted','trustd','runningboardd','amfid',
    'System','smss.exe','csrss.exe','wininit.exe','winlogon.exe','services.exe','lsass.exe','svchost.exe','dwm.exe','explorer.exe'
)
$SAFE_RESTART = @('SearchIndexer')
$MIN_APP_MEM = 80MB; $MIN_PROC_MEM = 150MB; $RED_DISPLAY_MEM = 100MB

function Test-SystemCritical($name, $comm) {
    $nm = ($name + '').Trim().ToLower(); $base = ($comm + '').Split('\')[-1].ToLower()
    return ($SYSTEM_BLACKLIST -contains $nm) -or ($SYSTEM_BLACKLIST -contains $base)
}

$scan = Get-Content -Raw $ScanPath | ConvertFrom-Json
$ps = $scan.processes
$green = @(); $yellow = @(); $red = @()

# 按 ExecutablePath 的顶层产品目录粗分组（Windows 无 .app 概念；以可执行名为主进程）
$byName = @{}
foreach ($p in $ps) { if ($p.name) { $byName[$p.name] = $p } }

foreach ($p in $ps) {
    $nm = $p.name; $rss = [int64]$p.rss
    if (Test-SystemCritical $nm $p.comm) {
        if ($rss -ge $RED_DISPLAY_MEM) { $red += [pscustomobject]@{name=$nm;desc='系统关键进程。';mem=$rss;why_no_button='杀掉会崩溃/注销/重启。';indirect_release=$null} }
        continue
    }
    if ($SAFE_RESTART -contains $nm) {
        $green += [pscustomobject]@{name="搜索索引 ($nm)";desc='索引服务，结束后自动重启。';mem=$rss;risk='低 — 自动重启';
            graceful_targets=@(@{pid=$p.pid;name=$nm;comm=$p.comm;kind='process'});
            force_targets=@(@{pid=$p.pid;name=$nm;comm=$p.comm;kind='process'}); command="Stop-Process -Id $($p.pid)"}
        continue
    }
    if ($rss -ge $MIN_APP_MEM) {
        $k = if ($p.kind -eq 'app') { 'app' } else { 'process' }
        $cmd = if ($k -eq 'app') { "Stop-Process -Id $($p.pid)" } else { "Stop-Process -Id $($p.pid)" }
        $yellow += [pscustomobject]@{name=$nm;desc='应用/进程。';mem=$rss;risk='中 — 可能丢失未保存状态';
            graceful_targets=@(@{pid=$p.pid;name=$nm;comm=$p.comm;kind=$k});
            force_targets=@(@{pid=$p.pid;name=$nm;comm=$p.comm;kind=$k}); command=$cmd; child_count=1}
    }
}
$yellow = @($yellow | Sort-Object mem -Descending)
$red    = @($red    | Sort-Object mem -Descending)
$reclaim = ($yellow | Measure-Object mem -Sum).Sum + ($green | Measure-Object mem -Sum).Sum

$analysis = [ordered]@{
    generated_at = 'auto-classified'
    system  = $scan.system
    summary = [ordered]@{
        total_reclaimable = $reclaim
        tier_stats = [ordered]@{ green=($green|Measure-Object mem -Sum).Sum; yellow=($yellow|Measure-Object mem -Sum).Sum; red=($red|Measure-Object mem -Sum).Sum; system_other=0 }
        top_targets = @($yellow | Select-Object -First 3 | ForEach-Object name)
        highest_risk = '强制结束可能丢失未保存数据。'
        long_term = @('常驻应用较多，建议关停不用的应用。')
    }
    ranking = @($yellow | Select-Object -First 12 | ForEach-Object { [pscustomobject]@{name=$_.name;aggregate_mem=$_.mem;child_count=1;cpu=0;tier='yellow'} })
    tiers = [ordered]@{ green=$green; yellow=$yellow; red=$red }
}
$analysis | ConvertTo-Json -Depth 10 -Compress | Set-Content -Encoding UTF8 $OutPath
[Console]::Error.WriteLine(("  分类: 绿{0} 黄{1} 红{2}" -f $green.Count,$yellow.Count,$red.Count))
