# personalSkills

个人（pipony）日常使用的 Claude Code skills 集合。每个 skill 是一个独立目录（核心是 `SKILL.md`，部分含 `scripts/`）。

把某个 skill 目录软链到 `~/.claude/skills/`（用户级，全局可用）或某项目的 `.claude/skills/`（项目级），即可在 Claude Code 中使用：

```bash
ln -s /path/to/personalSkills/<skill>  ~/.claude/skills/<skill>      # 全局
ln -s /path/to/personalSkills/<skill>  <项目>/.claude/skills/<skill>  # 项目级
```

## Skills 一览

| Skill | 一句话 | 触发方式 |
|---|---|---|
| [study-to-anki](./study-to-anki) | 学习主题 / 材料 → 结构化 Markdown → 可导入 Anki 的 `.apkg` 闪卡 | 「帮我做 XXX 的闪卡」「把 XXX 做成 Anki 卡片」 |
| [video-to-text](./video-to-text) | 小红书 / B站视频 / 小宇宙播客 → 干净的 Markdown 文字稿 | 丢一个上述平台链接，说「转文字稿」「出文案」「做字幕」 |
| [skill-architect-mentor](./skill-architect-mentor) | 深度拆解任意 Agent Skill 的设计思想，产出 11 节学习报告（MD + HTML） | 「拆解这个 skill」「分析这个 skill 是怎么设计的」+ GitHub URL / 本地路径 |
| [memory-analyzer](./memory-analyzer) | 内存/进程只读分析 → 三色安全分级 → 可视化网页 → 一键优雅退出/强制结束 | 「内存占用高」「哪个进程吃内存」「关掉某应用」「释放内存」 |

---

### study-to-anki
把任何学习主题（或提供的 PDF / 网页 / 文档材料）转成结构化的 Markdown 学习内容，经用户审阅确认后，生成可直接导入 Anki 的 `.apkg` 闪卡文件。可选归档到 GitHub 牌组仓库。
- **流程**：需求梳理 → 素材收集整理 → 生成 Markdown → 用户审阅 → 生成 .apkg →（可选）归档。
- **自带脚本**：`scripts/generate_apkg.py`（纯 Python，依赖 `genanki`）。
- **可复刻点**：「重内容拆文件」+ 用户逐段审阅的交互节奏。

### video-to-text
把小红书 / B站视频、或小宇宙播客单集的口播内容，转成一份干净的 Markdown 文字稿。这些平台都没有现成可复制的字幕，本 skill 自动跑「下载 → 抽音频 → 语音识别 → 校对」整条链路。
- **设计脊柱**：把稳定可复现的脏活固化进 `scripts/transcribe.py`，把需要判断的校对/分段留给模型。
- **依赖**：`ffmpeg`、`mlx_whisper`（仅 Apple Silicon Mac）。
- **可复刻点**：脚本/文档二分、退出码穷举失败分类、一段「执行准则」定调节奏。

### skill-architect-mentor
深度拆解、分析、学习任意 Agent Skill 的设计思想——不是读代码或浅层总结功能，而是回答「它为什么这样设计、哪些思想值得学、怎么迁移到自己的 skill」。支持 GitHub URL（含子目录）或本地路径输入。
- **流程**：建图 → 定位检查点 → 深度分析（7 阶段）→ 产出 11 节学习报告（`.md` + `.html`）。
- **自带脚本**：`scripts/report_to_html.py`（报告转自包含 HTML，含目录、折叠原文附录）。
- **三条写作原则**：原文佐证、术语就近解释、英文原文附翻译。
- **可复刻点**：阶段→报告章节映射保证不漏节、检查点机制、heavy reference 拆文件。

### memory-analyzer
对 macOS/Windows 做只读的**内存与运行中进程**分析，三色分级（🟢可安全退出 / 🟡谨慎退出 / 🔴永不触碰），产出交互式可视化网页，安全操作（优雅退出 / 强制结束）可在网页一键执行。架构同磁盘版 `storage-analyzer`，但对象是内存/进程。
- **流程**：只读扫描 → agent 三色分级 → 交互网页 → 一键安全动作 → 小结。
- **运行时**：macOS 用 Python（`scripts/*.py`，已实测）；Windows 用 PowerShell（`scripts/*.ps1`，零安装、代码就位未实测）。
- **设计脊柱**：scan 只读 + PID+comm 双键（堵死 pid 复用杀错）+ 六层防护动作端点 + 内存诚实性（"空闲≈浪费"、文件缓存自动回收）。
- **agent 无关**：`README.md` 是工作流唯一真相源，`SKILL.md`/`AGENTS.md` 为不同 agent 生态入口，任何能跑 shell 的 agent 都能用。
- **可复刻点**：脚本/文档二分、双键安全模型、analysis JSON 契约驱动按钮（同 storage-analyzer 的 `trash_paths` 思路）、跨运行时共享模板/契约/分级文档。

---

## 目录结构

```
personalSkills/
├── README.md
├── study-to-anki/         # SKILL.md + scripts/generate_apkg.py
├── video-to-text/         # SKILL.md + scripts/transcribe.py
├── skill-architect-mentor/
│   ├── SKILL.md           # 入口与编排
│   ├── analysis-guide.md  #  7 阶段分析方法论
│   ├── report-template.md # 11 节报告模板
│   └── scripts/report_to_html.py
└── memory-analyzer/       # 内存/进程分析（agent 无关）
    ├── README.md / SKILL.md / AGENTS.md
    ├── assets/report_template.html
    ├── references/{macos,windows}.md
    └── scripts/{scan,server,build_report}.{py,ps1} + safety.py
```
