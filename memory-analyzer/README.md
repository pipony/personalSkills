# memory-analyzer — 内存与进程分析（macOS / Windows）

对电脑做一次**只读**的内存与运行中进程分析，把"该不该动这个进程"判断成三色分级（🟢可安全退出 / 🟡谨慎退出 / 🔴永不触碰），产出交互式可视化网页，并让**安全的操作在网页上直接点击执行**（优雅退出 / 强制结束）。架构与磁盘版 `storage-analyzer` 同构，但分析对象是内存/进程。

> 本工具是 **agent 驱动**的：扫描和动作是脚本，三色分级由 agent（任何能跑 shell 的 LLM：Claude / GPT / Gemini / Cursor / Codex …）读 `references/<os>.md` + 扫描结果做判断。脚本本身纯标准库、零第三方依赖、不依赖任何特定 agent。

## 运行时（零安装）

| 平台 | 运行时 | 脚本 |
|---|---|---|
| macOS | Python 3（系统自带） | `scripts/scan.py` / `server.py` / `build_report.py` |
| Windows | PowerShell（Win10+ 自带） | `scripts/scan.ps1` / `server.ps1` / `build_report.ps1` |

> Windows 脚本为代码就位、**未在真实 Windows 实测**；macOS 已端到端实测。

## 铁律

1. **扫描全程只读**：只用 `ps`/`vm_stat`/`sysctl`（mac）或 `Get-CimInstance`（win），绝不发信号。
2. **动作只走受防护的 server 端点**：agent 本身在聊天里**不直接** kill 进程。用户在聊天说"帮我杀 X"也要先走网页/确认。
3. **系统关键进程永不可动**：硬黑名单（`safety.SYSTEM_BLACKLIST`），分级和动作时双重校验。
4. **PID+comm 双键**：每个动作执行时重新解析 pid 当前的 comm，必须与扫描时一致才执行——堵死"pid 被重用成 kernel_task 杀错"的致命坑。
5. **估算要标注为估算**；路径/命令保持原样不翻译。

## 工作流（任何 agent 照此执行）

### 1. 扫描（只读）

```bash
# macOS
python3 scripts/scan.py > /tmp/mem_scan.json
# Windows
pwsh scripts/scan.ps1 > "$env:TEMP\mem_scan.json"     # 或 powershell
```

产出 `{system:{os,total_mem,mem{...},swap{...}}, processes:[{pid,ppid,user,rss,cpu,name,comm,kind}...], denied:[...]}`。

### 2. 分析分级（agent 的大脑）

1. 读 `system.os` 选平台，读 `references/macos.md` 或 `references/windows.md`。
2. 读 `/tmp/mem_scan.json`：按父进程把子进程**聚合成应用**，取 **Top N** 内存占用。
3. 把"有动作决策"的项分到三色（见下）。系统进程、海量小进程不进三色。
4. 写 `/tmp/mem_analysis.json`（**analysis JSON 契约见文末附录**）。

### 3. 生成网页

**默认：server 模式（带一键动作按钮，自动开浏览器）**

```bash
python3 scripts/server.py /tmp/mem_analysis.json        # Ctrl+C 退出
# Windows: pwsh scripts/server.ps1 /tmp/mem_analysis.json
```

server 绑 `127.0.0.1` + 随机端口 + 随机 token。🟢🟡 项有「优雅退出」「强制结束」按钮；🔴 永无按钮。

**可选：静态只读 HTML（分享/留存用，无按钮，`file://` 打不开动作）**

```bash
python3 scripts/build_report.py /tmp/mem_analysis.json ~/Desktop/memory-report.html
# Windows: pwsh scripts/build_report.ps1 ...
```

> 网页上没出现动作按钮？要么你开的是静态报告（改用 `server` 模式），要么该项缺 `graceful_targets`/`force_targets`（补上再重启 server）。

### 4. 聊天小结

结论先行：预计可释放约多少、先处理哪 2-3 个、最高风险的一项是什么。细节在网页里。

## 三色分级标准

