# macOS 分级参照（memory-analyzer）

agent 读 scan.json 后，按本文件把"有动作决策"的进程分到 🟢/🟡/🔴。正常在用、无决策的项不进三色，落到内存条"系统及其它"。

## macOS 内存模型（讲清，别误导）

`vm_stat`（× `getconf PAGESIZE`，Apple Silicon 通常 16384）：

| scan 字段 | vm_stat 来源 | 含义 |
|---|---|---|
| `mem.wired` | Pages wired down | 内核锁定、不可换出，**系统核心，永不动作** |
| `mem.compressed` | Pages occupied by compressor | 压缩别的内存占用的物理 RAM |
| `mem.app_memory` | Pages active | 应用正在用的 |
| `mem.file_cache` | Pages inactive + speculative | 文件缓存，**系统会自动回收，不需要杀进程** |
| `mem.free` | Pages free | 真空闲 |

**诚实性铁律**：macOS 内存管理激进缓存，**"空闲内存≈浪费"**。文件缓存（`file_cache`）会被系统按需自动回收，杀进程来"腾缓存"基本无意义且可能适得其反（应用重启又占回）。真正值得动的是：常驻的、用户不需要的重应用（释放 `app_memory`），或 `swap.used` 持续偏高（说明物理内存真不够）。在报告与小结里如实说。

## 🔴 永不触碰（系统关键，杀=崩溃/注销/重启，绝不给按钮）

这些进程出现在 scan 里也只展示，无任何动作按钮（`safety.SYSTEM_BLACKLIST` 已硬编码双保险）：

`kernel_task`、`launchd`(pid 1)、`WindowServer`、`loginwindow`、`Dock`、`SystemUIServer`、`Finder`、`coreaudiod`、`bluetoothd`、`thermald`、`cfprefsd`、`distnoted`、`trustd`、`runningboardd`、`amfid`、`opendirectoryd`、`UserEventAgent`、`securityd`、` powerd`、`configd`、`SystemExtensions`。

判定原则：comm 在 `/System/` 下、属主 `root`、且名字命中上述或明显是系统守护进程 → 🔴。拿不准 → 🔴（保守）。

## 🟢 可安全退出（可判定自动重启 / 无状态）

**很少**——比磁盘缓存少得多。仅当能确认进程由 launchd `KeepAlive` 自动拉起、且无用户未保存状态时才归 🟢：

- `mds_stores` / `mdworker_shared`（Spotlight 索引，会自动重启；结束后短暂影响搜索）
- 明确的 `com.apple.*` 索引/同步 helper（如 `cloudphotod` 的索引子进程），且能判定会重启

验证 KeepAlive（只读）：`launchctl list | grep <label>`，或看其父进程是 `1`（launchd）且属已知 KeepAlive 服务。**拿不准是否自动重启 → 降为 🟡**。

## 🟡 谨慎退出（用户应用，可能有未保存状态）

默认档。所有用户安装的 GUI `.app` 及其 helper 子进程：

- 浏览器（Chrome/Safari/Firefox/Edge）及其 Helper/Renderer/GPU 子进程——**按父应用聚合**成一项（一个"Chrome"），一键退出整个应用
- 编辑器/IDE（VS Code、Xcode、Cursor、Sublime）
- 通讯/办公（Slack、微信、钉钉、飞书、Notion、Figma、Office）
- 其它常驻重应用（Docker、虚拟机、 Electron 套壳应用）

风险点：未保存编辑、浏览器标签页/表单、下载中断。优雅退出（`osascript quit` / SIGTERM）让应用有机会保存；强制结束（SIGKILL）则可能丢数据。每项写明风险。

## 聚合规则

- 同一 `.app` 的主进程 + 它的所有子进程（同 bundle 的 Helper/Renderer 等）聚合成一个"应用"项，`aggregate_mem` = 各 `rss` 之和。
- 聚合后进 Top N 排行；三色卡片里该应用带 `graceful_targets`/`force_targets`（主进程 pid，或主要子进程 pid 列表）。

## 命令备忘

- 进程：`ps -axo pid,ppid,user,rss,pcpu,comm`
- 某 pid 现名：`ps -p <pid> -o comm=`（双键校验用）
- 内存：`vm_stat`、`sysctl -n hw.memsize`、`sysctl -n vm.swapusage`
- bundle_id（可选元信息）：`defaults read <App.app>/Contents/Info CFBundleIdentifier`
