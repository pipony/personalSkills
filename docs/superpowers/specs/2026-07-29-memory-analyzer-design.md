# memory-analyzer — 设计文档

- **日期**：2026-07-29
- **状态**：已批准（方案 A），待实现
- **参考**：`KKKKhazix/khazix-skills` 的 `storage-analyzer`（磁盘版）。本 skill 把同一套「只读扫描 → 三色安全分级 → 可视化网页 → 一键执行安全操作」架构迁移到**内存/进程**领域。

---

## 1. 背景与目标

storage-analyzer 解决"磁盘满了"，但**明确把内存排除在外**。用户要的是同类工具，但分析对象是**内存与运行中的进程**：找出吃内存的应用/进程，可视化占用，并让"安全操作"能在网页上直接点击执行——

- 关掉某应用（优雅退出整个 App）
- 结束某进程（SIGTERM / 必要时 SIGKILL 强制）

核心价值：**像 storage-analyzer 那样，把"该不该动"的判断做成三色分级，把安全的操作做成网页一键按钮，危险的绝不给按钮。**

## 2. 范围

**In scope**
- 扫描运行中的进程（pid/ppid/user/rss/cpu%/name）与系统内存分类。
- 按父进程把子进程聚合成"应用"，给出每个应用的聚合内存。
- 三色分级（🟢可安全退出 / 🟡谨慎退出 / 🔴永不触碰），只对"有动作决策"的项分级。
- 生成交互式可视化网页：内存总览条 + 进程/应用榜 + 三色卡片 + 一键动作按钮。
- 本地服务提供受防护的动作端点：优雅退出 / SIGTERM / SIGKILL（强制，二次确认）。
- macOS 与 Windows 双平台扫描/动作代码。

**Out of scope**
- 磁盘空间分析（那是 storage-analyzer）。
- 持续监控/后台常驻；本 skill 是一次性快照。
- 自动批量清理；每次动作都需用户点击 + 浏览器 confirm。

## 3. 平台姿态与运行时

- **macOS**：完整实现并**实测**。运行时 = **Python 3**（用户本机已有 3.13）；脚本 `scripts/scan.py` / `server.py` / `build_report.py`。
- **Windows**：代码就位但**标注未实测**，等用户在 Windows 上跑反馈再调。运行时 = **PowerShell**（Win10+ 系统自带，**零安装**）；脚本 `scripts/scan.ps1` / `server.ps1` / `build_report.ps1`。比 storage-analyzer"Windows 也要装 Python"更省事。
- **共享**：`assets/report_template.html`、analysis JSON 契约、`references/*.md` 两边通用；只有 scan / server / build_report 按语言各一份。agent 据 OS 选 `.py` 或 `.ps1`。

## 4. 架构总览

```
1. 扫描(只读)  scan.py → /tmp/mem_scan.json        绝不发信号
2. 分析分级    Claude 读 references/<os>.md + scan.json
                 → 按父进程聚合应用 → Top N + 🟢🟡🔴 → 写 /tmp/mem_analysis.json
3. 生成网页    默认 server.py(带动作按钮，自动开浏览器) / 可选 build_report.py(静态只读)
4. 聊天小结    结论先行：可释放约多少、先处理哪 2-3 个、哪个最高风险
```

与 storage-analyzer 同构：**scan.py（纯数据采集，只读）→ Claude（分级判断，大脑）→ build_report.py/server.py（展示 + 受防护动作）**。本 skill 同样是"agent 驱动，不是双击独立 App"。

## 5. 目录结构

```
memory-analyzer/
├── SKILL.md                 # Claude Code 入口（frontmatter 触发）+ 正文=agent 无关工作流
├── README.md                # 通用入口：人 + 任何 agent 都能照着跑（工作流的唯一真相源）
├── AGENTS.md                # 跨 agent 发现入口（Cursor/Gemini/Codex 等读它，指向 README）
├── assets/
│   └── report_template.html # 可视化网页模板（内存条 + 进程榜 + 三色卡片 + 动作按钮）
├── references/
│   ├── macos.md             # macOS 内存模型 + 进程分级参照
│   └── windows.md           # Windows 内存模型 + 进程分级参照
└── scripts/
    ├── scan.py              # macOS 只读扫描（Python，带 --help）
    ├── server.py            # macOS 本地服务 + 受防护 POST /action（Python，带 --help）
    ├── build_report.py      # macOS 静态只读 HTML（Python，可选）
    ├── scan.ps1             # Windows 只读扫描（PowerShell，零安装）
    ├── server.ps1           # Windows 本地服务 + 受防护 POST /action（PowerShell）
    └── build_report.ps1     # Windows 静态只读 HTML（PowerShell，可选）
```

