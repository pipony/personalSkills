"""memory-analyzer 安全逻辑（纯函数，可测）。macOS/Windows 共用判定规则。

核心：进程工具独有的致命坑是 PID 复用——扫描时 pid 1234 是 Slack，点击时它
已退出、该 pid 被 kernel_task 重用，直接杀会崩系统。所以每个动作都要重新解析
pid 当前的 comm，必须与扫描时记录的一致才执行。
"""
import subprocess

# 系统关键进程：comm 或 name 命中任一即视为 🔴 永不可动作。
# 双保险：即使被误分级，动作时也再拦一次。
SYSTEM_BLACKLIST = [
    # macOS
    "kernel_task", "launchd", "WindowServer", "loginwindow", "Dock",
    "SystemUIServer", "Finder", "coreaudiod", "bluetoothd", "thermald",
    "cfprefsd", "distnoted", "trustd", "runningboardd", "amfid",
    # Windows
    "System", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe",
]


def is_system_critical(name, comm):
    """name 或 comm 命中黑名单即返回 True。"""
    hay = f"{name} {comm}".lower()
    return any(b.lower() in hay for b in SYSTEM_BLACKLIST)


def current_comm(pid):
    """返回 pid 当前的 comm（macOS: ps -p）；进程不在则返回 None。Windows 版见 server.ps1。"""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                             capture_output=True, text=True, check=False).stdout
        out = out.strip()
        return out or None
    except Exception:
        return None


def build_allowlists(analysis):
    """从 analysis JSON 的 tiers 构建 GRACEFUL/FORCE 两套白名单。
    白名单元素 = (pid, comm) 二元组。"""
    g, f = set(), set()
    for tier in ("green", "yellow"):
        for item in analysis.get("tiers", {}).get(tier, []):
            for t in item.get("graceful_targets", []):
                g.add((t["pid"], t["comm"]))
            for t in item.get("force_targets", []):
                f.add((t["pid"], t["comm"]))
    return {"graceful": g, "force": f}


def validate_action(target, allowlists, mode):
    """校验单个动作目标。返回 (ok, reason)。
    校验链：mode 合法 → (pid,comm) 在对应白名单 → 当前 comm 与扫描 comm 一致 → 非系统关键。"""
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
