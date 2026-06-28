# video-to-text

> 一个 [Claude Code](https://claude.com/claude-code) skill：把**小红书 / B站视频**、或**小宇宙播客单集**里的口播内容，自动转写成一份干净的 Markdown 文字稿。
>
> A Claude Code skill that turns Xiaohongshu / Bilibili videos or Xiaoyuzhou podcast episodes into clean Markdown transcripts — fully on-device (Apple Silicon), no API keys, no audio uploaded to the cloud.

## 为什么需要它

这三个平台的内容通常都没有可直接复制的字幕。要拿到文字稿，得走「下载视频/音频 → 语音识别」这条路，而这条路坑很多：页面数据动态渲染、流地址有时效签名、B站取流接口有风控、huggingface.co 在大陆常被墙、Whisper 会在结尾产生重复幻觉……本 skill 把这些**稳定可复现的处理固化在 `scripts/transcribe.py` 里**，一次跑完；校对与整理的部分则交给 AI（见 `SKILL.md`）。

## 支持的平台

| 平台 | 链接 | 取流方式 |
| --- | --- | --- |
| 小红书 | `xiaohongshu.com` / `xhslink.com` | 解析页面 `__INITIAL_STATE__`，直链下载 mp4 |
| B站 | `bilibili.com` / `b23.tv` | **优先**官方 CC/人工字幕；否则用 `platform=html5` 取音频 |
| 小宇宙 | `xiaoyuzhoufm.com/episode/<id>` | 解析 `__NEXT_DATA__`，公网 CDN 直链 m4a |

## 特点

- **一条命令**完成「解析元信息 → 下载 → 抽音 → 语音识别 → 去幻觉」。
- **B站字幕优先**：有可下载的官方字幕就直接用（更准、即时），没有才走 ASR。
- **本地识别**：基于 [mlx_whisper](https://github.com/ml-explore/mlx-examples) 在 Apple Silicon 上跑，音频不出本机、不调云端 API、不花 token 钱。
- **大陆网络友好**：模型走 `hf-mirror.com` 镜像；各平台尽量用匿名可用的取流方式。
- **抗幻觉**：自动裁掉 Whisper 常见的单字循环、段落重复。
- **作为 skill 使用时**，AI 会对照标题/简介/shownotes 校对术语错字、整理分段，输出可读的文字稿。

## 前置依赖

- **macOS Apple Silicon（arm64）** —— mlx_whisper 目前依赖 arm64。
- **ffmpeg** —— 抽取音频：`brew install ffmpeg`
- **mlx-whisper** —— 装在 `python3.13` 下：`python3.13 -m pip install -U mlx-whisper`
- 首次运行会下载模型 `mlx-community/whisper-large-v3-turbo`（约 1.6 GB，走镜像，之后离线缓存）。

> 脚本在默认 `python3` 没有 mlx_whisper 时，会自动改用 `python3.13/3.12/3.11` 重跑，所以即使 Homebrew 切换了默认 Python 版本也不会断。

## 安装（作为 Claude Code skill）

```bash
# 克隆到 Claude 的 skills 目录（目录名需为 video-to-text）
git clone https://github.com/pipony/video-to-text.git ~/.claude/skills/video-to-text
```

安装后，在 Claude Code 里直接发一条链接并说「转成文字稿」即可触发；AI 会自动调用脚本、校对并输出 Markdown。

## 用法（命令行直接用）

```bash
python3 scripts/transcribe.py "<链接>" [选项]
```

**示例：**

```bash
# 小红书视频（需含 xsec_token 的完整链接）
python3 scripts/transcribe.py "https://www.xiaohongshu.com/explore/<id>?xsec_token=..."

# B站视频（支持 BV / av / b23.tv 短链）
python3 scripts/transcribe.py "https://www.bilibili.com/video/BVxxxxxxxx"

# 小宇宙单集（中文内容建议传 --language zh）
python3 scripts/transcribe.py "https://www.xiaoyuzhoufm.com/episode/<id>" --language zh
```

**常用参数：**

| 参数 | 说明 |
| --- | --- |
| `--out-dir <目录>` | 输出目录（默认 `/tmp/v2t_<id>`） |
| `--model <repo>` | Whisper 模型（默认 `mlx-community/whisper-large-v3-turbo`） |
| `--language auto\|zh\|en\|…` | 语言（默认 `auto`；中文内容建议传 `zh`） |
| `--force-asr` | 忽略 B站字幕，强制语音识别 |

**输出（在输出目录下）：**

- `raw_text.txt` —— 整段文字（已去幻觉）
- `segments.txt` —— 带时间戳的逐句 `[起 -> 止] 文本`
- `metadata.json` —— 标题 / 作者 / 时长 / 来源(字幕 or ASR) / 模型 / 耗时

## 工作原理

```
链接 → 判断平台 → 取元信息 + 取音频/字幕
                          │
              ┌───────────┴────────────┐
            有字幕？                    无
              │                         │
         直接用字幕              ffmpeg 抽 16kHz wav
                                        │
                                mlx_whisper 识别
                                        │
                                去幻觉 / 去循环
                                        │
                       写出 raw_text / segments / metadata
```

更多细节见 `scripts/transcribe.py` 顶部注释，以及 [`SKILL.md`](./SKILL.md)（写给 AI 的校对与整理指南）。

## 退出码

| 码 | 含义 |
| --- | --- |
| 2 | 非视频/图文笔记，或小宇宙频道链接（非单集） |
| 3 | 链接/token 问题（小红书 `xsec_token` 过期、单集下架/私密） |
| 4 | 取不到可播放流（地区/会员限制、付费内容、链接失效） |
| 5 | 缺 ffmpeg 或 mlx_whisper |
| 6 | 不是支持的链接 |

## 局限

- 仅支持 **Apple Silicon Mac**（Intel / Windows / Linux 暂不支持，因依赖 mlx）。
- 语音识别在专名、术语、人名上**必然有错字**，需要人工/AI 校对（skill 模式下 AI 会做这一步）。
- 取不到付费、会员、私密、地区限制的内容。
- 目前仅支持小红书、B站、小宇宙；抖音 / YouTube / 视频号等暂不支持。

## 致谢

- 语音识别基于 [MLX](https://github.com/ml-explore/mlx) 与 [whisper-large-v3-turbo](https://huggingface.co/mlx-community/whisper-large-v3-turbo)。
- 小宇宙取流参考了社区的逆向思路。

## License

[MIT](./LICENSE)
