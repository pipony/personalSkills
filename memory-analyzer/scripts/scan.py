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

    def _to_bytes(token):
        # token 形如 "3072.00M" / "1.5G" / "512K" → 字节
        mm = re.match(r"([0-9.]+)\s*([KMGTP]?)", token.strip())
        if not mm:
            return 0
        val = float(mm.group(1))
        mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4, "P": 1024 ** 5}[mm.group(2)]
        return int(val * mult)

    swap = {"used": 0, "total": 0}
    sw = sh(["sysctl", "-n", "vm.swapusage"])  # "total = 3072.00M  used = 2438.00M  free = 634.00M"
    for key in ("used", "total"):
        mm = re.search(key + r"\s*=\s*([0-9.]+\s*[KMGTP]?)", sw)
        if mm:
            swap[key] = _to_bytes(mm.group(1))
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


def app_info(comm):
    """从 comm 路径反推 app 信息（纯函数，无 subprocess，可测）。
    返回 {name, kind, app_root, is_main_app, bundle_id}。
    - app_root = 最外层 .app 路径（把 helper 归到所属 app，区分 WeChat vs wechatdevtools）。
    - is_main_app = 该 comm 是否就是 app_root 的直接可执行文件（主进程），用于"优雅退出 app"选对 pid。"""
    apps = re.findall(r"(/.+?\.app)(?=/|$)", comm)
    if not apps:
        return {"name": os.path.basename(comm), "kind": "process",
                "app_root": None, "is_main_app": False, "bundle_id": None}
    app_root = apps[0]  # 最外层（非贪婪，第一个即最外）
    name = os.path.basename(app_root)[:-4]  # 去 .app
    # 主进程 = comm 恰好是 app_root/Contents/MacOS/<binary>（无更深嵌套 .app）
    is_main = re.match(r"^" + re.escape(app_root) + r"/Contents/MacOS/[^/]+$", comm) is not None
    return {"name": name, "kind": "app", "app_root": app_root,
            "is_main_app": is_main, "bundle_id": None}


def collect_processes():
    out = sh(["ps", "-axo", "pid,ppid,user,rss,pcpu,comm"])
    procs = []
    for line in out.strip().splitlines()[1:]:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
            user, rss_kb, cpu = parts[2], int(parts[3]), float(parts[4])
        except ValueError:
            continue
        comm = parts[5].strip()
        ai = app_info(comm)
        procs.append({
            "pid": pid, "ppid": ppid, "user": user,
            "rss": rss_kb * 1024, "cpu": cpu,
            "name": ai["name"], "comm": comm, "bundle_id": ai["bundle_id"],
            "kind": ai["kind"], "app_root": ai["app_root"], "is_main_app": ai["is_main_app"],
        })
    procs.sort(key=lambda p: p["rss"], reverse=True)
    return procs


def main():
    if sys.platform != "darwin":
        sys.stderr.write("scan.py 仅支持 macOS；Windows 请用 scan.ps1\n")
        sys.exit(2)
    try:
        doc = {
            "system": {
                "os": "darwin",
                "os_version": sh(["sw_vers", "-productVersion"]).strip(),
                **collect_memory(),
            },
            "processes": collect_processes(),
            "denied": [],
        }
    except Exception as e:
        sys.stderr.write(f"采集失败: {e}\n")
        sys.exit(3)
    json.dump(doc, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
