# memory-analyzer 交互服务 (Windows PowerShell)。默认模式：带动作按钮。
# 用法:  pwsh scripts/server.ps1 <analysis.json> [-NoOpen]
# 绑定 127.0.0.1 + 随机端口 + 随机 token；Ctrl+C 退出。
#
# ⚠️ 未在真实 Windows 实测。首次运行需验证：HttpListener 绑定、CloseMainWindow/Stop-Process、
#    Win32_Process ExecutablePath 在双键校验下的大小写一致性。
#
# 六层防护 + PID+comm 双键：Host 头 → token → mode → 白名单 → 当前 comm 与扫描 comm 一致 → 非系统关键。

param(
    [Parameter(Position=0)][string]$AnalysisJson,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$HERE  = Split-Path -Parent $MyInvocation.MyCommand.Path
$TEMPLATE = Join-Path $HERE '..\assets\report_template.html'

# —— 与 safety.py 一致的系统黑名单 ——
$SYSTEM_BLACKLIST = @(
    'kernel_task','launchd','WindowServer','loginwindow','Dock','SystemUIServer','Finder',
    'coreaudiod','bluetoothd','thermald','cfprefsd','distnoted','trustd','runningboardd','amfid',
    'System','smss.exe','csrss.exe','wininit.exe','winlogon.exe','services.exe','lsass.exe','svchost.exe','dwm.exe','explorer.exe'
)

function Test-SystemCritical($name, $comm) {
    $hay = ("$name $comm").ToLower()
    foreach ($b in $SYSTEM_BLACKLIST) { if ($hay.Contains($b.ToLower())) { return $true } }
    return $false
}

function Get-CurrentComm($targetPid) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$targetPid" -ErrorAction SilentlyContinue
    if ($null -eq $p) { return $null }
    if ($p.ExecutablePath) { return $p.ExecutablePath }
    return $p.Name
}

# —— 载入 analysis + 构建白名单 ——
if (-not $AnalysisJson) { [Console]::Error.WriteLine('用法: server.ps1 <analysis.json>'); exit 1 }
$analysis = Get-Content -Raw $AnalysisJson | ConvertFrom-Json

$Grace = @{}; $Force = @{}
foreach ($tier in 'green','yellow') {
    $items = $analysis.tiers.$tier
    if (-not $items) { continue }
    foreach ($item in $items) {
        foreach ($t in $item.graceful_targets) { if ($t) { $Grace["$($t.pid)|$($t.comm)"] = $true } }
        foreach ($t in $item.force_targets)   { if ($t) { $Force["$($t.pid)|$($t.comm)"] = $true } }
    }
}

function Test-Action($t, $mode) {
    if ($mode -notin 'graceful','force') { return @{ ok=$false; reason='未知动作模式' } }
    $al = if ($mode -eq 'graceful') { $Grace } else { $Force }
    $key = "$($t.pid)|$($t.comm)"
    if (-not $al.ContainsKey($key)) { return @{ ok=$false; reason='目标不在白名单' } }
    $live = Get-CurrentComm $t.pid
    if ($null -eq $live) { return @{ ok=$false; reason='进程已退出（已变更）' } }
    if ($live -cne $t.comm) { return @{ ok=$false; reason='进程已变更（pid 可能被重用），已拒绝' } }
    if (Test-SystemCritical $t.name $live) { return @{ ok=$false; reason='系统关键进程，禁止动作' } }
    return @{ ok=$true; reason='ok' }
}

function Invoke-Graceful($t) {
    try {
        $p = Get-Process -Id $t.pid -ErrorAction Stop
        if ($p.MainWindowHandle -ne [IntPtr]::Zero) { [void]$p.CloseMainWindow() }
        else { Stop-Process -Id $t.pid }
        return $true
    } catch { return $false }
}
function Invoke-Force($t) {
    try { Stop-Process -Id $t.pid -Force; return $true } catch { return $false }
}

