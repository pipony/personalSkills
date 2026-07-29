---
name: memory-analyzer
description: |
  对 macOS/Windows 做一次**只读**的内存与运行中进程分析，找出吃内存的应用/进程，把"该不该动"判断成三色分级（🟢可安全退出 / 🟡谨慎退出 / 🔴永不触碰），产出交互式可视化网页，并让**安全的操作在网页上直接点击执行**（优雅退出应用 / 强制结束进程）。架构同磁盘版 storage-analyzer，但分析对象是内存与进程，而非磁盘。

  当用户说"内存占用高""电脑卡/慢""哪个进程吃内存""内存不够/不足""释放内存""关掉某应用""结束/杀掉某进程""看下内存/进程""memory/cpu 占用高"等，或抱怨电脑变卡、想知道是什么占内存、想清理内存时，使用本 skill。

  也适用于：用户给了进程/应用名想退出或结束、想看当前内存大户、内存压力大/swap 飙高想排查。流程：扫描 → 三色分级 → 生成网页 → 小结。

  不适用于：用户明显指**磁盘**空间（"磁盘满了""C 盘满""清理空间""占盘"）——那应走 storage-analyzer；用户要的是单纯的活动监视器/任务管理器查看而非"分析+安全操作"。本 skill 只动内存/进程，不碰磁盘文件。
---

# memory-analyzer — 内存与进程分析（macOS / Windows）

只读扫描内存与运行中进程 → 三色安全分级 → 交互式网页 → 一键执行安全操作（优雅退出 / 强制结束）。完整工作流、契约、失败码见 **`README.md`**（本文件为 Claude 入口，正文与之一致）。

## 铁律

- 扫描全程只读；动作只走受防护的 `server` 端点，**agent 在聊天里不直接 kill**（用户说"帮我杀 X"也先走网页/确认）。
- 系统关键进程永不可动（`scripts/safety.py` 硬黑名单，双重校验）。
- PID+comm 双键：动作时重解析 pid 当前 comm，与扫描时不符就拒。
- 跑完整流程再汇报，中途别反复问用户；仅遇阻塞（OS 不支持、扫描失败、缺运行时）才打断。

## 工作流

**1. 扫描（只读）**
```bash
python3 scripts/scan.py > /tmp/mem_scan.json        # macOS
pwsh scripts/scan.ps1 > "$env:TEMP\mem_scan.json"   # Windows
```

**2. 分析分级**：可先用规则分类器自动出报告 `python3 scripts/classify.py /tmp/mem_scan.json /tmp/mem_analysis.json`（按 app_root 聚合、三色分级、target 主进程，列出所有达阈值应用），再按 `references/<os>.md` 精修。分级要点：
- 🔴 系统关键（kernel_task/launchd/WindowServer/lsass…）→ 只展示，**绝无按钮**。
- 🟡 用户应用（浏览器/IDE/通讯…，有未保存状态风险）→ `graceful_targets` + `force_targets`。
- 🟢 可判定自动重启/无状态（Spotlight 索引等，**很少**）→ 同上。
- 内存诚实：文件缓存会被自动回收、不需杀进程；swap 持续偏高才说明物理内存真不够。

**3. 生成网页（默认 server 模式，带按钮）**
```bash
python3 scripts/server.py /tmp/mem_analysis.json    # 自动开浏览器，Ctrl+C 退出
```
可选静态只读：`python3 scripts/build_report.py /tmp/mem_analysis.json ~/Desktop/memory-report.html`（无按钮）。**网页右上角「🔄 刷新」会重跑 scan+classify 实时刷新**（server 模式）。

**4. 小结**：结论先行——可释放约多少、先处理哪 2-3 个、最高风险一项。

## 依赖

macOS：系统自带 python3、`ps`/`vm_stat`/`sysctl`/`osascript`。Windows：PowerShell（Win10+ 自带）；脚本未实测。零第三方依赖。
