#!/usr/bin/env python3
"""
report_to_html.py — 把 skill-architect-mentor 产出的 Markdown 学习报告
转成一份自包含、可离线查看的 HTML（内嵌样式 + 自动目录）。

MD 报告是唯一事实来源；本脚本只做格式转换，保证 HTML 与 MD 内容一致。

用法:
    python3 report_to_html.py <报告.md> [输出.html]
不指定输出时，默认同名 .html，与输入同目录。

依赖 Python markdown 库；缺失时自动安装（--user，失败再试 --break-system-packages）。
"""
import sys
import os
import re
import html


def ensure_markdown():
    try:
        import markdown
        return markdown
    except ImportError:
        import subprocess
        for args in (
            [sys.executable, "-m", "pip", "install", "--user", "markdown"],
            [sys.executable, "-m", "pip", "install", "--break-system-packages", "markdown"],
        ):
            try:
                subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except Exception:
                continue
        try:
            import markdown
            return markdown
        except ImportError:
            sys.exit("[ERROR] 无法加载 markdown 库，自动安装失败。请手动：pip install markdown")


markdown = ensure_markdown()


def normalize_lists(text):
    """在列表块前补分隔空行，确保 markdown 解析器识别列表——否则紧跟段落
    （或紧跟段落式引用行）的列表会被吸收进 <p>，渲染成挤在一起的纯文本。
    同时处理普通列表和「引用块内的列表」(> - item)。跳过 ``` / ~~~ 代码围栏内部。"""
    fence = None
    out = []
    item_re = re.compile(r'^(>?\s*)([-*+]|\d+\.)\s')  # 可选引用前缀 + 列表标记
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            tok = stripped[:3]
            fence = None if fence == tok else (tok if fence is None else fence)
        is_list = fence is None and bool(item_re.match(line))
        if is_list and out:
            prev = out[-1]
            if prev.strip() != "" and not item_re.match(prev):
                # 引用块内的列表用空引用行 ">" 分隔；普通列表用空行 ""
                sep = ">" if (line.lstrip().startswith(">") and prev.lstrip().startswith(">")) else ""
                out.append(sep)
        out.append(line)
    return "\n".join(out)


def md_to_html(text, with_toc=False):
    """normalize_lists + markdown 转换。主报告 with_toc=True 以给标题加 id。"""
    exts = ["tables", "fenced_code", "sane_lists"]
    kwargs = {"extensions": exts}
    if with_toc:
        exts.append("toc")
        kwargs["extension_configs"] = {"toc": {"toc_depth": "2-3"}}
    return markdown.markdown(normalize_lists(text), **kwargs)


CSS = """
:root {
  --fg: #1f2328; --muted: #57606a; --bg: #ffffff; --soft: #f6f8fa;
  --border: #d0d7de; --accent: #0969da; --code-bg: #f6f8fa;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; font-size: 16px; line-height: 1.7; color: var(--fg); background: var(--soft);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
}
.page { max-width: 980px; margin: 0 auto; background: var(--bg); display: flex; min-height: 100vh; }
.toc {
  flex: 0 0 240px; width: 240px; padding: 32px 20px; background: var(--soft);
  border-right: 1px solid var(--border); position: sticky; top: 0; align-self: flex-start;
  max-height: 100vh; overflow: auto;
}
.toc-title { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin-bottom: 12px; }
.toc a {
  display: block; color: var(--muted); text-decoration: none; font-size: 13.5px;
  padding: 3px 0 3px 10px; border-left: 2px solid transparent;
}
.toc a.toc-h3 { padding-left: 22px; font-size: 13px; }
.toc a:hover { color: var(--accent); border-left-color: var(--accent); }
.content { flex: 1; min-width: 0; padding: 40px 48px 80px; }
.content h1 { font-size: 1.9em; line-height: 1.3; margin: 0 0 8px; border-bottom: 2px solid var(--border); padding-bottom: 12px; }
.content h2 { font-size: 1.4em; margin: 40px 0 14px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.content h3 { font-size: 1.15em; margin: 26px 0 10px; }
.content p { margin: 12px 0; }
.content ul, .content ol { padding-left: 1.6em; margin: 12px 0; }
.content li { margin: 4px 0; }
.content blockquote {
  margin: 16px 0; padding: 10px 16px; background: var(--soft); border-left: 4px solid var(--accent);
  color: var(--muted); border-radius: 0 6px 6px 0;
}
.content blockquote p { margin: 4px 0; }
.content code { font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: .9em; background: var(--code-bg); padding: 2px 6px; border-radius: 4px; }
.content pre { background: #1e1e2e; color: #e6e6e6; padding: 16px 18px; border-radius: 8px; overflow-x: auto; line-height: 1.5; }
.content pre code { background: none; padding: 0; color: inherit; font-size: .88em; }
.content table { border-collapse: collapse; width: 100%; margin: 16px 0; font-size: .95em; }
.content th, .content td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; vertical-align: top; }
.content th { background: var(--soft); font-weight: 600; }
.content tr:nth-child(even) td { background: #fbfcfd; }
.content hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
.content a { color: var(--accent); }
.content details.src-file { margin: 12px 0; border: 1px solid var(--border); border-radius: 6px; background: var(--soft); }
.content details.src-file > summary { cursor: pointer; padding: 8px 12px; font-weight: 500; }
.content details.src-file[open] > summary { border-bottom: 1px solid var(--border); }
.content details.src-file .src-md { padding: 12px 16px; max-height: 70vh; overflow: auto; background: var(--bg); }
.content details.src-file > pre { margin: 0; padding: 12px 16px; max-height: 70vh; overflow: auto; background: #1e1e2e; color: #e6e6e6; border-radius: 0 0 6px 6px; }
@media (max-width: 720px) {
  .page { flex-direction: column; }
  .toc { position: static; width: 100%; max-height: none; border-right: none; border-bottom: 1px solid var(--border); }
  .content { padding: 24px 20px 60px; }
}
@media print { .toc { display: none; } body { background: #fff; } }
"""

