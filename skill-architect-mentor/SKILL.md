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
- **GitHub URL**：clone 到本地保留目录 `./skill-src/<skill名>/` 分析，**分析结束后源码保留在原地**，便于后续查看、对照与复刻。
- **本地路径**：就地分析，**绝不改动原文件**（源码本来就在本地，不另存副本）。

**放置约定（默认项目级）**：被分析的 skill 一律按**项目级 skill** 对待——需要安装/放置时，落到**当前项目**的 `./.claude/skills/<skill名>/`（不是用户全局 `~/.claude/skills/`）；GitHub 来源的源码副本统一保留在工作区 `./skill-src/<skill名>/`。报告「调用示例」一节按项目级用法书写。

## 工作流程

### Step 0：获取与建图（Phase 1）

GitHub 输入时分两种 URL：
- **仓库根 URL**（`github.com/owner/repo` 或 `.git`）：直接 clone。
- **子目录 URL**（`github.com/owner/repo/tree/<branch>/<路径>`）：不能直接 clone（git 不认 tree URL），要拆成「仓库根 + 子目录」——clone 仓库根，再把 skill 根指向子目录。

```bash
url="<用户给的 GitHub URL>"; dst="./skill-src/<name>"   # 本地保留目录：<name> 取 skill 名（tree URL 取子目录名）；目录已存在则直接复用，不重复 clone
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
找不到 SKILL.md 时，再找 `*.md` 主文件、`rules`、`.cursorrules` 等。**clone 下来的源码保留在 `./skill-src/<skill名>/`，分析结束后不清理**——后续对照原文、复刻、二次分析都用它（HTML 报告不再内嵌源码，看这个目录）。

然后列目录结构、读 frontmatter 与关键文件，建立完整上下文。详细分析要点见 `analysis-guide.md` 的 Phase 1。

### Step 1：定位检查点（Phase 2）—— 唯一强制检查点

按 `analysis-guide.md` 的 Phase 2，产出一份**简短**定位：解决什么问题 / 适用与不适用场景 / 背后核心理念（2–4 条）。

**把这份定位呈现给用户，确认方向，并问「要重点深挖哪些方面？」。** 确认后才进入 Step 2。这个检查点的价值是在投入深度分析前及时纠偏——别跳过。

### Step 2：深度分析（Phase 3–7），一次性跑完

按 `analysis-guide.md` 跑：架构拆解 → Workflow → Prompt 工程 → 文件/代码结构 → 设计经验提炼 → 反向重设计。**中途不再逐段打断用户**，仅在真正阻塞（clone 失败、找不到入口、路径不存在）时才找用户。

### Step 3：组装报告

用 `report-template.md` 填满 11 节 + 「输入与输出（速览）」+「调用示例」（后两节同样**必填**），写到**当前工作目录** `<skill名>-学习报告.md`。元信息的「源码副本」填本地保留路径（GitHub 来源填 `./skill-src/<skill名>/`，本地来源填原路径）；「调用示例」给可直接复制尝试的调用写法（自然语言触发语 + slash 写法，按项目级用法）。对照 `analysis-guide.md` 的「阶段→报告章节映射」检查无遗漏。

然后生成对应的可查看 HTML 版本（MD 是唯一事实来源，脚本只做格式转换，保证两份内容一致）：

```bash
python3 <skill-path>/scripts/report_to_html.py <skill名>-学习报告.md
```

会在同目录生成 `<skill名>-学习报告.html`（自包含、内嵌样式、带目录、离线可看）。**HTML 不再内嵌「原文附录」**——要对照源码，直接看本地保留目录 `./skill-src/<skill名>/`（脚本的 `--skill-dir` 参数已废弃：传入也不会嵌入，只会打印提示）。向用户**同时交付 .md 和 .html 两个路径、源码保留目录**与摘要。

### Step 4：收尾（用户说「收尾」时进入）

报告交付后**什么都不删**。当用户说「收尾」（或明确表示要结束学习）时进入本阶段，分两步，**顺序不能颠倒**：

1. **巩固问答（先）**：围绕报告出 3–5 个巩固性问题，检验用户是否真懂设计思想——优先从核心理念（§3）、最值得学的设计点（§8）、反向重设计（§10）出题（例：「为什么它要先规划再执行，直接一步到位会怎样？」）。把问题抛给用户、**等用户回答**后再点评纠偏；不要自问自答，也不要问题还没互动就往下走。
2. **清理确认（后）**：问答结束后，明确询问用户是否删除**本分析工作目录**下由本 skill 生成的产物，逐项列清再问：
   - 被分析 skill 的本地源码副本：`./skill-src/<skill名>/`
   - 学习报告：`<skill名>-学习报告.md`、`<skill名>-学习报告.html`
   - 本 skill 生成的其它中间产物（如有）

   **默认一律不删**；只有用户明确确认后才删，且只删上面列出的产物，绝不动其它文件。用户拒绝则全部保留，并把各产物的路径再完整告知一遍。

## 参考文件

- `analysis-guide.md`：7 阶段方法论 + 阶段→报告映射（深度分析时读）
- `report-template.md`：11 节报告模板（组装报告时用）
- `scripts/report_to_html.py`：把 .md 报告转成自包含 HTML（组装报告后跑；不嵌源码附录，源码看 `./skill-src/`）

## 常见坑

- **子目录 / tree URL**：GitHub 的 `.../tree/<branch>/<path>` 链接不能直接 `git clone`，要拆成仓库根 clone + 子目录定位（见 Step 0 的 case 分支）。
- **找不到 SKILL.md**：不是所有 skill 都叫 SKILL.md；找 `*.md` 主文件 / README / `rules` / `.cursorrules` 等，兼容其它格式。
- **clone 失败**：私有仓库 / 网络问题 → 让用户提供本地路径或检查权限。
- **对象不是 skill**：如果是普通代码库而非 agent skill，提示用户本 skill 不适用，不要硬分析。
- **别只罗列功能**：每个分析点都要回到「为什么这样设计」，否则报告没有学习价值。
- **报告别漏节**：组装后对照映射表数一遍，确保 §1–§11 与「速览」「调用示例」都有内容。
- **收尾顺序**：必须先巩固问答、再清理确认；未经用户明确确认，绝不删除源码副本或报告。
- **HTML 生成失败**：脚本依赖 `markdown` 库，会自动 `pip install`；若环境装不上，.md 报告仍已生成，可手动转或告知用户只看 .md。
