# Windows 分级参照（memory-analyzer）

> ⚠️ **本文件及 Windows 脚本（`*.ps1`）为代码就位、未在真实 Windows 实测。** 首次在 Windows 运行需验证：进程枚举、内存数值、`CloseMainWindow`/`Stop-Process` 行为。

agent 读 `scan.ps1` 输出后，按本文件把"有动作决策"的进程分到 🟢/🟡/🔴。

## Windows 内存模型

| scan 字段 | 来源 | 含义 |
|---|---|---|
| `rss` | `Win32_Process.WorkingSetSize` | 工作集（含共享页，≈ 任务管理器"内存"） |
| `mem` total | `Win32_OperatingSystem.TotalVisibleMemorySize` ×1024 | 物理内存 |
| free | `Win32_OperatingSystem.FreePhysicalMemory` ×1024 | 空闲 |
| standby（≈文件缓存） | （需 `Get-Counter` 或 `GlobalMemoryStatusEx`，scan 暂以 free 表征） | 系统自动回收 |
| `swap` | `Win32_PageFileUsage`（AllocatedBaseSize/CurrentUsage，MB） | 页面文件 |

**诚实性**：同 macOS——Windows 也激进缓存（standby list），"空闲低"不等于"内存不够"。看 `Committed Bytes / Commit Limit` 和页面文件使用率更准。杀应用释放的是其工作集，应用可能重启又占回。

## 🔴 永不触碰

`System`（Idle 进程）、`smss.exe`、`csrss.exe`（会话管理/客户端运行时）、`wininit.exe`、`winlogon.exe`、`services.exe`、`lsass.exe`（杀 lsass 会触发 Windows Defender 警报/强制重启）、`svchost.exe`（系统服务宿主，尤其 SYSTEM 属主）、`dwm.exe`（桌面窗口管理器）、`explorer.exe`（外壳，杀掉会注销当前会话体验，**不要直接杀**）。

判定：属主 `SYSTEM`/`LOCAL SERVICE`/`NETWORK SERVICE` 的系统核心 + Session 0 进程 → 🔴。拿不准 → 🔴。

## 🟢 可安全退出（自动重启 / 无状态，Windows 上更少）

- `SearchIndexer.exe`（Windows Search 索引，服务自动重启）
- 明确的、由服务控制器（`services.exe`）按"自动"启动且无交互状态的后台 helper

验证可重启（只读）：`Get-Service` / `Get-CimInstance Win32_Service -Filter "ProcessId=<pid>"`，看 `StartMode=Auto` 且非关键系统服务。**拿不准 → 🟡**。

## 🟡 谨慎退出（用户应用）

默认档。用户应用（浏览器、Office、IDE、通讯、Electron 应用等）。同 macOS：按主应用聚合子进程；风险点为未保存数据。

## 命令备忘（PowerShell）

- 进程：`Get-CimInstance Win32_Process | Select ProcessId,ParentProcessId,Name,ExecutablePath,@{n='rss';e={$_.WorkingSetSize}}`
- 内存：`Get-CimInstance Win32_OperatingSystem | Select TotalVisibleMemorySize,FreePhysicalMemory`
- 页面文件：`Get-CimInstance Win32_PageFileUsage | Select AllocatedBaseSize,CurrentUsage`
- 某 pid 现名（双键校验）：`(Get-CimInstance Win32_Process -Filter "ProcessId=<pid>").Name`
- 优雅关闭窗口：`(Get-Process -Id <pid>).CloseMainWindow()`；结束：`Stop-Process -Id <pid>`；强制：`Stop-Process -Id <pid> -Force`

## 聚合规则

同 macOS：同一应用（按 `ExecutablePath` 所属产品目录或 `Name` 前缀）的主进程 + 子进程聚合成一项，`aggregate_mem` 求和，进 Top N 与三色卡片。