# —— token + 模板注入 ——
$rngBytes = New-Object byte[] 24
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rngBytes)
$Token = [Convert]::ToBase64String($rngBytes).TrimEnd('=').Replace('+','-').Replace('/','_')

$tpl = Get-Content -Raw $TEMPLATE
$dataJson = $analysis | ConvertTo-Json -Depth 20 -Compress
$Html = $tpl.Replace('__REPORT_DATA__', $dataJson).Replace('__DELETE_CONFIG__', "{`"token`":`"$Token`",`"endpoint`":`"/action`"}")

# —— 找一个空闲端口 ——
$tl = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$tl.Start(); $Port = $tl.LocalEndpoint.Port; $tl.Stop()

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://127.0.0.1:$Port/")
$listener.Start()
[Console]::Error.WriteLine("  报告: http://127.0.0.1:$Port")
[Console]::Error.WriteLine("  token: 已启用  ·  Ctrl+C 退出")
if (-not $NoOpen) { try { Start-Process "http://127.0.0.1:$Port/" } catch {} }

function Send-Json($resp, $code, $obj) {
    $resp.StatusCode = $code
    $bytes = [Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Depth 10 -Compress))
    $resp.ContentType = 'application/json; charset=utf-8'
    $resp.ContentLength64 = $bytes.Length
    $resp.OutputStream.Write($bytes, 0, $bytes.Length)
}

try {
    while ($listener.IsListening) {
        $ctx  = $listener.GetContext()
        $req  = $ctx.Request
        $resp = $ctx.Response
        try {
            $h = $req.Headers['Host']
            if ($h -notmatch '^127\.0\.0\.1|^localhost') {
                $resp.StatusCode = 403
            }
            elseif ($req.HttpMethod -eq 'GET') {
                if ($req.Url.AbsolutePath -in '/','/index.html') {
                    $bytes = [Text.Encoding]::UTF8.GetBytes($Html)
                    $resp.ContentType = 'text/html; charset=utf-8'
                    $resp.ContentLength64 = $bytes.Length
                    $resp.OutputStream.Write($bytes, 0, $bytes.Length)
                } else { $resp.StatusCode = 404 }
            }
            elseif ($req.HttpMethod -eq 'POST' -and $req.Url.AbsolutePath -eq '/action') {
                $sr = New-Object IO.StreamReader($req.InputStream)
                $body = $sr.ReadToEnd(); $sr.Dispose()
                try { $reqobj = $body | ConvertFrom-Json } catch { Send-Json $resp 400 @{ok=$false;reason='请求格式错误'}; $body=$null }
                if ($reqobj) {
                    if ($reqobj.token -ne $Token) {
                        Send-Json $resp 403 @{ok=$false;reason='token 无效'}
                    } else {
                        $mode = $reqobj.mode
                        $fn = if ($mode -eq 'graceful') { 'Invoke-Graceful' } elseif ($mode -eq 'force') { 'Invoke-Force' } else { $null }
                        if (-not $fn) {
                            Send-Json $resp 400 @{ok=$false;reason='未知动作模式'}
                        } else {
                            $done = @(); $failed = @()
                            foreach ($t in $reqobj.targets) {
                                $r = Test-Action $t $mode
                                if (-not $r.ok) { $failed += [pscustomobject]@{pid=$t.pid; name=$t.name; reason=$r.reason}; continue }
                                if (& $fn $t) { $done += [pscustomobject]@{pid=$t.pid; name=$t.name; action=$mode} }
                                else { $failed += [pscustomobject]@{pid=$t.pid; name=$t.name; reason='进程已退出'} }
                            }
                            Send-Json $resp 200 @{ok=($failed.Count -eq 0); done=$done; failed=$failed}
                        }
                    }
                }
            } else { $resp.StatusCode = 404 }
        } catch {
            try { $resp.StatusCode = 500 } catch {}
        } finally {
            $resp.Close()
        }
    }
} finally {
    if ($listener.IsListening) { $listener.Stop() }
}
