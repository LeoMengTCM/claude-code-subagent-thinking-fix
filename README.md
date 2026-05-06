# Claude Code SubAgent Patch

中文 · [English](#english)

---

## 这是啥

给 Claude Code CLI 的 SubAgent 打字节级 patch，修复两个导致第三方中转（如 anyrouter）路由失败的 bug：

1. **thinkingConfig 硬编码为 `{type:"disabled"}`** —— 子代理始终不传 thinking 字段，anyrouter 后端校验不正确
2. **Haiku 子代理缺 1M context beta header** —— 请求不带 `context-1m-2025-08-07`，anyrouter 网关直接 400

原 bug（问题 1）的分析和首个 AST 修复脚本来自 **哈雷佬**：

- <https://linux.do/t/topic/1991311>（原帖：SubAgent / Haiku 无法调用）
- <https://linux.do/t/topic/1993426>（跟进：2.1.114 npm 包换 bun 编译的影响）

哈雷佬的 AST 脚本在 2.1.112 之后失效，因为 npm 包从 `cli.js` 换成了单可执行二进制（Node SEA / Bun compile），
但 JS bundle 仍以明文嵌入二进制，所以字节级**等长度替换**这条路走得通。本仓库就是这条路的脚本实现。

同时也支持 [CometixSpace/claude-code](https://github.com/CometixSpace/claude-code) 这个第三方分发 ——
他们把 bun 编译产物**反向解包成 Node 可跑的 `cli.js`**（npm 包名 `@cometix/claude-code`），
方便不愿用原生二进制的用户。这种场景下脚本同样能工作（不需要 codesign）。

> ⚠️ 该修复主要针对第三方中转（如 anyrouter）场景下 SubAgent 无法路由的症状。走官方 API 的用户一般不需要此 patch。

## 快速上手

```bash
# 安装/升级 Claude Code 之后跑这三条就行
python3 patch-claude-code-subagent-thinking.py --check    # 先 dry-run 看一眼
python3 patch-claude-code-subagent-thinking.py             # 应用 patch（macOS 自动 ad-hoc 重签）
# 重启 Claude Code

# 想回滚？
python3 patch-claude-code-subagent-thinking.py --restore
```

## 要求

- Python 3.9+
- Claude Code 2.1.112+（再低就去跑哈雷佬原版的 AST 脚本）
- macOS（Apple Silicon / Intel 都行）或 Linux
- **macOS 额外**：系统自带的 `codesign`（脚本会自动调用做 ad-hoc 重签）

## 已验证版本

| 包 | 版本 | 状态 | 备注 |
|---|---|---|---|
| `@anthropic-ai/claude-code` | 2.1.113 | ✅ | Node SEA 时代 |
| `@anthropic-ai/claude-code` | 2.1.114 | ✅ | bun compile 首发，APFS clonefile 副作用由脚本自动补签处理 |
| `@anthropic-ai/claude-code` | 2.1.116 | ✅ | 同 2.1.114 |
| `@anthropic-ai/claude-code` | 2.1.128–2.1.131 | ✅ | 原生安装器布局；两个修复均验证通过 |
| `@cometix/claude-code` | 2.1.121 | ✅ | CometixSpace 还原版（cli.js）；纯 JS 文件，自动跳过 codesign |

## 它做了什么

1. 自动定位原生安装（`~/.local/share/claude/versions/<ver>`）或 npm 全局安装里的 `@anthropic-ai/claude-code` 或 `@cometix/claude-code` 目录
2. 找出所有目标文件：
   - 原生安装：`versions/<ver>` 目录下的裸二进制
   - `@anthropic-ai/claude-code`：顶层 wrapper 二进制 + 平台子包二进制
   - `@cometix/claude-code`：包根目录的 `cli.js`
3. 用宽松正则找 `thinkingConfig:X?Y.options.thinkingConfig:{type:"disabled"}`（修复 1）
4. 用宽松正则找 `if(FN(H))_.push(BETA);`（修复 2，即 1M context beta header 条件判断）
5. 用**等长度**的替换串（`/* 空格填充 */`）覆盖它们：
   - 修复 1：始终继承父级 thinkingConfig
   - 修复 2：始终 push `context-1m-2025-08-07` beta header，不依赖模型判断
6. 仅对 Mach-O 二进制做 `codesign --remove-signature` + `codesign -s -` ad-hoc 重签（通过 magic number 自动检测；纯 JS 文件如 Cometix 的 cli.js 跳过）
7. 写备份文件到同目录（`<file>.backup-subagent-thinking-<timestamp>`）
8. 如果文件已经是 patched 形态但 macOS 签名失效（APFS clonefile 共享存储导致），自动补签

## 常见问题

- **升级后 `--check` 报 `未匹配`**
  minifier 变量名变了，打开脚本把 `PATTERN` 里的 `{0,3}` 放宽到 `{0,5}`、`PATTERN_1M` 里的 `{1,5}` 放宽到 `{1,7}` 再试。
- **macOS 启动 `claude` 被 `killed`**
  签名失效。跑 `python3 ... --check`，或 `codesign -v` 手动确认，再重跑 patch 脚本。
- **想彻底卸载 patch**
  `--restore` 会恢复到最近备份；或直接 `npm install -g @anthropic-ai/claude-code@latest` 重装覆盖。

## 局限

- 这个思路假设 JS bundle 以**明文**嵌入二进制。一旦 Anthropic 上压缩/加密，这条路就废了。
- 每次 `npm update -g` 都会覆盖二进制，patch + 签名全部丢失，需要重跑。
- 没在 Linux / Windows 上实测过（Linux 理论上不需要 codesign 步骤，脚本已做平台判断）。

## 致谢

- **哈雷佬** —— 原始 bug 分析、AST 修复思路、2.1.114 bun 迁移解读。所有功劳都是他的，这个仓库只是把他的思路延伸到二进制分发场景。

> 详细的踩坑过程见 [WRITEUP.md](WRITEUP.md)（中文，记录了从原 AST 脚本失效到二进制 patch + codesign + Cometix 兼容的完整 debug log）。

---

<a name="english"></a>

# Claude Code SubAgent Patch (English)

## What it is

A byte-level patch for Claude Code CLI's SubAgent bugs that cause routing failures on third-party relays (e.g. anyrouter):

1. **`thinkingConfig` hardcoded to `{type:"disabled"}`** — sub-agents never send a thinking field, causing backend validation failures
2. **Haiku sub-agents missing the 1M context beta header** — requests without `context-1m-2025-08-07` get rejected by the relay gateway with a 400 error

Original bug analysis (for issue 1) and the first AST-based fix come from **Haleclipse** on linux.do:

- <https://linux.do/t/topic/1991311> — original post (SubAgent / Haiku unusable)
- <https://linux.do/t/topic/1993426> — follow-up on 2.1.114 switching to bun compile

Haleclipse's AST script stopped working in 2.1.112+ because the npm package switched from `cli.js` to a single-executable binary (Node SEA, then Bun compile). The JS bundle is still embedded as plain text inside the binary, though, so byte-level **equal-length replacement** still works. That's what this repo does.

The script also supports [CometixSpace/claude-code](https://github.com/CometixSpace/claude-code) — a third-party redistribution that **reverse-unpacks the bun-compiled binary back into a Node-runnable `cli.js`** (npm package `@cometix/claude-code`), for users who prefer not to run the native binary. The same byte-level patch applies (no codesign needed for plain JS).

> ⚠️ This fix mainly addresses SubAgent routing failures on third-party relays (e.g. anyrouter). Users on the official Anthropic API usually don't need it.

## Quick start

```bash
# After installing or upgrading Claude Code:
python3 patch-claude-code-subagent-thinking.py --check    # dry-run first
python3 patch-claude-code-subagent-thinking.py            # apply (auto ad-hoc re-sign on macOS)
# Restart Claude Code

# To roll back:
python3 patch-claude-code-subagent-thinking.py --restore
```

## Requirements

- Python 3.9+
- Claude Code 2.1.112+ (older versions: use Haleclipse's original AST script)
- macOS (Apple Silicon / Intel) or Linux
- **macOS extra**: system `codesign` (auto-invoked for ad-hoc re-signing)

## Verified versions

| Package | Version | Status | Notes |
|---|---|---|---|
| `@anthropic-ai/claude-code` | 2.1.113 | ✅ | Node SEA era |
| `@anthropic-ai/claude-code` | 2.1.114 | ✅ | First Bun compile release; APFS clonefile side-effects auto-handled |
| `@anthropic-ai/claude-code` | 2.1.116 | ✅ | Same as 2.1.114 |
| `@anthropic-ai/claude-code` | 2.1.128–2.1.131 | ✅ | Native installer layout; both fixes verified |
| `@cometix/claude-code` | 2.1.121 | ✅ | CometixSpace's restored `cli.js`; plain JS, codesign auto-skipped |

## What it does

1. Auto-locates the native install (`~/.local/share/claude/versions/<ver>`) or npm global install of `@anthropic-ai/claude-code` or `@cometix/claude-code`
2. Finds every target file:
   - Native install: bare binary under `versions/<ver>`
   - `@anthropic-ai/claude-code`: top-level wrapper binary + platform-subpackage binaries
   - `@cometix/claude-code`: the package-root `cli.js`
3. Uses loose regexes to find the two target patterns:
   - Fix 1: `thinkingConfig:X?Y.options.thinkingConfig:{type:"disabled"}`
   - Fix 2: `if(FN(H))_.push(BETA);` (the 1M context beta conditional)
4. Replaces them with **equal-length** strings (`/* <spaces> */` padding):
   - Fix 1: always inherits parent thinkingConfig
   - Fix 2: always pushes `context-1m-2025-08-07` beta header, regardless of model
5. Re-signs only Mach-O binaries via `codesign --remove-signature` + `codesign -s -` (auto-detected via magic number; plain JS files like Cometix's cli.js are skipped)
6. Writes a backup next to the original (`<file>.backup-subagent-thinking-<timestamp>`)
7. If a file is already patched but its macOS signature is invalid (APFS clonefile side-effect), re-signs it automatically

## Troubleshooting

- **`--check` reports `未匹配` or `not found` after upgrade**
  The minifier renamed variables. Open the script and widen `{0,3}` to `{0,5}` in `PATTERN`, and `{1,5}` to `{1,7}` in `PATTERN_1M`.
- **macOS `claude` command is `killed` on launch**
  Signature invalidated. Run `python3 ... --check` or `codesign -v` to confirm, then re-run the patch.
- **Uninstall the patch**
  `--restore` reverts to the latest backup, or just reinstall with `npm install -g @anthropic-ai/claude-code@latest`.

## Limitations

- Assumes the JS bundle is embedded as **plain text**. If Anthropic starts compressing/encrypting it, this approach dies.
- Every `npm update -g` overwrites the binary, so patch + signature are lost — re-run the script.
- Not tested on Linux / Windows (Linux theoretically needs no codesign; the script already handles platform detection).

## Credits

- **Haleclipse** — original bug analysis, AST fix, and the 2.1.114 bun-migration writeup. All credit to him; this repo just extends his approach to the binary-distribution era.

> Full debugging log (in Chinese): [WRITEUP.md](WRITEUP.md) — covers the journey from the AST script failing to byte-level patching + codesign + Cometix compatibility.
