#!/usr/bin/env python3
"""memory-analyzer 交互服务 (macOS)。默认模式：带动作按钮。
用法: python3 server.py <analysis.json> [--no-open]
绑定 127.0.0.1 + 随机端口 + 随机 token；Ctrl+C 退出。

六层防护 + PID+comm 双键（见 safety.validate_action）：
Host 头 → token → mode → 白名单 → 当前 comm 与扫描 comm 一致 → 非系统关键。"""
import argparse, json, os, secrets, signal, subprocess, sys, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import safety  # noqa: E402

TEMPLATE = os.path.join(HERE, "..", "assets", "report_template.html")


def graceful(t):
    """优雅退出：app→osascript quit(3s 超时)，统一 SIGTERM 兜底。"""
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
    """强制结束：SIGKILL 单 pid（不杀整个进程组，避免误伤）。"""
    try:
        os.kill(t["pid"], signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False


def make_handler(analysis, allowlists, token):
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    injected = (tpl
                .replace("__REPORT_DATA__", json.dumps(analysis, ensure_ascii=False))
                .replace("__DELETE_CONFIG__", json.dumps({"token": token, "endpoint": "/action"})))

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _host_ok(self):
            h = self.headers.get("Host", "")
            return h.startswith("127.0.0.1") or h.startswith("localhost")

        def do_GET(self):
            if not self._host_ok():
                self.send_error(403); return
            if urlparse(self.path).path not in ("/", "/index.html"):
                self.send_error(404); return
            b = injected.encode("utf-8")
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
            fn = graceful if mode == "graceful" else force if mode == "force" else None
            if fn is None:
                self._json(400, {"ok": False, "reason": "未知动作模式"}); return
            done, failed = [], []
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
    ap = argparse.ArgumentParser(description="memory-analyzer 交互服务（macOS）")
    ap.add_argument("analysis_json")
    ap.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()
    with open(args.analysis_json, encoding="utf-8") as f:
        analysis = json.load(f)
    allowlists = safety.build_allowlists(analysis)
    token = secrets.token_urlsafe(24)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(analysis, allowlists, token))
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"  报告: {url}\n  token: 已启用  ·  Ctrl+C 退出", file=sys.stderr, flush=True)
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。", file=sys.stderr)
        srv.shutdown()


if __name__ == "__main__":
    main()
