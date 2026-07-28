"""safety.py 纯函数单测（stdlib unittest，零依赖）。
覆盖：系统黑名单、白名单构建、PID 双键校验。运行: python3 -m unittest tests.test_safety"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import safety  # noqa: E402
from safety import is_system_critical, build_allowlists, validate_action  # noqa: E402


class TestSafety(unittest.TestCase):
    def setUp(self):
        self._orig = safety.current_comm

    def tearDown(self):
        safety.current_comm = self._orig

    def _stub_comm(self, mapping):
        # mapping: pid -> comm 字符串（或 None 表示进程已退出）
        safety.current_comm = lambda pid: mapping.get(pid)

    def test_system_critical_kernel(self):
        self.assertTrue(is_system_critical("kernel_task", "/kernel_task"))

    def test_system_critical_windowserver(self):
        self.assertTrue(is_system_critical("WindowServer", "/WindowServer"))

    def test_user_app_not_critical(self):
        self.assertFalse(is_system_critical(
            "Google Chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))

    def test_build_allowlists(self):
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        analysis = {"tiers": {
            "green": [{"graceful_targets": [{"pid": 411, "comm": "/x/mds_stores", "name": "mds_stores", "kind": "process"}],
                       "force_targets": []}],
            "yellow": [{"graceful_targets": [{"pid": 1234, "comm": chrome, "name": "Google Chrome", "kind": "app"}],
                        "force_targets": [{"pid": 1234, "comm": chrome, "name": "Google Chrome", "kind": "app"}]}],
            "red": [{"name": "kernel_task"}]}}
        al = build_allowlists(analysis)
        self.assertIn((411, "/x/mds_stores"), al["graceful"])
        self.assertIn((1234, chrome), al["graceful"])
        self.assertIn((1234, chrome), al["force"])

    def test_validate_unknown_pid_rejected(self):
        al = {"graceful": {(1234, "/apps/C")}, "force": set()}
        ok, reason = validate_action({"pid": 9999, "comm": "/apps/C"}, al, "graceful")
        self.assertFalse(ok)
        self.assertIn("白名单", reason)

    def test_validate_pid_gone_rejected(self):
        al = {"graceful": {(1234, "/apps/Chrome")}, "force": set()}
        self._stub_comm({1234: None})  # 进程已退出
        ok, reason = validate_action({"pid": 1234, "comm": "/apps/Chrome"}, al, "graceful")
        self.assertFalse(ok)
        self.assertIn("变更", reason)

    def test_validate_wrong_comm_rejected(self):
        # pid 在白名单但当前 comm 不符（PID 被重用成 kernel_task）→ 必须拒绝
        al = {"graceful": {(1234, "/apps/Chrome")}, "force": set()}
        self._stub_comm({1234: "/kernel_task"})
        ok, reason = validate_action({"pid": 1234, "comm": "/apps/Chrome"}, al, "graceful")
        self.assertFalse(ok)
        self.assertIn("变更", reason)

    def test_validate_blacklisted_even_if_in_allowlist(self):
        # 即使误把 launchd 放进白名单，动作时也必须被系统黑名单拦下
        al = {"graceful": {(1, "/sbin/launchd")}, "force": set()}
        self._stub_comm({1: "/sbin/launchd"})
        ok, reason = validate_action({"pid": 1, "comm": "/sbin/launchd"}, al, "graceful")
        self.assertFalse(ok)
        self.assertIn("系统", reason)

    def test_validate_ok(self):
        al = {"graceful": {(1234, "/apps/Chrome")}, "force": set()}
        self._stub_comm({1234: "/apps/Chrome"})
        ok, reason = validate_action({"pid": 1234, "comm": "/apps/Chrome", "name": "Chrome"}, al, "graceful")
        self.assertTrue(ok)

    def test_force_uses_force_allowlist(self):
        # graceful 白名单里的 pid，不能用 force 动作（除非也在 force 白名单）
        al = {"graceful": {(1234, "/apps/C")}, "force": set()}
        self._stub_comm({1234: "/apps/C"})
        ok, reason = validate_action({"pid": 1234, "comm": "/apps/C"}, al, "force")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