### 5.1 agent 无关 / 通用化原则（本 skill 的硬约束）

- **脚本即真相**：`scan.py`/`server.py`/`build_report.py` 是纯 Python 标准库、零第三方依赖、不依赖任何 agent 或 Claude 特性。任何能跑 shell 的 agent（Claude / GPT / Gemini / Cursor / Codex / Copilot）或人，都能直接运行。
- **文档 agent 无关**：工作流写成"做这些步骤、跑这些命令"的中性描述，不出现 Claude 专属机制（如 skill 自动触发、特定工具调用格式）。`README.md` 是工作流的唯一真相源；`SKILL.md` 正文与之一致（仅多一层 Claude frontmatter 用于触发）；`AGENTS.md` 指向 `README.md` 供其他 agent 生态发现。
- **仍需 agent 在环做分级**：三色分级靠 agent 读 `references/<os>.md` + scan.json 做判断（不内置规则分类器）。因此"无 agent 直接一键出分级网页"不在范围内——但"任何 agent 照 README 跑"在范围内。
- **语言**：文档用中文（用户工作语言），不影响 agent 无关性（主流 agent 均支持中文）。

接入方式（遵循用户 skill-store 约定）：
```bash
ln -s /Users/huangxindi/ai/skill-store/memory-analyzer ~/.claude/skills/memory-analyzer
```

## 6. 扫描输出 schema（scan.py / scan.ps1 共用契约，只读）

```jsonc
{
  "system": {
    "os": "darwin",                 // darwin | windows
    "os_version": "macOS 15.x",     // sw_vers / Windows 版本
    "total_mem": 17179869184,       // 字节，hw.memsize / Win32_ComputerSystem
    "page_size": 16384,
    "mem": {                        // 字节；macOS 来自 vm_stat × page_size
      "wired": ..., "compressed": ..., "app_memory": ...,
      "file_cache": ..., "free": ...
    },
    "swap": { "used": ..., "total": ... }   // sysctl vm.swapusage / Win32_PageFileUsage
  },
  "processes": [
    {
      "pid": 1234, "ppid": 1, "user": "huangxindi",
      "rss": 1234567,               // 常驻内存，字节
      "cpu": 12.3,                  // CPU% 近 10s，次要信息列
      "name": "Google Chrome",      // 展示名（.app 名 / 进程名）
      "comm": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
      "bundle_id": "com.google.Chrome",   // macOS 有；用于优雅退出
      "is_app": true                // 是否 GUI .app 主进程（macOS）
    }
  ],
  "denied": [ ... ]                 // 因权限取不到的项（如需）
}
```

- macOS 采集：`ps -axo pid,ppid,user,rss,pcpu,comm`；bundle_id 由 comm 反推 `.app` 路径；内存用 `vm_stat` + `getconf PAGESIZE`；总量 `sysctl hw.memsize`；swap `sysctl vm.swapusage`。
- Windows 采集：`Get-CimInstance Win32_Process`（pid/ppid/name/WorkingSetSize）+ `Win32_OperatingSystem`（Free/TotalPhysicalMemory）+ `Win32_PageFileUsage`。
- 进程列表按 rss 降序，过滤掉 rss<50MB 的噪音（保留系统关键进程用于分级参照即使它们小）。

## 7. 三色分级模型（内存版）

> 与磁盘的关键差异：磁盘有大量"删了能重建"的纯缓存（🟢 很多）；**内存里真正零风险的可杀项很少**，大多数动作落在 🟡。SKILL.md 与网页都要讲清这一点，避免误导用户到处乱杀。

