# memory-analyzer 只读扫描 (Windows PowerShell)。
# 输出 JSON 到 stdout（与 scan.py 同契约）: {system:{...}, processes:[...], denied:[...]}。
# 铁律: 全程只读，绝不发送信号。
#
# ⚠️ 未在真实 Windows 实测。首次运行需验证：进程枚举、内存数值、CloseMainWindow/Stop-Process。
# 用法:  pwsh scripts/scan.ps1   或   powershell -File scripts/scan.ps1

$ErrorActionPreference = 'Stop'

function ConvertTo-Bytes($token) {
    # vm.swapusage 等带单位（KB/MB/GB）的字符串 → 字节。Win32_PageFileUsage 直接是 MB，本函数备用。
    if ($token -match '^\s*([\d.]+)\s*(KB|MB|GB|TB)?') {
        $val = [double]$Matches[1]
        switch ($Matches[2]) {
            'KB' { return [int64]($val * 1KB) }
            'MB' { return [int64]($val * 1MB) }
            'GB' { return [int64]($val * 1GB) }
            'TB' { return [int64]($val * 1TB) }
            default { return [int64]$val }
        }
    }
    return 0
}

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $totalMem = [int64]($os.TotalVisibleMemorySize) * 1KB        # KB → 字节
    $freeMem  = [int64]($os.FreePhysicalMemory) * 1KB

    # 页面文件（MB 为单位）
    $swapUsed = 0; $swapTotal = 0
    $pf = Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue
    if ($pf) {
        foreach ($p in $pf) { $swapUsed += [int64]$p.CurrentUsage * 1MB; $swapTotal += [int64]$p.AllocatedBaseSize * 1MB }
    }

    $procs = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, WorkingSetSize

    $outProcs = foreach ($pr in $procs) {
        if ($null -eq $pr.ProcessId) { continue }
        $comm = if ($pr.ExecutablePath) { $pr.ExecutablePath } else { $pr.Name }
        $name = if ($pr.Name) { $pr.Name -replace '\.exe$','' } else { $comm }
        $kind = if ($comm -match '\\Program Files\\|\\Users\\[^\\]+\\AppData\\Local\\|\\Applications\\') { 'app' } else { 'process' }
        [pscustomobject]@{
            pid      = [int]$pr.ProcessId
            ppid     = [int]($pr.ParentProcessId)
            user     = $null
            rss      = [int64]$pr.WorkingSetSize
            cpu      = $null
            name     = $name
            comm     = $comm
            bundle_id = $null
            kind     = $kind
        }
    }
    $outProcs = @($outProcs | Sort-Object rss -Descending)

    $doc = [ordered]@{
        system = [ordered]@{
            os          = 'windows'
            os_version  = $os.Caption
            total_mem   = $totalMem
            mem = [ordered]@{
                # Windows 无 vm_stat 那样的细分类；以 free + 估算填契约字段（标注估算）
                wired       = 0
                compressed  = 0
                app_memory  = ($totalMem - $freeMem)
                file_cache  = 0
                free        = $freeMem
            }
            swap = [ordered]@{ used = $swapUsed; total = $swapTotal }
        }
        processes = $outProcs
        denied    = @()
    }
    $doc | ConvertTo-Json -Depth 8 -Compress
}
catch {
    [Console]::Error.WriteLine("采集失败: $($_.Exception.Message)")
    exit 3
}
