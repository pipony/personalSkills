"""classify.py 规则分类测试。"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import classify  # noqa: E402


def mkproc(pid, name, comm, rss, kind="app", app_root=None, is_main_app=False, user="me", ppid=1, cpu=0.0):
    return {"pid": pid, "ppid": ppid, "user": user, "rss": rss, "cpu": cpu,
            "name": name, "comm": comm, "bundle_id": None, "kind": kind,
            "app_root": app_root, "is_main_app": is_main_app}


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.scan = {"system": {"os": "darwin", "os_version": "26", "total_mem": 16 * 10**9,
                                "mem": {"wired": 0, "compressed": 0, "app_memory": 0, "file_cache": 0, "free": 0},
                                "swap": {"used": 0, "total": 0}},
                     "processes": [
                         # 用户应用主进程 + helper（Chrome，应聚合为 1 个 🟡，target=主进程）
                         mkproc(100, "Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                                300 * 10**6, app_root="/Applications/Google Chrome.app", is_main_app=True),
                         mkproc(101, "Google Chrome", "/Applications/Google Chrome.app/.../Helper",
                                200 * 10**6, app_root="/Applications/Google Chrome.app", is_main_app=False),
                         # 微信
                         mkproc(200, "WeChat", "/Applications/WeChat.app/Contents/MacOS/WeChat",
                                150 * 10**6, app_root="/Applications/WeChat.app", is_main_app=True),
                         # 小应用（低于阈值，不进 🟡）
                         mkproc(300, "TinyApp", "/Applications/TinyApp.app/Contents/MacOS/TinyApp",
                                10 * 10**6, app_root="/Applications/TinyApp.app", is_main_app=True),
                         # 系统关键（🔴，无按钮）
                         mkproc(1, "kernel_task", "/kernel_task", 2000 * 10**6, kind="process"),
                         mkproc(2, "WindowServer", "/WindowServer", 300 * 10**6, kind="process"),
                         # 自重启守护（🟢）
                         mkproc(400, "mds_stores", "/System/.../mds_stores", 500 * 10**6, kind="process"),
                         # 用户重型非 app 进程（🟡，如 claude CLI）
                         mkproc(500, "claude", "/usr/local/bin/claude", 400 * 10**6, kind="process"),
                     ]}

    def _run(self):
        return classify.classify_scan(self.scan)

    def test_chrome_aggregated_targets_main(self):
        d = self._run()
        chrome = [y for y in d["tiers"]["yellow"] if y["name"] == "Google Chrome"][0]
        self.assertEqual(chrome["graceful_targets"][0]["pid"], 100)  # 主进程，非 helper
        self.assertIn("child_count", d["ranking"][0] or {}) or None
        # 聚合内存包含 helper
        self.assertGreater(chrome["mem"], 400 * 10**6)

    def test_system_critical_is_red_no_button(self):
        d = self._run()
        names = [r["name"] for r in d["tiers"]["red"]]
        self.assertIn("kernel_task", names)
        self.assertIn("WindowServer", names)
        for r in d["tiers"]["red"]:
            self.assertFalse(r.get("graceful_targets"))

    def test_mds_stores_is_green(self):
        d = self._run()
        # 多个 mds 进程聚合成一个 🟢 卡片
        self.assertEqual(len(d["tiers"]["green"]), 1)
        g = d["tiers"]["green"][0]
        self.assertIn("Spotlight", g["name"])
        self.assertGreater(g["mem"], 400 * 10**6)  # 含 mds_stores 500MB

    def test_tiny_app_excluded(self):
        d = self._run()
        names = [y["name"] for y in d["tiers"]["yellow"]]
        self.assertNotIn("TinyApp", names)  # 低于阈值

    def test_heavy_user_process_is_yellow(self):
        d = self._run()
        names = [y["name"] for y in d["tiers"]["yellow"]]
        self.assertIn("claude", names)

    def test_no_button_when_targets_missing(self):
        d = self._run()
        for y in d["tiers"]["yellow"]:
            self.assertTrue(y.get("graceful_targets"), f"{y['name']} 缺 graceful_targets")


if __name__ == "__main__":
    unittest.main(verbosity=2)