| 级别 | 含义 | 典型例子 | 网页按钮 |
|---|---|---|---|
| 🔴 永不触碰 | 系统关键，杀=崩溃/注销/重启 | `kernel_task`、`launchd`(pid1)、`WindowServer`、`loginwindow`、`Dock`、`Finder`、`SystemUIServer`、`coreaudiod`、`bluetoothd`、`thermald` | **无任何按钮**，只展示 |
| 🟡 谨慎退出 | 用户应用，可能有未保存状态 | Chrome、VS Code、Slack、Figma、企业 IM | 优雅退出；强制结束(二次确认) |
| 🟢 可安全退出 | 可判定自动重启/无状态的后台 helper | Spotlight 索引 `mds_stores`/`mdworker_shared` 等 launchd KeepAlive 守护（保守判定） | 优雅退出；强制结束(可选) |

- 分级是"动作决策清单"，不是完整清单。正常在用的应用、系统本身、海量小进程没有动作决策，落到内存条的"系统及其它"段。
- 🔴 清单硬编码在 `references/<os>.md` 与 `server.py` 黑名单里（双保险）。

## 8. 安全模型（六层防护 + PID 双键）

进程工具独有致命坑：**扫描时 pid 1234 是 Slack，点击时它已退出、该 pid 被 `kernel_task` 重用，直接杀=崩系统。** 因此引入 PID+名称双键：

1. **系统进程硬黑名单**：`kernel_task`/`launchd`/`WindowServer` 等无论分级如何都不给按钮；服务端动作时再次校验当前 pid 不在黑名单。
2. **PID+名称双键**：分析 JSON 里白名单条目存 `{pid, name}`。执行时服务端用 `ps -p <pid>` 重新解析当前进程名，**必须与扫描记录一致**才执行；进程已退出或名字不符 → 拒绝（"进程已变更，已拒绝"）。
3. **Host 头防 DNS rebinding**：只认 `127.0.0.1`/`localhost`，否则 403。
4. **随机 token**：每次会话 `secrets.token_urlsafe(24)`，请求须带正确 token。
5. **两套白名单** `GRACEFUL_ALLOW ⊂ FORCE_ALLOW`（按分级填充）+ 每条逐项校验。
6. **浏览器端 confirm**：每个动作点击前 `confirm()`；强制结束额外醒目警告。

## 9. 动作映射（两个用户动作，内部按进程类型分支）

| 用户动作 | 适用 | macOS | Windows |
|---|---|---|---|
| **优雅退出** `graceful` | 🟢🟡 默认动作 | GUI App：`osascript -e 'tell application "X" to quit'`；后台进程：`kill -TERM <pid>` | `(Get-Process -Id <pid>).CloseMainWindow()`（后台进程 `Stop-Process` 不带 -Force） |
| **强制结束** `force` | 🟢🟡 可选，二次确认 | `kill -9 <pid>`；若是应用则对其**扫描记录的子进程 pid 逐一** kill，不杀整个进程组（避免误伤） | `Stop-Process -Id <pid> -Force` |

- 🔴 无按钮。
- 分析 JSON 字段驱动按钮：每项带 `graceful_targets` 与 `force_targets`（`{pid,name}` 列表）；缺字段则不出对应按钮（与 storage-analyzer 的 `trash_paths` 机制同构）。

## 10. 内存诚实性（必须做对）

macOS 内存管理激进缓存，**"空闲内存=浪费"**。网页与 SKILL.md 需传达：

- 展示内存**分类**（活跃/非活跃/wired/已压缩/文件缓存/free/swap），而非单一"已用"。
- 点明：文件缓存会被系统自动回收，**不需要杀进程**；swap 占用高亮提示（可能意味着物理内存真不够）。
- 杀应用释放的是它的 app 内存，但应用可能自动重启；建议"退出特定重应用"而非"无脑清内存"。

## 11. report_template.html 结构（读序固定）

当前状态 → 诊断 → 处方 → 行动：

1. **内存总览卡**：总量 + 分段条（app内存/压缩/wired/文件缓存/free，swap 单独高亮）+ 系统信息。
2. **Top N 内存榜**（应用聚合，含 CPU% 次要列）。
3. **执行建议**（先处理哪 2-3 个）。
4. **🟢🟡🔴 可折叠卡片**：每项含聚合内存、子进程数、一键动作按钮。
5. **长期建议**（加内存 / 关 swap / 查内存泄漏应用）。

模板两个替换令牌：`__REPORT_DATA__`（分析 JSON）、`__DELETE_CONFIG__`（`null`=静态只读 / `{token,endpoint}`=server 模式启用按钮）。沿用 storage-analyzer 模板机制。

