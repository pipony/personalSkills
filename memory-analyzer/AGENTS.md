# AGENTS.md

这是一个 **agent 驱动**的内存与运行中进程分析工具（macOS / Windows）。

- 只读扫描 → 三色安全分级（🟢可安全退出 / 🟡谨慎退出 / 🔴永不触碰）→ 交互式可视化网页 → 一键执行安全操作（优雅退出 / 强制结束）。
- 脚本纯标准库、零第三方依赖、不依赖任何特定 agent。任何能跑 shell 的 agent（Claude / GPT / Gemini / Cursor / Codex / Copilot）或人都能用。

## 怎么用（任何 agent 照此执行）

完整工作流、analysis JSON 契约、失败码、铁律见 **`README.md`（唯一真相源）**。要点：

1. 扫描（只读）：macOS `python3 scripts/scan.py > /tmp/mem_scan.json`；Windows `pwsh scripts/scan.ps1 > …`。
2. 分析分级：你（agent）读 `references/macos.md` 或 `references/windows.md` + 扫描结果，按父进程聚合应用、三色分级，写 `/tmp/mem_analysis.json`。
3. 生成网页：`python3 scripts/server.py /tmp/mem_analysis.json`（带动作按钮）。
4. 小结：结论先行。

## 安全

- 扫描只读。动作只走受防护的 `server` 端点（127.0.0.1 + 随机 token + 白名单 + PID+comm 双键 + 系统黑名单）。
- 系统关键进程永不可动。详见 `README.md` 与 `scripts/safety.py`。
