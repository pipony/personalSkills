#!/usr/bin/env python3
"""
通用 Markdown → Anki .apkg 转换器

用法:
    python generate_apkg.py <content_dir> <output_file> <deck_name> [<front_field> <back_fields...>]

示例:
    python generate_apkg.py ./content ./output/血液检查.apkg "血液检查学习卡片" "指标名称" "所属分类" "是什么" "正常范围" "偏高意味着" "偏低意味着"

Markdown 文件格式要求:
    - 文件以 # 开头的标题作为分类名
    - 每个条目用 ## 或 ### 标题开头，标题内容作为第一个字段（名称）
    - 条目内容用 **字段名**：值的格式，字段名对应命令行传入的字段参数
    - 用 --- 或下一个同级标题分隔条目
"""

import re
import os
import sys
import hashlib
import html
import genanki


def generate_model_id(deck_name):
    return int(hashlib.md5(deck_name.encode("utf-8")).hexdigest()[:8], 16)


def generate_deck_id(deck_name):
    return int(hashlib.sha256(deck_name.encode("utf-8")).hexdigest()[:8], 16)


def guid_for(name, deck_name):
    return int(hashlib.md5(f"{deck_name}:{name}".encode("utf-8")).hexdigest()[:8], 16)


def build_model(model_id, model_name, fields, front_field):
    """构建 Anki 卡片模型"""
    field_defs = [{"name": f} for f in fields]
    front_idx = fields.index(front_field) if front_field in fields else 0

    # 构建正面 HTML
    qfmt = '<div class="front">\n  <div class="name">{{%s}}</div>\n</div>' % fields[front_idx]

    # 构建背面 HTML
    afmt_parts = ['<div class="back">']
    afmt_parts.append('  <div class="name">{{%s}}</div>' % fields[front_idx])
    afmt_parts.append('  <hr>')
    for i, f in enumerate(fields):
        if f == front_field:
            continue
        afmt_parts.append(
            '  <div class="section s%d">'
            '<div class="label">%s</div>'
            '<div class="content">{{%s}}</div>'
            '</div>' % (i, f, f)
        )
    afmt_parts.append('</div>')

    # CSS - 每个字段不同颜色
    section_colors = [
        ("#f0f4ff", "#3b5998"),  # 蓝
        ("#f0fff4", "#2d8a4e"),  # 绿
        ("#fff5f0", "#d63031"),  # 红
        ("#f0f5ff", "#2d6cdf"),  # 亮蓝
        ("#fff8e1", "#e67e22"),  # 橙
        ("#f3e5f5", "#8e24aa"),  # 紫
        ("#e0f7fa", "#00838f"),  # 青
        ("#fce4ec", "#c62828"),  # 粉红
    ]
    css_sections = []
    non_front_fields = [f for f in fields if f != front_field]
    for i, f in enumerate(non_front_fields):
        color_pair = section_colors[i % len(section_colors)]
        css_sections.append(
            ".section.s%d { background: %s; }\n.section.s%d .label { color: %s; }"
            % (fields.index(f), color_pair[0], fields.index(f), color_pair[1])
        )

    css = """
.card {
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #fafafa; padding: 20px; color: #333; line-height: 1.6;
}
.front { text-align: center; padding: 40px 20px; }
.name { font-size: 28px; font-weight: bold; color: #1a1a1a; }
.back .name { font-size: 22px; margin-bottom: 4px; }
hr { border: none; border-top: 1px solid #e0e0e0; margin: 16px 0; }
.section { margin-bottom: 14px; padding: 10px 14px; border-radius: 8px; }
.label { font-weight: bold; font-size: 15px; margin-bottom: 4px; }
.content { font-size: 14px; color: #444; }
""" + "\n".join(css_sections)

    return genanki.Model(
        model_id,
        model_name,
        fields=field_defs,
        templates=[{
            "name": "卡片1",
            "qfmt": qfmt,
            "afmt": "\n".join(afmt_parts),
        }],
        css=css,
    )


def extract_field(text, label):
    """从文本中提取某个字段的值"""
    pattern = rf"\*\*{re.escape(label)}\*\*[：:]\s*(.+?)(?=\n\n\*\*|\n---|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        val = match.group(1).strip()
        val = html.escape(val)
        val = val.replace("&lt;br&gt;", "<br>").replace("&lt;", "<").replace("&gt;", ">")
        # 保留原始换行为 <br>
        val = re.sub(r"\n", "<br>", val)
        return val
    return ""


def parse_md(filepath, fields):
    """解析 Markdown 文件，提取每个条目的字段"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    category_match = re.search(r"^# (.+)$", content, re.MULTILINE)
    category = category_match.group(1) if category_match else os.path.splitext(os.path.basename(filepath))[0]

    items = []

    # 先尝试 ### 级别，数量不够再用 ##
    for level in [r"^### ", r"^## "]:
        blocks = re.split(level, content, flags=re.MULTILINE)
        valid_blocks = [b for b in blocks[1:] if b.strip()]
        if len(valid_blocks) >= 2:
            indicator_blocks = valid_blocks
            break
    else:
        return category, []

    for block in indicator_blocks:
        lines = block.strip().split("\n")
        name = lines[0].strip()
        # 跳过分节标题
        if re.match(r"^[一二三四五六七八九十]+[、.]", name):
            continue

        text = "\n".join(lines[1:])
        field_values = {}
        has_content = False
        for field in fields:
            if field == "名称":
                field_values["名称"] = html.escape(name)
                has_content = True
            else:
                val = extract_field(text, field)
                field_values[field] = val
                if val:
                    has_content = True

        if has_content:
            items.append({"category": category, "fields": field_values})

    return category, items


def main():
    if len(sys.argv) < 5:
        print("用法: python generate_apkg.py <content_dir> <output_file> <deck_name> <field1> [field2] ...")
        print("第一个 field 会被用作卡片正面")
        sys.exit(1)

    content_dir = sys.argv[1]
    output_file = sys.argv[2]
    deck_name = sys.argv[3]
    fields = sys.argv[4:]
    front_field = fields[0]

    if "所属分类" not in fields:
        fields = list(fields) + ["所属分类"]

    model = build_model(generate_model_id(deck_name), deck_name, fields, front_field)
    deck = genanki.Deck(generate_deck_id(deck_name), deck_name)

    md_files = sorted(f for f in os.listdir(content_dir) if f.endswith(".md"))
    if not md_files:
        print(f"错误: 在 {content_dir} 中没有找到 .md 文件")
        sys.exit(1)

    total = 0
    for md_file in md_files:
        filepath = os.path.join(content_dir, md_file)
        category, items = parse_md(filepath, fields)
        print(f"  {md_file}: {len(items)} 个条目")
        for item in items:
            field_vals = []
            for f in fields:
                if f == "所属分类":
                    field_vals.append(item["category"])
                else:
                    field_vals.append(item["fields"].get(f, ""))
            note = genanki.Note(
                model=model,
                fields=field_vals,
                guid=guid_for(item["fields"].get(front_field, str(total)), deck_name),
            )
            deck.add_note(note)
            total += 1

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    genanki.Package(deck).write_to_file(output_file)
    print(f"\n共 {total} 张卡片 → {output_file}")


if __name__ == "__main__":
    main()
