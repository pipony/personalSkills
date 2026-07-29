#!/usr/bin/env python3
"""memory-analyzer 规则分类器 (macOS)。scan.json → analysis.json。

既给 agent 当参考，也供 server 的 /refresh 实时刷新（脱离 agent 也能出报告）。
规则（确定性）：
- 🔴 系统关键：命中 safety.SYSTEM_BLACKLIST 或 app_root 在 /System/ 下；另把大体量系统进程列入展示（无按钮）。
- 🟢 可安全退出：已知 launchd KeepAlive 自重启守护（mds_stores 等）。
- 🟡 谨慎退出：其余用户应用（/Applications 下、主进程、聚合内存 ≥ 阈值）+ 大体量用户进程。

用法: python3 classify.py <scan.json> [analysis.json]   （默认读 /tmp/mem_scan.json，写 /tmp/mem_analysis.json）"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from safety import is_system_critical  # noqa: E402

SAFE_RESTART = {"mds_stores", "mdworker_shared", "mds"}
MIN_APP_MEM = 80 * 10**6        # 应用聚合内存阈值（进 🟡）
MIN_PROC_MEM = 150 * 10**6      # 非 app 用户进程阈值（进 🟡）
RED_DISPLAY_MEM = 100 * 10**6   # 系统进程展示阈值（进 🔴 仅展示）
RANK_TOP = 12


def _tgt(p, kind):
    return [{"pid": p["pid"], "name": p["name"], "comm": p["comm"], "kind": kind}]


def _yellow(name, desc, mem, main, kind, nproc, risk="中 — 可能丢失未保存状态"):
    cmd = (f"osascript -e 'tell application \"{name}\" to quit'" if kind == "app"
           else f"kill -TERM {main['pid']}")
    return {"name": name, "desc": desc, "mem": mem, "risk": risk,
            "graceful_targets": _tgt(main, kind), "force_targets": _tgt(main, kind), "command": cmd,
            "child_count": nproc}


def classify_scan(scan):
    ps = scan["processes"]
    sysinfo = scan["system"]
    home_apps = os.path.expanduser("~/Applications")

    # 1) 按 app_root 聚合应用
    apps = {}
    for p in ps:
        ar = p.get("app_root")
        if not ar:
            continue
        g = apps.setdefault(ar, {"main": None, "all": [], "name": p["name"]})
        g["all"].append(p)
        if p.get("is_main_app") and not g["main"]:
            g["main"] = p

    green, yellow, red = [], [], []

    for ar, g in apps.items():
        main = g["main"]
        if not main:
            continue
        name = g["name"]
        agg = sum(p["rss"] for p in g["all"])
        crit = is_system_critical(name, main["comm"]) or ar.startswith("/System/")
        if crit:
            if agg >= RED_DISPLAY_MEM:  # 小体量系统应用不展示，避免红档刷屏
                red.append({"name": name, "desc": "系统/核心应用。", "mem": agg,
                            "why_no_button": "系统关键，直接退出可能导致异常。", "indirect_release": None})
        elif name in SAFE_RESTART:
            pass  # 自重启守护统一在下面聚合成一个 🟢 卡片
        elif agg >= MIN_APP_MEM and (ar.startswith("/Applications/") or ar.startswith(home_apps)):
            nproc = len(g["all"])
            yellow.append(_yellow(name, f"应用（{nproc} 个进程聚合）。", agg, main, "app", nproc))

    # 2) 🟢 自重启守护：聚合成一个卡片（mds/mds_stores/mdworker_shared 多进程合一）
    safe_procs = [p for p in ps if p["name"] in SAFE_RESTART]
    if safe_procs:
        smem = sum(p["rss"] for p in safe_procs)
        stg = [{"pid": p["pid"], "name": p["name"], "comm": p["comm"], "kind": "process"} for p in safe_procs]
        green.append({"name": "Spotlight 索引服务 (mds/mdworker)", "desc": "系统索引服务，结束后由 launchd 自动重启；短暂影响搜索。",
                      "mem": smem, "risk": "低 — 自动重启",
                      "graceful_targets": stg, "force_targets": stg,
                      "command": "; ".join(f"kill -TERM {p['pid']}" for p in safe_procs)})

    # 3) 非 app 的用户重型进程（如 claude CLI、docker 守护等）
    seen_pids = {t["pid"] for y in yellow for t in y["graceful_targets"]} | {p["pid"] for p in safe_procs}
    for p in ps:
        if p.get("kind") == "app" or p["pid"] in seen_pids or p["name"] in SAFE_RESTART:
            continue
        nm = p["name"]
        if is_system_critical(nm, p["comm"]):
            if p["rss"] >= RED_DISPLAY_MEM:
                red.append({"name": nm, "desc": "系统关键进程。", "mem": p["rss"],
                            "why_no_button": "杀掉会崩溃/注销/重启。", "indirect_release": None})
            continue
        if p["rss"] >= MIN_PROC_MEM and p.get("user") not in ("root",):
            yellow.append(_yellow(nm, "后台进程。", p["rss"], p, "process", 1))

    yellow.sort(key=lambda x: x["mem"], reverse=True)
    green.sort(key=lambda x: x["mem"], reverse=True)
    red.sort(key=lambda x: x["mem"], reverse=True)

    reclaim = sum(y["mem"] for y in yellow) + sum(g["mem"] for g in green)
    ranking = ([{"name": y["name"], "aggregate_mem": y["mem"],
                 "child_count": y.get("child_count", 1), "cpu": 0.0, "tier": "yellow"} for y in yellow]
               + [{"name": r["name"], "aggregate_mem": r["mem"], "child_count": 1, "cpu": 0.0, "tier": "red"}
                  for r in red[:3]])
    ranking = ranking[:RANK_TOP]

    swap_pct = (100 * sysinfo.get("swap", {}).get("used", 0) / max(1, sysinfo.get("swap", {}).get("total", 1)))
    return {
        "generated_at": "auto-classified",
        "system": sysinfo,
        "summary": {
            "total_reclaimable": reclaim,
            "tier_stats": {"green": sum(g["mem"] for g in green), "yellow": sum(y["mem"] for y in yellow),
                           "red": sum(r["mem"] for r in red),
                           "system_other": max(0, sysinfo["total_mem"] - sysinfo["mem"]["free"])},
            "top_targets": [y["name"] for y in yellow[:3]],
            "highest_risk": "强制结束应用可能丢失未保存数据；结束 claude 等开发进程会中断当前任务。",
            "long_term": ([f"swap 已用 {swap_pct:.0f}%，物理内存偏紧" if swap_pct > 60 else "内存尚有余量"]
                          + ["常驻应用较多，建议关停不用的应用/减少开机自启"]),
        },
        "ranking": ranking,
        "tiers": {"green": green, "yellow": yellow, "red": red},
    }


def main():
    scan_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/mem_scan.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/mem_analysis.json"
    scan = json.load(open(scan_path))
    analysis = classify_scan(scan)
    json.dump(analysis, open(out_path, "w"), ensure_ascii=False)
    t = analysis["tiers"]
    print(f"  分类: 🟢{len(t['green'])} 🟡{len(t['yellow'])} 🔴{len(t['red'])} "
          f"| 可释放 {analysis['summary']['total_reclaimable']/1e9:.2f} GB", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