## 12. 文档结构与铁律（agent 无关）

**三份文档分工（同一套工作流，不同入口）：**
- `README.md` —— **唯一真相源**。完整工作流（扫描→分级→生成网页→小结）、脚本用法、铁律、失败码。人与任何 agent 都读它。每条脚本带 `--help`，即使只看帮助也能驱动。
- `SKILL.md` —— Claude Code 入口。frontmatter（`name`/`description` + 触发词）用于自动触发；正文与 README 一致（可 `参考 README.md`）。仅在 Claude Code 环境自动激活。
- `AGENTS.md` —— 跨 agent 发现入口（Cursor/Gemini CLI/Codex/Copilot 等约定读取）。简短说明"这是个 agent 驱动的内存分析工具，工作流见 README.md，脚本在 scripts/"。

**其他 agent 怎么用**：任何能跑 shell 的 agent，先判断 OS——macOS 跑 `scripts/scan.py`、Windows 跑 `scripts/scan.ps1` → 读 `references/<os>.md` + scan.json 做分级 → 写 analysis.json → 跑对应的 `server.py`/`server.ps1`。两边产出的 JSON 契约一致，HTML 模板共享。无任何 Claude 专属依赖。

**触发词**（写入 SKILL.md frontmatter，用于 Claude 自动触发；其他 agent 靠用户/README 引导）：内存占用高、电脑卡/慢、哪个进程吃内存、内存不够、释放内存、关掉某应用、结束某进程、memory/cpu 占用、"看下内存/进程"等。

**排除**：用户明显指磁盘（磁盘满了/清理空间/C 盘满）→ 引导用 storage-analyzer。

**铁律**：扫描全程只读；动作只在受防护的 server 端点执行，agent 本身在聊天里不发 kill 信号（用户在聊天说"帮我杀 X"也要先走网页/确认）；估算要标注为估算。

## 13. 失败场景与退出码（scan.py / scan.ps1）

- **0**：正常。
- **2**：不支持的 OS（非 darwin/windows）。
- **3**：采集命令失败（ps/vm_stat/PowerShell 不可用）。
- **4**：权限不足取不到关键数据（输出部分结果 + denied 列表，仍退出 0 但标注）。
- server.py 动作失败：返回 JSON `{ok:false, reason:"进程已变更"|"不在白名单"|"token 无效"|...}`，网页提示。

## 14. 测试计划

- **macOS 实测**：
  - scan.py 输出合法 JSON，内存分类之和≈总量。
  - 启一个已知重应用（如 Chrome），网页出现 🟡 卡片 + 优雅退出按钮；点击后应用正常退出、内存下降。
  - 强制结束按钮二次确认生效。
  - PID 复用拒绝：构造场景让某 pid 在点击前退出/变名，验证服务端拒绝。
  - 系统进程（kernel_task 等）卡片**无按钮**。
- **Windows**：代码就位 + 人工 checklist（进程枚举/内存数值/CloseMainWindow/Stop-Process），等用户机器反馈。

## 15. 交付物清单

1. `README.md`（agent 无关工作流真相源 + 人类用法 + 失败码）
2. `SKILL.md`（Claude 入口：frontmatter + 触发词 + 正文同 README）
3. `AGENTS.md`（跨 agent 发现入口，指向 README）
4. `scripts/scan.py`（macOS 只读扫描，带 `--help`）
5. `scripts/server.py`（macOS 受防护动作服务，PID 双键，带 `--help`）
6. `scripts/build_report.py`（macOS 静态只读 HTML，带 `--help`）
7. `scripts/scan.ps1` / `server.ps1` / `build_report.ps1`（Windows PowerShell 版，零安装，产出同一 JSON 契约）
8. `assets/report_template.html`（可视化网页）
9. `references/macos.md`、`references/windows.md`（分级参照）
10. 软链接接入 `~/.claude/skills/memory-analyzer`（Claude 侧）；其他 agent 侧由用户把目录指给对应工具

## 16. 开放问题

无。范围（内存/进程）、平台（Mac 优先 + Windows 代码就位）、安全底线（优雅退出为主 + 强制可选 + 系统进程永不可杀）、动作集（优雅/强制两档）、**通用化（仅文档通用：保留 agent 大脑、文档 agent 无关）** 均已确认。
