"""scan.py 的 app_info() 推导测试（纯函数，覆盖多进程应用的 main/helper 区分）。"""
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from scan import app_info  # noqa: E402

WX = "/Applications/WeChat.app"
WX_HELPER = (WX + "/Contents/MacOS/WeChatAppEx.app/Contents/Frameworks/"
             "WeChatAppEx Framework.framework/Versions/C/Helpers/"
             "WeChatAppEx Helper (Renderer).app/Contents/MacOS/WeChatAppEx Helper (Renderer)")


class TestAppInfo(unittest.TestCase):
    def test_main_wechat_is_main(self):
        i = app_info(WX + "/Contents/MacOS/WeChat")
        self.assertEqual(i["app_root"], WX)
        self.assertEqual(i["name"], "WeChat")
        self.assertTrue(i["is_main_app"])
        self.assertEqual(i["kind"], "app")

    def test_wechat_helper_is_not_main(self):
        i = app_info(WX_HELPER)
        # helper 仍归属外层 WeChat.app，但不是主进程
        self.assertEqual(i["app_root"], WX)
        self.assertEqual(i["name"], "WeChat")
        self.assertFalse(i["is_main_app"])

    def test_wechatdevtools_is_separate_app(self):
        i = app_info("/Applications/wechatwebdevtools.app/Contents/MacOS/wechatdevtools")
        self.assertEqual(i["app_root"], "/Applications/wechatwebdevtools.app")
        self.assertEqual(i["name"], "wechatwebdevtools")
        self.assertTrue(i["is_main_app"])

    def test_chrome_main(self):
        i = app_info("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        self.assertEqual(i["name"], "Google Chrome")
        self.assertTrue(i["is_main_app"])

    def test_non_app_process(self):
        i = app_info("/usr/bin/python3")
        self.assertEqual(i["kind"], "process")
        self.assertIsNone(i["app_root"])
        self.assertFalse(i["is_main_app"])
        self.assertEqual(i["name"], "python3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
