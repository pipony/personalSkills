# memory-analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `memory-analyzer`, an agent-driven (agent-agnostic docs) tool that scans memory/running processes, classifies cleanup decisions into 🟢/🟡/🔴 tiers, renders an interactive HTML report, and executes safe actions (graceful quit / force kill) via a guarded local server — macOS (Python, tested) + Windows (PowerShell, zero-install, code-in-place).

**Architecture:** Mirrors storage-analyzer. Read-only scanner → agent (any LLM) does 3-tier classification → interactive HTML template (shared) → local server with defense-in-depth action endpoint. Unique to processes: **PID+comm dual-key revalidation** to defeat the PID-reuse footgun. Two runtimes (Python on Mac, PowerShell on Windows) share one JSON contract and one HTML template.

**Tech Stack:** Python 3 stdlib (macOS), PowerShell 5.1+ (Windows), HTML/CSS/vanilla JS, pytest (safety-logic only).

## Global Constraints

- **macOS = Python 3** (`scripts/*.py`), tested on this machine. **Windows = PowerShell** (`scripts/*.ps1`), zero-install, code-in-place but UNTESTED — flag in every Windows file's header.
- **Scan is strictly read-only.** Never send signals from scan scripts. Only `server.py`/`server.ps1` send signals, and only via the guarded `/action` endpoint.
- **System-critical processes are never actionable.** Hard blacklist (`safety.py` SYSTEM_BLACKLIST) is checked at classification time AND re-checked at action time.
- **PID+comm dual-key:** every action re-resolves the live `comm` for the pid and requires an exact match with the scanned `comm`, else reject. No exceptions.
- **Two action modes only:** `graceful` (SIGTERM; GUI app → osascript quit with SIGTERM fallback) and `force` (SIGKILL). No "kill whole process group."
- **agent-agnostic docs:** `README.md` is the single source of truth; `SKILL.md` = Claude frontmatter + same body; `AGENTS.md` points to README. No Claude-specific mechanics in the workflow.
- **No third-party deps** for runtime scripts (stdlib / PowerShell only). pytest only for the safety unit tests.
- All user-facing text in **Chinese** (user's working language).

---

## File Structure

```
memory-analyzer/
├── README.md                      # T7 — universal source of truth
├── SKILL.md                       # T7 — Claude entry (frontmatter + body)
├── AGENTS.md                      # T7 — cross-agent discovery
├── assets/
│   └── report_template.html       # T3 — shared viz template
├── references/
│   ├── macos.md                   # T6 — mac memory model + tiering
│   └── windows.md                 # T6 — win memory model + tiering
├── scripts/
│   ├── scan.py                    # T1 — mac read-only scan
│   ├── safety.py                  # T2 — pure safety logic (tested)
│   ├── server.py                  # T4 — mac guarded action server
│   ├── build_report.py            # T5 — mac static HTML
│   ├── scan.ps1                   # T8 — win read-only scan
│   ├── server.ps1                 # T8 — win guarded action server
│   └── build_report.ps1           # T8 — win static HTML
└── tests/
    └── test_safety.py             # T2 — pytest for safety.py
```

### The central contract: analysis JSON (produced by the agent, consumed by template + server)

The agent reads `scan.py` output (`/tmp/mem_scan.json`) + `references/<os>.md`, then writes `/tmp/mem_analysis.json` in THIS exact shape:

```jsonc
{
  "generated_at": "2026-07-29T12:00:00",      // agent stamps it
  "system": { /* echoed from mem_scan.json: os, os_version, total_mem, mem{...}, swap{...} */ },
  "summary": {
    "total_reclaimable": 3000000000,           // bytes, 🟢+🟡 aggregate estimate
    "tier_stats": { "green": 0, "yellow": 0, "red": 0, "system_other": 0 }, // bytes
    "top_targets": ["Google Chrome", "Slack"], // 2-3 names to clean first
    "highest_risk": "强制结束 VS Code 可能丢失未保存编辑",
    "long_term": ["物理内存 16GB 偏紧，常驻应用多，建议考虑升级内存或减少开机自启"]
  },
  "ranking": [                                  // Top N apps, desc by aggregate_mem
    { "name": "Google Chrome", "aggregate_mem": 2500000000, "child_count": 31, "cpu": 8.4, "tier": "yellow" }
  ],
  "tiers": {
    "green": [
      {
        "name": "Spotlight 索引 (mds_stores)",
        "desc": "系统索引服务，会自动重启；结束后短暂影响搜索速度。",
        "mem": 1800000000,
        "risk": "低 — launchd 会自动拉起",
        "graceful_targets": [ { "pid": 411, "name": "mds_stores", "comm": "/System/Library/Frameworks/CoreServices.framework/Frameworks/Metadata.framework/Support/mds_stores", "kind": "process" } ],
        "force_targets": [ /* same shape, opt-in */ ],
        "command": "kill -TERM 411"
      }
    ],
    "yellow": [
      {
        "name": "Google Chrome",
        "desc": "浏览器，31 个渲染子进程。优雅退出会关闭所有标签页（Chrome 通常会恢复）。",
        "mem": 2500000000,
        "risk": "中 — 可能丢失未保存的表单/标签页",
        "graceful_targets": [ { "pid": 1234, "name": "Google Chrome", "comm": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "kind": "app" } ],
        "force_targets": [ /* same */ ],
        "command": "osascript -e 'tell application \"Google Chrome\" to quit'"
      }
    ],
    "red": [
      {
        "name": "kernel_task",
        "desc": "内核核心进程，管理系统资源。",
        "mem": 3000000000,
        "why_no_button": "杀掉会立即崩溃系统/强制重启。",
        "indirect_release": null
      }
    ]
  }
}
```

**Button wiring (data-driven, same as storage-analyzer's trash_paths):**
- Item with non-empty `graceful_targets` → renders 「优雅退出」 button.
- Item with non-empty `force_targets` → renders 「强制结束」 button (extra confirm).
- `red` items → no buttons, ever.

**Server allowlists (built from tiers):**
- `GRACEFUL_ALLOW` = all `graceful_targets` from green+yellow (set of `(pid, comm)`).
- `FORCE_ALLOW` = all `force_targets` from green+yellow.

---

## Task 1: Scaffold + `scripts/scan.py` (macOS, read-only)

**Files:**
- Create: `memory-analyzer/scripts/scan.py`
- No test file (system-dependent; manual verification).

**Interfaces:**
- Produces: stdout JSON conforming to the `system` + `processes` shape above (scan half). Later: agent reads `/tmp/mem_scan.json`.

- [ ] **Step 1: Create the skill directory scaffold**

```bash
cd /Users/huangxindi/ai/skill-store
mkdir -p memory-analyzer/{scripts,assets,references,tests}
```

- [ ] **Step 2: Write `scripts/scan.py`** (complete)

```python
#!/usr/bin/env python3
"""memory-analyzer 只读扫描 (macOS)。Windows 请用 scan.ps1。
输出 JSON 到 stdout: {system:{...}, processes:[...], denied:[...]}。
铁律: 全程只读，绝不发送信号。"""
import json, os, re, subprocess, sys

PAGE_SIZE = int(subprocess.check_output(["getconf", "PAGESIZE"]).strip()) if sys.platform == "darwin" else 4096

def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout

def collect_memory():
    out = sh(["vm_stat"])
    pages = {}
    for line in out.splitlines():
        m = re.match(r"^(.*?):\s*([0-9]+)\.?$", line.strip())
        if m:
            pages[m.group(1).strip().lower()] = int(m.group(2)) * PAGE_SIZE
    def pick(*keys):
        for k in keys:
            for real in pages:
                if k in real:
                    return pages[real]
        return 0
    total = int(sh(["sysctl", "-n", "hw.memsize"]).strip() or 0)
    swap = {"used": 0, "total": 0}
    sw = sh(["sysctl", "-n", "vm.swapusage"])
    um = re.search(r"used\s*=\s*([0-9]+)", sw)
    tm = re.search(r"total\s*=\s*([0-9]+)", sw)
    if um: swap["used"] = int(um.group(1))
    if tm: swap["total"] = int(tm.group(1))
    return {
        "total_mem": total,
        "mem": {
            "wired": pick("wired down"),
            "compressed": pick("occupied by compressor"),
            "app_memory": pick("active"),
            "file_cache": pick("inactive") + pick("speculative"),
            "free": pick("free"),
        },
        "swap": swap,
    }

def app_name_and_bundle(comm):
    """从 comm 路径反推 .app 展示名与 bundle_id（尽力而为）。"""
    m = re.search(r"(/.+?\.app)/Contents/MacOS/", comm)
    if not m:
        base = os.path.basename(comm)
        return base, None, "process"
    app_path = m.group(1)
    name = os.path.basename(app_path)[:-4]  # 去 .app
    bid = None
    try:
        bid = subprocess.check_output(
            ["defaults", "read", app_path + "/Contents/Info", "CFBundleIdentifier"],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        pass
    return name, bid, "app"

def collect_processes():
    out = sh(["ps", "-axo", "pid,ppid,user,rss,pcpu,comm"])
    procs = []
    for line in out.strip().splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            pid, ppid, user, rss_kb, cpu = int(parts[0]), int(parts[1]), parts[2], int(parts[3]), float(parts[4])
        except ValueError:
            continue
        comm = parts[5].strip()
        name, bundle_id, kind = app_name_and_bundle(comm)
        procs.append({
            "pid": pid, "ppid": ppid, "user": user,
            "rss": rss_kb * 1024, "cpu": cpu,
            "name": name, "comm": comm, "bundle_id": bundle_id, "kind": kind,
        })
    # 过滤 <50MB 噪音，但保留全部供 agent 分级（agent 需要看到系统进程）
    procs.sort(key=lambda p: p["rss"], reverse=True)
    return procs

def main():
    if sys.platform != "darwin":
        sys.stderr.write("scan.py 仅支持 macOS；Windows 请用 scan.ps1\n")
        sys.exit(2)
    try:
        doc = {
            "system": {"os": "darwin",
                        "os_version": sh(["sw_vers", "-productVersion"]).strip(),
                        **collect_memory()},
            "processes": collect_processes(),
            "denied": [],
        }
    except Exception as e:
        sys.stderr.write(f"采集失败: {e}\n")
        sys.exit(3)
    json.dump(doc, sys.stdout, ensure_ascii=False)

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run scan, verify valid JSON + memory sums**

```bash
cd memory-analyzer && python3 scripts/scan.py > /tmp/mem_scan.json
python3 -c "import json;d=json.load(open('/tmp/mem_scan.json'));m=d['system']['mem'];print('total',d['system']['total_mem'],'sum',sum(m.values()));print('procs',len(d['processes']));print('top',d['processes'][0]['name'],d['processes'][0]['rss'])"
```
Expected: `sum` ≈ `total` (within ~file_cache slack); procs > 100; top is a real heavy process (e.g., kernel_task or a browser).

- [ ] **Step 4: Commit**

```bash
git add memory-analyzer/scripts/scan.py
git commit -m "feat(memory-analyzer): scan.py macOS 只读扫描"
```

---

## Task 2: `scripts/safety.py` + `tests/test_safety.py` (pure safety logic, TDD)

**Files:**
- Create: `memory-analyzer/scripts/safety.py`
- Create: `memory-analyzer/tests/test_safety.py`

**Interfaces:**
- Produces: `SYSTEM_BLACKLIST` (set of substrings matched against comm/name), `is_system_critical(name, comm) -> bool`, `current_comm(pid) -> str|None`, `build_allowlists(analysis) -> {graceful:set, force:set}`, `validate_action(target, allowlist, mode) -> (ok:bool, reason:str)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_safety.py
import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from safety import is_system_critical, build_allowlists, validate_action

def test_system_critical_kernel():
    assert is_system_critical("kernel_task", "/kernel_task") is True

def test_system_critical_windowserver():
    assert is_system_critical("WindowServer", "/WindowServer") is True

def test_user_app_not_critical():
    assert is_system_critical("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") is False

def test_build_allowlists():
    analysis = {"tiers": {
        "green": [{"graceful_targets":[{"pid":411,"comm":"/x/mds_stores","name":"mds_stores","kind":"process"}],
                   "force_targets":[]}],
        "yellow": [{"graceful_targets":[{"pid":1234,"comm":"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome","name":"Google Chrome","kind":"app"}],
                    "force_targets":[{"pid":1234,"comm":"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome","name":"Google Chrome","kind":"app"}]}],
        "red": [{"name":"kernel_task"}]}}
    al = build_allowlists(analysis)
    assert (411, "/x/mds_stores") in al["graceful"]
    assert (1234, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") in al["graceful"]
    assert (1234, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome") in al["force"]

def test_validate_unknown_pid_rejected():
    al = {"graceful": {(1234, "/apps/C")}, "force": set()}
    ok, reason = validate_action({"pid": 9999, "comm": "/apps/C"}, al, "graceful")
    assert ok is False
    assert "白名单" in reason or "变更" in reason

def test_validate_wrong_comm_rejected(monkeypatch):
    # pid 在白名单但当前 comm 不符（PID 被重用）→ 必须拒绝
    al = {"graceful": {(1234, "/apps/Chrome")}, "force": set()}
    monkeypatch.setattr("safety.current_comm", lambda pid: "/kernel_task")  # pid 1234 现在是 kernel_task
    ok, reason = validate_action({"pid": 1234, "comm": "/apps/Chrome"}, al, "graceful")
    assert ok is False
    assert "变更" in reason

def test_validate_blacklisted_even_if_in_allowlist(monkeypatch):
    al = {"graceful": {(1, "/sbin/launchd")}, "force": set()}
    monkeypatch.setattr("safety.current_comm", lambda pid: "/sbin/launchd")
    ok, reason = validate_action({"pid": 1, "comm": "/sbin/launchd"}, al, "graceful")
    assert ok is False
    assert "系统" in reason
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd memory-analyzer && python3 -m pytest tests/test_safety.py -v
```
Expected: FAIL (ImportError / module has no attribute).

- [ ] **Step 3: Write `scripts/safety.py`**

```python
"""memory-analyzer 安全逻辑（纯函数，可测）。macOS/Windows 共用判定规则。"""
import subprocess

# 系统关键进程：comm 或 name 命中任一即视为 🔴 永不可动作（双保险，即使被误分级也拦）
SYSTEM_BLACKLIST = [
    "kernel_task", "launchd", "WindowServer", "loginwindow", "Dock",
    "SystemUIServer", "Finder", "coreaudiod", "bluetoothd", "thermald",
    "cfprefsd", "distnoted", "SecInit", "trustd", "runningboardd",
    # Windows
    "System", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe",
]

def is_system_critical(name, comm):
    hay = f"{name} {comm}".lower()
    return any(b.lower() in hay for b in SYSTEM_BLACKLIST)

def current_comm(pid):
    """返回 pid 当前的 comm（ps -p）；进程不在则返回 None。macOS 实现。"""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                             capture_output=True, text=True, check=False).stdout
        out = out.strip()
        return out or None
    except Exception:
        return None

def build_allowlists(analysis):
    g, f = set(), set()
    for tier in ("green", "yellow"):
        for item in analysis.get("tiers", {}).get(tier, []):
            for t in item.get("graceful_targets", []):
                g.add((t["pid"], t["comm"]))
            for t in item.get("force_targets", []):
                f.add((t["pid"], t["comm"]))
    return {"graceful": g, "force": f}

def validate_action(target, allowlists, mode):
    """六层校验：mode→白名单、(pid,comm)∈白名单、当前comm匹配扫描comm、非系统关键。"""
    if mode not in ("graceful", "force"):
        return False, "未知动作模式"
    al = allowlists["graceful"] if mode == "graceful" else allowlists["force"]
    key = (target["pid"], target["comm"])
    if key not in al:
        return False, "目标不在白名单"
    live = current_comm(target["pid"])
    if live is None:
        return False, "进程已退出（已变更）"
    if live != target["comm"]:
        return False, "进程已变更（pid 可能被重用），已拒绝"
    if is_system_critical(target.get("name", ""), live):
        return False, "系统关键进程，禁止动作"
    return True, "ok"
```

- [ ] **Step 4: Run tests, verify pass**

```bash
python3 -m pytest tests/test_safety.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add memory-analyzer/scripts/safety.py memory-analyzer/tests/test_safety.py
git commit -m "feat(memory-analyzer): safety.py 安全逻辑 + 单测"
```

---

## Task 3: `assets/report_template.html` (shared visualization)

**Files:**
- Create: `memory-analyzer/assets/report_template.html`

**Interfaces:**
- Consumes: two placeholder tokens replaced by `server.py`/`build_report.py`:
  - `__REPORT_DATA__` → JSON-stringified analysis object.
  - `__DELETE_CONFIG__` → `null` (static) or `{"token":"...","endpoint":"/action"}` (server).
- Produces: renders memory bar, ranking, tier cards, and wires action buttons iff `__DELETE_CONFIG__` is not null AND item has `graceful_targets`/`force_targets`.

- [ ] **Step 1: Write the template** — structure spec + required JS (build the CSS to this design)

HTML skeleton (Chinese UI, dark-friendly, no external deps):

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>内存与进程分析报告</title>
<style>
  /* 设计令牌：参考 dataviz skill 的中性调色板；绿黄红三色用于分级。
     :root 定义 --bg --fg --muted --card --green --yellow --red --blue --gray
     进度条用 flex 分段；卡片可折叠 <details>；按钮 .btn .btn-graceful .btn-force .btn-copy */
</style>
</head>
<body>
  <header><h1>内存与进程分析报告</h1><div id="sysinfo"></div></header>
  <section id="overview"><!-- 内存总览：总量 + 分段条 + swap 高亮 --></section>
  <section id="ranking"><!-- Top N 应用榜 --></section>
  <section id="advice"><!-- summary.top_targets + highest_risk --></section>
  <section id="tiers"><!-- 🟢🟡🔴 <details> 卡片 --></section>
  <section id="longterm"><!-- summary.long_term --></section>
  <script>
    const DATA = __REPORT_DATA__;
    const ACT = __DELETE_CONFIG__;   // null 或 {token, endpoint}

    // 内存总览分段条：按 system.mem 各分类占比着色（app_memory蓝/compressed/文件缓存/wired/free），swap 单独高亮条
    // 排行榜：ranking[] 一行 = 名 + 聚合内存条 + cpu% + tier 色点
    // 三色卡片：每个 tier item 渲染 <details>：name/desc/mem/risk + 命令块(可复制) + 动作按钮
    //   按钮出现条件：ACT && item.graceful_targets?.length → 「优雅退出」; item.force_targets?.length → 「强制结束」

    function fmtBytes(n){ /* 1000 进制 GB/MB */ }
    async function doAction(mode, targets, btn){
      if(!ACT){ return; }
      const sure = confirm(mode==='force'
        ? '⚠️ 强制结束会立即杀死进程，可能丢失未保存数据。确认？'
        : '确认优雅退出？');
      if(!sure) return;
      btn.disabled = true;
      const r = await fetch(ACT.endpoint, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({token:ACT.token, mode, targets})
      });
      const res = await r.json();
      if(res.ok){ btn.textContent = '已完成 ✓'; }
      else { btn.textContent = '失败：'+(res.reason||''); btn.disabled=false; }
    }
    // 渲染入口：render() 填充各 section，给按钮绑 doAction
    render();
  </script>
</body>
</html>
```

**Required rendering rules (implement in `render()`):**
1. Overview: segmented bar from `system.mem` (app_memory / compressed / file_cache / wired / free) sized to `total_mem`; a second slim bar for `swap` (red-highlight if `swap.used > 20% swap.total`).
2. Ranking: each `ranking[]` row shows name, aggregate_mem bar (rel to max), `cpu`%, tier dot.
3. Tiers: for each of green/yellow/red, a `<details open>` per item. Red items render **no buttons**. Green/yellow render a copyable `command` block; if `ACT`, render buttons per the rules above. Button `onclick` calls `doAction(mode, item.graceful_targets||item.force_targets, this)`.
4. Advice: `summary.top_targets` as a checklist; `summary.highest_risk` in a warning callout. Longterm: `summary.long_term` bullet list.

- [ ] **Step 2: Manual render check** (template alone can't run; verified in T4 with server). Just ensure the file is well-formed HTML with both tokens present.

```bash
grep -c "__REPORT_DATA__\|__DELETE_CONFIG__" memory-analyzer/assets/report_template.html
```
Expected: `2` (both tokens present).

- [ ] **Step 3: Commit**

```bash
git add memory-analyzer/assets/report_template.html
git commit -m "feat(memory-analyzer): report_template.html 可视化模板"
```

---

## Task 4: `scripts/server.py` (macOS, guarded action server)

**Files:**
- Create: `memory-analyzer/scripts/server.py`
- Modify: none (imports `safety`).

**Interfaces:**
- Consumes: `safety.build_allowlists`, `safety.validate_action`, `safety.SYSTEM_BLACKLIST`; the template; analysis JSON path (argv[1]).
- Produces: `GET /` (rendered report), `POST /action` (`{token, mode, targets:[{pid,comm,name,kind}]}` → `{ok, done, failed}`).

- [ ] **Step 1: Write `scripts/server.py`** (complete)

```python
#!/usr/bin/env python3
"""memory-analyzer 交互服务 (macOS)。默认模式：带动作按钮。
用法: python3 server.py <analysis.json> [--no-open]
绑定 127.0.0.1 + 随机端口 + 随机 token；Ctrl+C 退出。"""
import argparse, json, os, secrets, signal, subprocess, sys, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import safety  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "assets", "report_template.html")

def graceful(t):
    """优雅退出：app→osascript quit(3s 超时)，所有→SIGTERM 兜底。"""
    pid = t["pid"]
    if t.get("kind") == "app":
        try:
            subprocess.run(["osascript", "-e", f'tell application "{t["name"]}" to quit'],
                           timeout=3, capture_output=True)
        except Exception:
            pass
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False

def force(t):
    """强制结束：SIGKILL 单 pid（不杀进程组）。"""
    try:
        os.kill(t["pid"], signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False

def make_handler(analysis, allowlists, token):
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _host_ok(self):
            h = self.headers.get("Host", "")
            return h.startswith("127.0.0.1") or h.startswith("localhost")

        def do_GET(self):
            if not self._host_ok():
                self.send_error(403); return
            if urlparse(self.path).path not in ("/", "/index.html"):
                self.send_error(404); return
            html = (tpl
                    .replace("__REPORT_DATA__", json.dumps(analysis, ensure_ascii=False))
                    .replace("__DELETE_CONFIG__", json.dumps({"token": token, "endpoint": "/action"})))
            b = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            if not self._host_ok():
                self.send_error(403); return
            if urlparse(self.path).path != "/action":
                self.send_error(404); return
            length = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(length) or "{}")
            except Exception:
                self._json(400, {"ok": False, "reason": "请求格式错误"}); return
            if req.get("token") != token:
                self._json(403, {"ok": False, "reason": "token 无效"}); return
            mode = req.get("mode")
            targets = req.get("targets", [])
            done, failed = [], []
            fn = graceful if mode == "graceful" else force if mode == "force" else None
            if fn is None:
                self._json(400, {"ok": False, "reason": "未知动作模式"}); return
            for t in targets:
                ok, reason = safety.validate_action(t, allowlists, mode)
                if not ok:
                    failed.append({"pid": t["pid"], "name": t.get("name"), "reason": reason})
                    continue
                if fn(t):
                    done.append({"pid": t["pid"], "name": t.get("name"), "action": mode})
                else:
                    failed.append({"pid": t["pid"], "name": t.get("name"), "reason": "进程已退出"})
            self._json(200, {"ok": not failed, "done": done, "failed": failed})

        def _json(self, code, obj):
            b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    return H

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_json")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    with open(args.analysis_json, encoding="utf-8") as f:
        analysis = json.load(f)
    allowlists = safety.build_allowlists(analysis)
    token = secrets.token_urlsafe(24)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(analysis, allowlists, token))
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f" serving {url}  (token ok)  Ctrl+C 退出", file=sys.stderr)
    if not args.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: End-to-end test on live Mac**

Prepare a minimal analysis JSON by hand to exercise the server (full agent-driven classification is a doc concern, not code):

```bash
cat > /tmp/mem_analysis_test.json <<'EOF'
{
  "generated_at":"2026-07-29T00:00:00",
  "system":{"os":"darwin","os_version":"15","total_mem":17179869184,
    "mem":{"wired":3000000000,"compressed":2000000000,"app_memory":5000000000,"file_cache":4000000000,"free":3179869184},
    "swap":{"used":0,"total":0}},
  "summary":{"total_reclaimable":7000000000,"tier_stats":{"green":1800000000,"yellow":5200000000,"red":3000000000,"system_other":4000000000},
    "top_targets":["测试用"],"highest_risk":"仅测试","long_term":["测试"]},
  "ranking":[{"name":"测试应用","aggregate_mem":1000000000,"child_count":1,"cpu":1.0,"tier":"yellow"}],
  "tiers":{"green":[],"yellow":[{"name":"测试应用","desc":"测试","mem":1000000000,"risk":"低",
    "graceful_targets":[{"pid":<填一个真实可退的用户进程pid>,"name":"测试","comm":"<填该pid的ps comm>","kind":"process"}],
    "force_targets":[],"command":"kill -TERM <pid>"}],"red":[{"name":"kernel_task","desc":"内核","mem":3000000000,"why_no_button":"崩溃系统","indirect_release":null}]}
}
EOF
python3 scripts/server.py /tmp/mem_analysis_test.json
```
Expected: browser opens; memory bar renders; 「测试应用」 has 优雅退出 button; kernel_task card has NO button; clicking 优雅退出 on the test pid terminates it; tampering with the pid in devtools to a mismatched comm returns `进程已变更`.

- [ ] **Step 3: Commit**

```bash
git add memory-analyzer/scripts/server.py
git commit -m "feat(memory-analyzer): server.py 受防护动作服务（PID 双键）"
```

---

## Task 5: `scripts/build_report.py` (macOS, static read-only HTML)

**Files:**
- Create: `memory-analyzer/scripts/build_report.py`

- [ ] **Step 1: Write `scripts/build_report.py`**

```python
#!/usr/bin/env python3
"""memory-analyzer 静态报告 (macOS)。只读 HTML，无动作按钮（file:// 无法发请求）。
用法: python3 build_report.py <analysis.json> [out.html]"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "report_template.html")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_json")
    ap.add_argument("out", nargs="?", default=os.path.expanduser("~/Desktop/memory-report.html"))
    args = ap.parse_args()
    with open(args.analysis_json, encoding="utf-8") as f:
        analysis = json.load(f)
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    html = (tpl
            .replace("__REPORT_DATA__", json.dumps(analysis, ensure_ascii=False))
            .replace("__DELETE_CONFIG__", "null"))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f" 已写出: {args.out}", file=sys.stderr)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify static mode has no buttons**

```bash
python3 scripts/build_report.py /tmp/mem_analysis_test.json /tmp/static.html
grep -c "doAction\|__DELETE_CONFIG__" /tmp/static.html   # 模板里 doAction 仍存在但 ACT=null 不触发
python3 -c "import re;h=open('/tmp/static.html').read();print('DELETE_CONFIG is', re.search(r'__DELETE_CONFIG__',h) is None)"
```
Expected: `__DELETE_CONFIG__` token fully replaced (grep for the raw token returns none / second print `None`).

- [ ] **Step 3: Commit**

```bash
git add memory-analyzer/scripts/build_report.py
git commit -m "feat(memory-analyzer): build_report.py 静态只读 HTML"
```

---

## Task 6: `references/macos.md` + `references/windows.md`

**Files:**
- Create: `memory-analyzer/references/macos.md`
- Create: `memory-analyzer/references/windows.md`

- [ ] **Step 1: Write `references/macos.md`** — content: (a) macOS memory model explained (wired/compressed/app/file_cache/free, swap, "空闲=浪费" honesty); (b) the 🔴 system-critical list (kernel_task, launchd, WindowServer, loginwindow, Dock, Finder, SystemUIServer, coreaudiod, bluetoothd, thermald…); (c) 🟢 safe-restart candidates (mds_stores/mdworker_shared and other launchd KeepAlive daemons — how to verify KeepAlive); (d) 🟡 = user apps default; (e) how to read `ps`/`vm_stat`/`sysctl vm.swapusage`; (f) bundle_id derivation note.

- [ ] **Step 2: Write `references/windows.md`** — content: (a) Windows memory model (WorkingSet vs PrivateMemory, commit, standby list ≈ file cache, "free" semantics, pagefile); (b) 🔴 list (System, smss, csrss, wininit, winlogon, services, lsass, svchost(system), dwm, explorer — note explorer restartable but warn); (c) 🟢 candidates (SearchIndexer, Windows Search service helpers — via Get-Service StartType/Auto); (d) 🟡 = user apps; (e) PowerShell commands (`Get-CimInstance Win32_Process`, `Win32_OperatingSystem`, `Win32_PageFileUsage`); (f) **header banner: 本文件为代码就位、未在真实 Windows 实测**.

- [ ] **Step 3: Commit**

```bash
git add memory-analyzer/references/
git commit -m "docs(memory-analyzer): references/macos.md + windows.md 分级参照"
```

---

## Task 7: `README.md` + `SKILL.md` + `AGENTS.md` (agent-agnostic docs)

**Files:**
- Create: `memory-analyzer/README.md` (source of truth)
- Create: `memory-analyzer/SKILL.md` (Claude frontmatter + same workflow)
- Create: `memory-analyzer/AGENTS.md` (cross-agent pointer)

- [ ] **Step 1: Write `README.md`** with these sections (agent-agnostic, Chinese):
  1. **它是什么** — 内存/进程分析，三色分级，网页一键安全动作。
  2. **运行时** — macOS 用 Python（scripts/*.py），Windows 用 PowerShell（scripts/*.ps1）；零第三方依赖。
  3. **铁律** — 扫描只读；动作只走 server；系统进程永不可动；估算标注。
  4. **工作流（任何 agent 照此执行）**：
     1. 扫描：mac `python3 scripts/scan.py > /tmp/mem_scan.json` / win `pwsh scripts/scan.ps1 > $env:TEMP\mem_scan.json`
     2. 读 `references/<os>.md` + scan.json，按父进程聚合应用，Top N + 三色分级，写 `/tmp/mem_analysis.json`（analysis JSON 契约见本文件附录）。
     3. 开网页：默认 `python3 scripts/server.py /tmp/mem_analysis.json`（带动作）；分享用 `build_report.py`（只读）。
     4. 聊天小结：结论先行（可释放约多少、先处理哪 2-3 个、最高风险）。
  5. **分级标准** — 🟢/🟡/🔴 定义表 + 按钮 wiring（graceful_targets/force_targets）。
  6. **失败码**（scan：0/2/3；server 返回 ok/reason）。
  7. **附录：analysis JSON 契约**（贴本 plan 的 analysis JSON 示例）。
  8. **执行准则** — 跑完整流程再汇报，中途别反复问用户；仅遇阻塞（OS 不支持、扫描失败）才打断。

- [ ] **Step 2: Write `SKILL.md`** — Claude frontmatter:
  ```yaml
  ---
  name: memory-analyzer
  description: |
    对 macOS/Windows 做只读的**内存与运行中进程**分析……（触发词：内存占用高/电脑卡慢/哪个进程吃内存/释放内存/关掉某应用/结束某进程/看下内存进程……；排除：明显指磁盘→storage-analyzer）。正文流程同 README.md。
  ---
  ```
  Body: brief restatement pointing to README.md for the full workflow + the 4-step commands inline (so Claude can act without leaving the file).

- [ ] **Step 3: Write `AGENTS.md`** — short: "这是一个 agent 驱动的内存/进程分析工具。完整工作流见 `README.md`，脚本在 `scripts/`（macOS=.py，Windows=.ps1）。任何能跑 shell 的 agent 照 README 执行即可。"

- [ ] **Step 4: Commit**

```bash
git add memory-analyzer/README.md memory-analyzer/SKILL.md memory-analyzer/AGENTS.md
git commit -m "docs(memory-analyzer): README/SKILL/AGENTS agent 无关文档"
```

---

## Task 8: PowerShell ports (`scan.ps1`, `server.ps1`, `build_report.ps1`) — UNTESTED

**Files:**
- Create: `memory-analyzer/scripts/scan.ps1`, `server.ps1`, `build_report.ps1`

> **每份文件头部标注：本脚本为代码就位，未在真实 Windows 实测；首次运行需验证进程枚举/内存数值/CloseMainWindow/Stop-Process。**

- [ ] **Step 1: `scan.ps1`** — translation of scan.py: `Get-CimInstance Win32_Process` (ProcessId, ParentProcessId, Name, WorkingSetSize, …) + `Win32_OperatingSystem` (FreePhysicalMemory, TotalVisibleMemorySize) + `Win32_PageFileUsage` (AllocatedBaseSize, CurrentUsage). Output the SAME JSON contract as scan.py to stdout (`ConvertTo-Json -Depth 8 -Compress`). Derive `kind`: if executable path under `\Program Files\` or a known app dir → "app" (best-effort); else "process".

- [ ] **Step 2: `server.ps1`** — translation of server.py: `[System.Net.HttpListener]` on `http://127.0.0.1:<random>/`, random token (`[Web.Security.Cryptography.RandomNumberGenerator]` or GUID-based), GET serves injected template, POST `/action` validates token + mode + per-target `(pid,comm)` allowlist + **PID revalidation via `Get-CimInstance Win32_Process -Filter "ProcessId=$pid"` current Name match** + system blacklist. Actions: graceful = `(Get-Process -Id $pid).CloseMainWindow()` (bg process: `Stop-Process -Id $pid` no -Force); force = `Stop-Process -Id $pid -Force`. Reuse `safety.py`'s SYSTEM_BLACKLIST list (copy into the .ps1).

- [ ] **Step 3: `build_report.ps1`** — translation of build_report.py: load analysis JSON, inject `__REPORT_DATA__`, set `__DELETE_CONFIG__` = `null`, write HTML.

- [ ] **Step 4: Commit** (clearly marked untested)

```bash
git add memory-analyzer/scripts/*.ps1
git commit -m "feat(memory-analyzer): Windows PowerShell 版（scan/server/build_report，未实测）"
```

---

## Task 9: Symlink + end-to-end integration test (macOS)

**Files:**
- Create symlink: `~/.claude/skills/memory-analyzer -> skill-store/memory-analyzer`

- [ ] **Step 1: Symlink into Claude skills**

```bash
ln -s /Users/huangxindi/ai/skill-store/memory-analyzer ~/.claude/skills/memory-analyzer
ls -l ~/.claude/skills/memory-analyzer
```
Expected: symlink shown.

- [ ] **Step 2: Full integration test** — run the real workflow once on this Mac:
  1. `python3 scripts/scan.py > /tmp/mem_scan.json` (valid JSON).
  2. (Agent) classify into `/tmp/mem_analysis.json` per the contract — pick 1 real heavy user app as 🟡, kernel_task as 🔴, one safe daemon as 🟢.
  3. `python3 scripts/server.py /tmp/mem_analysis.json` — verify: page renders; 🟡 app has 优雅退出 + 强制结束; 🔴 has no button; 🟢 has buttons.
  4. Click 优雅退出 on the 🟡 test app → app quits, button shows ✓.
  5. PID-reuse guard: in a second terminal, note a 🟡 pid, kill it manually, start a different process reusing nothing → click button → server returns 进程已变更.
  6. `python3 -m pytest tests/ -v` → all green.

- [ ] **Step 3: Update skill-store README skill index** (add memory-analyzer row to `/Users/huangxindi/ai/skill-store/README.md`).

- [ ] **Step 4: Commit**

```bash
git add memory-analyzer README.md
git commit -m "feat(memory-analyzer): 接入 ~/.claude/skills + 端到端验证 + README 索引"
```

---

## Self-Review (completed)

**1. Spec coverage:** §1-2 goal/scope → all tasks. §3 runtime (py/ps1) → T1/T4/T5/T8. §4 data flow → T1/T4 + README(T7). §5 file tree → all. §5.1 agent-agnostic → T7. §6 scan schema → T1. §7 tiers → T6/T7/contract. §8 six-layer safety + PID dual-key → T2 (tested) + T4. §9 two actions → T2/T4 + contract. §10 memory honesty → T6. §11 template read-order → T3. §12 docs → T7. §13 exit codes → T1/README. §14 testing → T2/T4/T9. §15 deliverables → T1-T9. ✓ No gaps.

**2. Placeholder scan:** Template CSS is described via design tokens (intentional — visual built to spec in T3, not a logic placeholder); PowerShell tasks are explicitly UNTESTED ports with translation spec (honest, per spec §3). No "TBD/TODO". ✓

**3. Type consistency:** target shape `{pid, comm, name, kind}` is identical in contract, safety.build_allowlists, validate_action, server, and template doAction. `graceful_targets`/`force_targets` keys match across contract/template/server. `__REPORT_DATA__`/`__DELETE_CONFIG__` tokens match across template/server/build_report. ✓