HTML_DOC = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<div class="page">
<nav class="toc">
  <div class="toc-title">目录</div>
  {toc}
</nav>
<main class="content">
{body}
</main>
</div>
</body>
</html>
"""


def build_appendix(skill_dir):
    """把被分析 skill 目录里的每个源文件嵌进可折叠 <details>，附在报告末尾。
    .md 文件渲染成 HTML 便于直接读；其它文件用 <pre> 原样显示。"""
    if not skill_dir or not os.path.isdir(skill_dir):
        return ""
    skip_dirs = {".git", "node_modules", "__pycache__"}
    blocks = []
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in sorted(files):
            if fn in (".DS_Store",):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, skill_dir)
            try:
                with open(full, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue  # 跳过二进制 / 不可读文件
            if fn.lower().endswith(".md"):
                inner = md_to_html(content)
                rendered = f'<div class="src-md">{inner}</div>'
            else:
                rendered = f'<pre><code>{html.escape(content)}</code></pre>'
            blocks.append(
                f'<details class="src-file"><summary><code>{html.escape(rel)}</code></summary>{rendered}</details>'
            )
    if not blocks:
        return ""
    out = '\n<h2 id="原文附录">原文附录（折叠阅读）</h2>'
    out += "\n<p>下面是被分析 skill 的原始文件，点击文件名展开直接阅读（.md 已渲染，其它为原样代码）。</p>"
    return out + "\n" + "\n".join(blocks)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="把 skill 学习报告 .md 转成自包含 HTML")
    ap.add_argument("report", help="报告 .md 文件")
    ap.add_argument("output", nargs="?", help="输出 .html（默认同名 .html）")
    ap.add_argument("--skill-dir", help="被分析 skill 的目录；给出则在 HTML 末尾追加「原文附录（折叠）」")
    args = ap.parse_args()

    src = args.report
    out = args.output
    if not os.path.exists(src):
        sys.exit(f"[ERROR] 找不到输入文件: {src}")

    with open(src, "r", encoding="utf-8") as f:
        md_text = f.read()

    body = md_to_html(md_text, with_toc=True)
    body += build_appendix(args.skill_dir)

    m = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else os.path.basename(src)

    toc_items = []
    for level, tid, text in re.findall(r'<h([23])\s+id="([^"]+)">(.*?)</h\1>', body, re.S):
        clean = html.unescape(re.sub(r"<[^>]+>", "", text))
        cls = "toc-h2" if level == "2" else "toc-h3"
        toc_items.append(f'<a class="{cls}" href="#{tid}">{html.escape(clean)}</a>')
    toc_html = "\n  ".join(toc_items)

    if not out:
        out = os.path.splitext(src)[0] + ".html"
    page = HTML_DOC.format(title=html.escape(title), css=CSS, toc=toc_html, body=body)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"[done] HTML 报告: {out}")


if __name__ == "__main__":
    main()
