#!/usr/bin/env python3
"""memory-analyzer 静态报告 (macOS)。只读 HTML，无动作按钮（file:// 无法发请求）。
用法: python3 build_report.py <analysis.json> [out.html]"""
import argparse, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "report_template.html")


def main():
    ap = argparse.ArgumentParser(description="memory-analyzer 静态只读报告（macOS）")
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
    print(f"  已写出: {args.out}", flush=True)


if __name__ == "__main__":
    main()
