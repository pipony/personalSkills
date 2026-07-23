---
name: skill-architect-mentor
description: |
  用于深度拆解、分析、学习任意 Agent Skill 的设计思想——不是读代码或浅层总结功能，而是搞清楚「它为什么这样设计、哪些思想值得学、怎么迁移到自己的 skill」。

  当用户说「拆解这个 skill」「分析这个 skill 是怎么设计的」「我想学习这个 skill 的设计思路」「这个 skill 为什么这么设计」「帮我研究一下这个 skill」，或用户提供某个 skill 的 GitHub 仓库地址 / 本地路径并想理解其设计、思想、可迁移经验时，使用此 skill。

  也适用于：想从别人的 skill 里提炼 Prompt 技巧 / Workflow 模式 / Agent 架构经验；想对比或复刻一个优秀 skill 的设计。

  不适用于：只是想跑一下 / 用一下某个 skill；只想快速知道某个 skill 大致做什么的浅层总结；分析对象是普通代码库而非 agent skill。
---

# Skill Architect Mentor — 拆解、学习优秀 Agent Skill 的导师

把任意 Agent Skill（GitHub 仓库或本地路径）拆解成一份有洞察的学习报告，帮你理解它为什么这样设计、哪些思想值得迁移到自己的 skill。重点永远是「为什么这样设计」，不是「它做了什么」。

## 何时使用 / 不适用

- **适用**：想深度理解一个 skill 的设计思想、提炼可迁移经验、学习或复刻优秀 skill。
- **不适用**：只是想跑一下 / 用一下某个 skill；只想要浅层功能总结；对象是普通代码库而非 agent skill。

## 输入

两种模式：
- **GitHub URL**：clone 到临时目录分析，结束后清理。
- **本地路径**：就地分析，**绝不改动原文件**。

## 工作流程

### Step 0：获取与建图（Phase 1）

GitHub 输入时分两种 URL：
- **仓库根 URL**（`github.com/owner/repo` 或 `.git`）：直接 clone。
- **子目录 URL**（`github.com/owner/repo/tree/<branch>/<路径>`）：不能直接 clone（git 不认 tree URL），要拆成「仓库根 + 子目录」——clone 仓库根，再把 skill 根指向子目录。

```bash
url="<用户给的 GitHub URL>"; dst="/tmp/skill-analyze-<name>"
case "$url" in
  */tree/*)
    bp="${url#*/tree/}"          # <branch>/<路径>
    branch="${bp%%/*}"; sub="/${bp#*/}"
    repo="${url%/tree/*}.git"
    git clone --depth 1 -b "$branch" "$repo" "$dst"
    skill_root="$dst$sub"        # skill 实际在 clone 里的子目录
    ;;
  *)
    git clone --depth 1 "$url" "$dst"
    skill_root="$dst"
    ;;
esac
```

本地路径输入时：`skill_root=<本地路径>`，不 clone、不改动。

定位入口（优先 SKILL.md，兼容其它格式）：
```bash
find "$skill_root" -iname 'SKILL.md' -o -iname 'README.md' | head
```
找不到 SKILL.md 时，再找 `*.md` 主文件、`rules`、`.cursorrules` 等。结束后清理 `/tmp/skill-analyze-<name>`。

然后列目录结构、读 frontmatter 与关键文件，建立完整上下文。详细分析要点见 `analysis-guide.md` 的 Phase 1。

### Step 1：定位检查点（Phase 2）—— 唯一强制检查点

按 `analysis-guide.md` 的 Phase 2，产出一份**简短**定位：解决什么问题 / 适用与不适用场景 / 背后核心理念（2–4 条）。

**把这份定位呈现给用户，确认方向，并问「要重点深挖哪些方面？」。** 确认后才进入 Step 2。这个检查点的价值是在投入深度分析前及时纠偏——别跳过。

### Step 2：深度分析（Phase 3–7），一次性跑完

按 `analysis-guide.md` 跑：架构拆解 → Workflow → Prompt 工程 → 文件/代码结构 → 设计经验提炼 → 反向重设计。**中途不再逐段打断用户**，仅在真正阻塞（clone 失败、找不到入口、路径不存在）时才找用户。

### Step 3：组装报告

用 `report-template.md` 填满 11 节，写到**当前工作目录** `<skill名>-学习报告.md`。对照 `analysis-guide.md` 的「阶段→报告章节映射」检查 11 节无遗漏。

然后生成对应的可查看 HTML 版本（MD 是唯一事实来源，脚本只做格式转换，保证两份内容一致）。传入 `--skill-dir` 可把被分析 skill 的原始文件以**可折叠**方式嵌进 HTML 末尾，方便对照原文：

```bash
python3 <skill-path>/scripts/report_to_html.py <skill名>-学习报告.md --skill-dir <skill_root>
```

会在同目录生成 `<skill名>-学习报告.html`（自包含、内嵌样式、带目录、离线可看，末尾「原文附录」可展开直接读 skill 源文件）。向用户**同时交付 .md 和 .html 两个路径**与摘要。

## 参考文件

- `analysis-guide.md`：7 阶段方法论 + 阶段→报告映射（深度分析时读）
- `report-template.md`：11 节报告模板（组装报告时用）
- `scripts/report_to_html.py`：把 .md 报告转成自包含 HTML（组装报告后跑）

## 常见坑

- **子目录 / tree URL**：GitHub 的 `.../tree/<branch>/<path>` 链接不能直接 `git clone`，要拆成仓库根 clone + 子目录定位（见 Step 0 的 case 分支）。
- **找不到 SKILL.md**：不是所有 skill 都叫 SKILL.md；找 `*.md` 主文件 / README / `rules` / `.cursorrules` 等，兼容其它格式。
- **clone 失败**：私有仓库 / 网络问题 → 让用户提供本地路径或检查权限。
- **对象不是 skill**：如果是普通代码库而非 agent skill，提示用户本 skill 不适用，不要硬分析。
- **别只罗列功能**：每个分析点都要回到「为什么这样设计」，否则报告没有学习价值。
- **报告别漏节**：组装后对照映射表数一遍，确保 §1–§11 都有内容。
- **HTML 生成失败**：脚本依赖 `markdown` 库，会自动 `pip install`；若环境装不上，.md 报告仍已生成，可手动转或告知用户只看 .md。