| 级别 | 含义 | 典型 | 网页按钮 |
|---|---|---|---|
| 🔴 永不触碰 | 系统关键，杀=崩溃/注销/重启 | kernel_task、launchd、WindowServer、lsass… | **无** |
| 🟡 谨慎退出 | 用户应用，可能有未保存状态 | 浏览器、IDE、通讯/办公应用 | 优雅退出；强制结束（二次确认） |
| 🟢 可安全退出 | 可判定自动重启/无状态 | Spotlight 索引等 KeepAlive 守护（很少） | 优雅退出；强制结束（可选） |

**按钮由数据驱动**：分析 JSON 里每项带 `graceful_targets`/`force_targets`（`{pid,name,comm,kind}` 列表）才出按钮；🔴 项不带。

## 动作映射

| 用户动作 | macOS | Windows |
|---|---|---|
| 优雅退出 | GUI 应用 `osascript quit`（SIGTERM 兜底）；后台 `kill -TERM` | `CloseMainWindow()`（后台 `Stop-Process`） |
| 强制结束 | `kill -9 <pid>`（应用的已记录子进程逐一，不杀整组） | `Stop-Process -Force` |

## 内存诚实性（重要）

macOS/Windows 都激进缓存，**"空闲内存≈浪费"**。报告展示内存**分类**，并说明：文件缓存会被自动回收、不需杀进程；杀应用释放的是其 app/工作集内存，但应用可能重启又占回。建议"退出特定重应用"而非"无脑清内存"。`swap` 占用持续偏高才是物理内存真不够的信号（报告会高亮）。

## 失败码

- scan：`0` 正常 / `2` 不支持的 OS（mac 用 .py、win 用 .ps1）/ `3` 采集命令失败
- server 动作返回 JSON：`{ok, done:[...], failed:[{pid,name,reason}]}`，reason 如 `进程已变更` / `目标不在白名单` / `系统关键进程，禁止动作` / `token 无效`

## 执行准则

跑完整条流程（扫描→分级→生成网页→小结）再向用户汇报，**中途不要反复问用户**。仅遇真正阻塞才打断：OS 不支持、扫描采集失败、缺运行时。

---

## 附录：analysis JSON 契约（agent 写、template/server 读）

```jsonc
{
  "generated_at": "2026-07-29T12:00:00",
  "system": { /* 透传自 mem_scan.json：os, os_version, total_mem, mem{wired,compressed,app_memory,file_cache,free}, swap{used,total} */ },
  "summary": {
    "total_reclaimable": 3000000000,
    "tier_stats": { "green": 0, "yellow": 0, "red": 0, "system_other": 0 },   // 字节
    "top_targets": ["Google Chrome", "Slack"],
    "highest_risk": "强制结束 VS Code 可能丢失未保存编辑",
    "long_term": ["物理内存 16GB 偏紧，建议减少开机自启"]
  },
  "ranking": [ { "name": "Google Chrome", "aggregate_mem": 2500000000, "child_count": 31, "cpu": 8.4, "tier": "yellow" } ],
  "tiers": {
    "green":  [ { "name","desc","mem","risk", "graceful_targets":[{pid,name,comm,kind}], "force_targets":[...], "command" } ],
    "yellow": [ { ...同上... } ],
    "red":    [ { "name","desc","mem","why_no_button","indirect_release" } ]   // 无 targets，无按钮
  }
}
```

`kind`：`"app"`（GUI 应用，优雅退出走 osascript/CloseMainWindow）或 `"process"`（后台进程，走 SIGTERM/Stop-Process）。`comm` 必须与扫描时 `ps comm` 完全一致（双键校验用）。

**target 必须是应用主进程**（scan 里 `is_main_app=true` 的那个，comm 形如 `<app_root>/Contents/MacOS/<binary>`），**绝不能是 helper/子进程**——杀 helper 应用会立即重生，主程序毫发无伤（"点了没反应"）。按 `app_root` 分组，不同 `app_root`（如 WeChat vs wechatwebdevtools）不能混组。详见 `references/macos.md` 聚合规则。scan 每个 process 字段：`pid, ppid, user, rss, cpu, name, comm, bundle_id, kind, app_root, is_main_app`。
