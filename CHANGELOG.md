# Changelog

中文 · [English](#english)

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

---

## [0.5.0] - 2026-04-30

### 新增
- **支持 [`@cometix/claude-code`](https://github.com/CometixSpace/claude-code)**：CometixSpace 把 bun 编译产物反向解包成 Node 可跑的 `cli.js`，本脚本现在能自动定位并 patch 这种发布
- `find_install_root` 同时检查 `@anthropic-ai/claude-code` 和 `@cometix/claude-code`
- `find_binaries` 在包根目录扫 `cli.js`（除了原有的 `bin/claude*` 和平台子包）
- `is_macho()` / `needs_codesign()` 通过文件头 magic number 检测 Mach-O，避免对纯 JS 文件做无意义的 codesign

### 验证
- `@cometix/claude-code` 2.1.121：1 处 patched，跳过 codesign（cli.js 是 plain JS）

## [0.4.0] - 2026-04-22

### 新增
- 脚本输出和 `--help` 文案全部中文化（标签、状态、错误信息）
- 内部状态码保留英文（`patched` / `would_patch` / `already` / `not_found` / `error`），只改展示层

### 验证
- Claude Code 2.1.116：patch + 重签 + Haiku/Opus subagent 工具调用全部通过

## [0.3.0] - 2026-04-21

### 新增
- **macOS APFS clonefile 副作用兜底**：当二进制检测到"已是 patched 形态"但 codesign 校验失败时，自动做 ad-hoc 重签
- `codesign_is_valid()` 辅助函数

### 修复
- 2.1.114 升级场景下的问题：npm postinstall 使用 APFS clonefile 共享 `bin/claude.exe` 和平台子包存储，第一个文件被 patch 时第二个的字节也受波及，但签名只在第一个上被 codesign 修过，导致第二个签名失效启动被 SIGKILL

### 验证
- Claude Code 2.1.114：bun compile 首发版本，patch 全流程通过

## [0.2.0] - 2026-04-18

### 重写
- 从 shell 一把梭脚本改写为结构化 Python 脚本
- 宽松正则捕获 minifier 变量（`{0,3}` 字符），替换串按捕获的变量名**动态计算等长度 padding**
- 增加安装目录自动探测（npm root -g / nvm / homebrew / 系统路径）
- 自动发现所有平台二进制（顶层 wrapper + `claude-code-*` 子包）
- 按 real path 去重（兼容 hardlink / symlink）

### 新增
- `--check` 只检查不改
- `--restore` 从最近备份还原
- `--root` 手动指定安装路径
- `PATCHED_PATTERN` 识别已 patch 形态，支持幂等重跑

## [0.1.0] - 2026-04-18

### 初始版本
- 针对 Claude Code 2.1.113（Node SEA 分发）的字节级 patch
- 等长度替换：`thinkingConfig:P?q.options.thinkingConfig:{type:"disabled"}` → `thinkingConfig:/*                */q.options.thinkingConfig`
- macOS ad-hoc 重签步骤（`codesign --remove-signature` + `codesign -s -`）
- 同时 patch 顶层 `bin/claude.exe` 和平台子包 `claude-code-darwin-arm64/claude`
- 备份文件命名：`<file>.backup-subagent-thinking-<timestamp>`

### 思路来源
- 基于哈雷佬 [linux.do 帖子 1991311](https://linux.do/t/topic/1991311) 的 AST 修复思路
- 原 AST 脚本在 2.1.112 之后失效，因为 npm 包从 `cli.js` 换成单可执行二进制（embedded plain-text JS）

---

<a name="english"></a>

# Changelog (English)

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] - 2026-04-30

### Added
- **Support for [`@cometix/claude-code`](https://github.com/CometixSpace/claude-code)**: CometixSpace reverse-unpacks the bun-compiled binary back into a Node-runnable `cli.js`; the script now auto-detects and patches this distribution
- `find_install_root` now checks both `@anthropic-ai/claude-code` and `@cometix/claude-code`
- `find_binaries` scans the package-root `cli.js` (in addition to existing `bin/claude*` and platform subpackages)
- `is_macho()` / `needs_codesign()` detect Mach-O via file-header magic numbers, avoiding pointless codesign on plain JS files

### Verified
- `@cometix/claude-code` 2.1.121: 1 occurrence patched, codesign skipped (cli.js is plain JS)

## [0.4.0] - 2026-04-22

### Added
- Localized script output and `--help` text to Chinese (labels, status lines, error messages)
- Internal status codes kept in English (`patched` / `would_patch` / `already` / `not_found` / `error`); only the presentation layer is translated

### Verified
- Claude Code 2.1.116: patch + re-sign + Haiku/Opus subagent tool-calls all working

## [0.3.0] - 2026-04-21

### Added
- **macOS APFS clonefile fallback**: when a binary is detected as "already patched" but `codesign` validation fails, automatically re-sign ad-hoc
- Helper `codesign_is_valid()`

### Fixed
- Issue surfaced on 2.1.114 upgrade: npm postinstall uses APFS clonefile to share storage between `bin/claude.exe` and the platform subpackage; patching the first file caused the second file's bytes to change too, but codesign only touched the first — the second had an invalid signature and was SIGKILL'd on launch

### Verified
- Claude Code 2.1.114: first bun-compile release; full patch flow verified

## [0.2.0] - 2026-04-18

### Rewritten
- Migrated from a one-shot shell script to a structured Python script
- Loose regex captures minifier-generated variables (`{0,3}` chars); replacement string computes **equal-length padding dynamically** from the captured object name
- Auto-detection of install root (npm root -g / nvm / homebrew / system paths)
- Auto-discovery of all platform binaries (top-level wrapper + `claude-code-*` subpackages)
- Real-path de-duplication (handles hardlinks / symlinks)

### Added
- `--check` dry-run mode
- `--restore` roll-back-to-latest-backup mode
- `--root` override for install path
- `PATCHED_PATTERN` for recognizing already-patched state → idempotent reruns

## [0.1.0] - 2026-04-18

### Initial release
- Byte-level patch for Claude Code 2.1.113 (Node SEA distribution)
- Equal-length substitution: `thinkingConfig:P?q.options.thinkingConfig:{type:"disabled"}` → `thinkingConfig:/*                */q.options.thinkingConfig`
- macOS ad-hoc re-sign step (`codesign --remove-signature` + `codesign -s -`)
- Patches both the top-level `bin/claude.exe` and the platform subpackage `claude-code-darwin-arm64/claude`
- Backup file naming: `<file>.backup-subagent-thinking-<timestamp>`

### Origin
- Inspired by Haleclipse's AST fix at [linux.do topic 1991311](https://linux.do/t/topic/1991311)
- The original AST script broke after 2.1.112 because the npm package switched from `cli.js` to a single-executable binary (with embedded plain-text JS)
