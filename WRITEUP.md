# 跟着哈雷佬两篇帖子踩坑 + 升级到 2.1.114：和 Claude Code 一起边调试边打 patch 的完整记录

> 起因是看到哈雷佬的两篇帖子：
>
> - **原帖**（SubAgent 和 Haiku 无法调用的解决办法）👉 <https://linux.do/t/topic/1991311>
> - **跟进帖**（2.1.114 换成 bun 构建的分析）👉 <https://linux.do/t/topic/1993426>
>
> 哈雷佬第一篇提供了一个 AST 脚本 `apply-claude-code-subagent-thinking-fix.sh` 修 SubAgent `thinkingConfig` 硬编码成 `disabled` 的问题，第二篇又接着分析了 2.1.114 之后 npm 包从 Node 兼容制品整体换成 bun 版的影响。我两篇都看了，照着第一篇的脚本一把梭跑，没跑通。这篇是我跟 Claude Code 对话一步步把它治好的过程，包括后来升级 2.1.114 之后又踩的新坑。不是教程，是 debug log，发出来给踩同坑的朋友参考，不一定对，欢迎指正。

## 我的环境

- macOS 15（Apple Silicon, arm64）
- Claude Code 开始时是 `2.1.113`，后来升到 `2.1.114`（nvm 下 `npm i -g` 装的）
- base_url 指向某第三方中转

## 第一步：哈雷佬的脚本直接 NOT_FOUND

在 2.1.113 上跑 `apply-claude-code-subagent-thinking-fix.sh --check`：

```
[X] No thinkingConfig conditional found in SubAgent launcher context
```

以为自己装错路径了，折腾半天才意识到 —— Claude Code 从某个版本开始，**npm 包里已经没有 `cli.js`**：

```bash
$ ls ~/.nvm/versions/node/v24.14.0/lib/node_modules/@anthropic-ai/claude-code/
bin/  cli-wrapper.cjs  install.cjs  node_modules/  package.json  ...
# ↑ 没有 cli.js

$ file bin/claude.exe
bin/claude.exe: Mach-O 64-bit executable arm64
$ ls -lh bin/claude.exe
-rwxr-xr-x  1 me  staff  204M
```

一个 **204MB 的 Mach-O 可执行文件**。哈雷佬第二篇帖子里讲得很清楚：npm 包里的 `cli.js` 和对 Node 的兼容运行制品已经被换成 bun 编译产物，顶层只剩一个 `cli-wrapper.cjs` 当调度器拉取平台特定的二进制。脚本是用 acorn 去 parse `cli.js` 的，当然 `NOT_FOUND`。

## 第二步：Claude Code 帮我确认 JS 还是以明文嵌入

不太确定这 200 多 MB 里究竟是啥，让 Claude Code 用 `strings` 扫了一下：

```bash
strings bin/claude.exe | grep -E "thinkingConfig|appendSubagentSystemPrompt" | head
```

直接扫出 React/Ink 相关的 JSX 编译产物、`thinkingConfig`、`appendSubagentSystemPrompt`，全是明文。

也就是说虽然顶层是二进制分发，**JS bundle 还是以纯文本塞在二进制里**（bun 的 single-executable 打包机制和 Node SEA 类似）。这解释了为什么体积那么大，也意味着哈雷佬原脚本的 AST 路线不可行，但**字节级替换还有戏**。哈雷佬第二篇也提到"解包还出来 cli.js 也可以"、"114 目前解出来的仍然可以 node 来跑"，印证了 JS 内容还没加密压缩。

（Claude Code 解释这些时我半信半疑，后来自己 `strings | head` 亲眼看到熟悉的 JSX 才死心。）

## 第三步：定位要改的字节

用宽松正则在二进制里找哈雷佬脚本要替换的那个条件表达式：

```bash
BIN=~/.nvm/versions/node/v24.14.0/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
grep -oaE 'thinkingConfig:[A-Za-z_$][A-Za-z0-9_$]{0,3}\?[A-Za-z_$][A-Za-z0-9_$]{0,3}\.options\.thinkingConfig:\{type:"disabled"\}' "$BIN"
```

输出：

```
thinkingConfig:P?q.options.thinkingConfig:{type:"disabled"}
thinkingConfig:P?q.options.thinkingConfig:{type:"disabled"}
```

两条完全一样。Claude Code 又拉了每个 match 前后 ±4KB 的上下文，确认两处都带 `appendSubagentSystemPrompt` 这个 SubAgent launcher 的标志。两处都改是 OK 的（bundle 里被打包了两份，没深究）。

另外 Claude Code 提醒我：平台子包 `node_modules/@anthropic-ai/claude-code-darwin-arm64/claude` 本身也是一个独立的 204MB 二进制，`bin/claude.exe` 是从它复制过来的副本（两个 inode 不同），**两个都得改**。

## 第四步：字节级等长度替换

- 原：`thinkingConfig:P?q.options.thinkingConfig:{type:"disabled"}`（59 字节）
- 新：`thinkingConfig:/*                */q.options.thinkingConfig`（59 字节，用注释填空格凑等长）

JS 语义上等价于"始终继承父级 thinkingConfig"，长度不变所以不会破坏 bun/SEA blob 偏移。

## 第五步：macOS 上第一次跪了 —— 启动即 `killed`

```
$ claude
[1]    25312 killed     claude
```

反复重试都是 SIGKILL（137）。Claude Code 告诉我这是 Apple Silicon 对签名二进制的完整性校验：**任何字节修改都会让原签名失效，kernel 拒绝加载**。

这个坑哈雷佬的 Linux / JS 版脚本没覆盖。先回滚备份 → 重新 patch → 再 ad-hoc 重签：

```bash
codesign --remove-signature "$BIN"
codesign -s - "$BIN"        # ad-hoc 本地自签
codesign -v "$BIN"          # 校验通过
```

两个二进制都签完之后 `claude --version` 能起来了。

（我本来以为 codesign 命令要 Apple 开发者账号，其实 `-s -` 是 ad-hoc 签名，本地自签，任何人都能用。这个是 Claude Code 告诉我的，查了 `man codesign` 确认。）

## 第六步：验证 SubAgent 恢复

重启 Claude Code 后让它自己 spawn Haiku 和 Opus 两个 subagent 分别调用工具跑小任务，都正常返回结果。修复前是连 subagent 启动都启不来，修复后 subagent 能正常发 thinking 字段上去。

## 第七步：升到 2.1.114 又踩一个新坑 —— APFS clonefile 副作用

看到哈雷佬第二篇讲 114 换 bun 之后，我手贱升了一下试试：

```bash
npm install -g @anthropic-ai/claude-code@latest
```

装上之后还是 2 个二进制各 2 处原 pattern，脚本识别正常。但一 patch 完发现个怪现象：

```
[+] claude.exe: patched (2 occurrences) — re-signed ad-hoc
[=] claude:     already — patched form already present
```

**只有第一个被脚本 patch 并重签了，第二个报"已 patched"**。但它们明明是不同 inode、不同大小、npm 刚装完的新文件。查了下：

```bash
$ codesign -v "$BIN" && echo OK
OK
$ codesign -v "$SUB" && echo OK
/.../claude: invalid signature (code or signature have been modified)
```

第二个文件**内容也是 patched 的，但签名是坏的**（会 SIGKILL）。脚本根本没写过它。

Claude Code 的推测是：npm 在 2.1.114 的 postinstall 用了 **APFS clonefile**（Apple 的 copy-on-write 拷贝），让 `bin/claude.exe` 和子包 `claude` 底层共享存储块。我 patch 第一个时，CoW 的具体行为把第二个文件的数据部分也改了，但 load command 里的签名 section 只在 `bin/claude.exe` 被我显式 codesign 修过，子包那份保留着原 Anthropic 签名的元数据指向新内容 → 签名自然 invalid。

不完全确定是不是 clonefile 准确引起的，但**症状是确定的**。修法也简单 —— 把第二个也 ad-hoc 重签一下：

```bash
codesign --remove-signature "$SUB"
codesign -s - "$SUB"
```

为了以后升级不再踩这个边界，我把脚本改成：**即使检测到已经 patched，也会在 macOS 上校验签名，坏了就自动重签**。

## 一把梭脚本（macOS / Linux 通用，Python）

保存为 `patch-claude-code-subagent-thinking.py`：

```python
#!/usr/bin/env python3
"""
Claude Code SubAgent thinkingConfig fix — 版本无关的字节级 patch。

适配单可执行文件分发（2.1.112~2.1.113 的 Node SEA、2.1.114+ 的 bun compile），
前提是 JS bundle 仍以明文嵌入二进制。
"""

import argparse, os, re, shutil, subprocess, sys, time
from pathlib import Path

PATTERN = re.compile(
    rb'thinkingConfig:'
    rb'(?P<cond>[A-Za-z_$][A-Za-z0-9_$]{0,3})\?'
    rb'(?P<obj>[A-Za-z_$][A-Za-z0-9_$]{0,3})\.options\.thinkingConfig:'
    rb'\{type:"disabled"\}'
)
PATCHED_PATTERN = re.compile(
    rb'thinkingConfig:/\*[\s]*\*/'
    rb'[A-Za-z_$][A-Za-z0-9_$]{0,3}\.options\.thinkingConfig'
)
MIN_BINARY_BYTES = 10 * 1024 * 1024

def find_install_root(override):
    if override:
        p = Path(override).expanduser().resolve()
        return p if p.is_dir() else None
    candidates = []
    try:
        npm_root = subprocess.check_output(["npm", "root", "-g"], text=True, stderr=subprocess.DEVNULL).strip()
        if npm_root:
            candidates.append(Path(npm_root) / "@anthropic-ai" / "claude-code")
    except Exception:
        pass
    candidates += [
        Path.home() / ".claude/local/node_modules/@anthropic-ai/claude-code",
        Path("/usr/local/lib/node_modules/@anthropic-ai/claude-code"),
        Path("/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code"),
    ]
    return next((p for p in candidates if p.is_dir()), None)

def find_binaries(root):
    found = []
    for name in ("claude", "claude.exe"):
        p = root / "bin" / name
        if p.exists() and p.stat().st_size >= MIN_BINARY_BYTES:
            found.append(p)
    sub = root / "node_modules" / "@anthropic-ai"
    if sub.is_dir():
        for pkg in sorted(sub.iterdir()):
            if "claude-code-" not in pkg.name:
                continue
            for name in ("claude", "claude.exe"):
                p = pkg / name
                if p.exists() and p.stat().st_size >= MIN_BINARY_BYTES:
                    found.append(p)
    seen, unique = set(), []
    for p in found:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(p)
    return unique

def build_replacement(match):
    orig_len = match.end() - match.start()
    obj = match.group("obj").decode()
    base = f"thinkingConfig:/**/{obj}.options.thinkingConfig".encode()
    pad = orig_len - len(base)
    if pad < 0:
        raise RuntimeError("replacement longer than match")
    return f"thinkingConfig:/*{' '*pad}*/{obj}.options.thinkingConfig".encode()

def codesign_adhoc(path):
    subprocess.run(["codesign", "--remove-signature", str(path)], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["codesign", "-s", "-", str(path)], check=True)
    subprocess.run(["codesign", "-v", str(path)], check=True)

def codesign_is_valid(path):
    return subprocess.run(["codesign", "-v", str(path)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

def patch_file(path, check_only):
    data = path.read_bytes()
    matches = list(PATTERN.finditer(data))
    if not matches:
        if PATCHED_PATTERN.search(data):
            # 关键：已 patched 但 macOS 签名坏掉（APFS clonefile 副作用）时补签
            if sys.platform == "darwin" and not check_only and not codesign_is_valid(path):
                codesign_adhoc(path)
                return ("already", 0, "patched; signature was broken → re-signed")
            return ("already", 0, "patched form already present")
        return ("not_found", 0, "no matching pattern")
    if check_only:
        return ("would_patch", len(matches), f"found {matches[0].group(0).decode()!r}")
    new_data = bytearray(data)
    for m in reversed(matches):
        new_data[m.start():m.end()] = build_replacement(m)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    backup = path.with_name(path.name + f".backup-subagent-thinking-{ts}")
    shutil.copy2(path, backup)
    path.write_bytes(bytes(new_data))
    if sys.platform == "darwin":
        codesign_adhoc(path)
    return ("patched", len(matches), f"backup={backup.name}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root")
    args = ap.parse_args()
    root = find_install_root(args.root)
    if not root:
        print("ERROR: install not found; use --root")
        return 1
    print(f"Install root: {root}")
    bins = find_binaries(root)
    if not bins:
        print("ERROR: no candidate binaries")
        return 1
    for b in bins:
        print(f"  - {b}  ({b.stat().st_size // (1024*1024)} MB)")
    print()
    any_err = False
    for b in bins:
        status, count, detail = patch_file(b, args.check)
        tag = {"patched":"[+]","would_patch":"[?]","already":"[=]","not_found":"[!]","error":"[X]"}[status]
        print(f"  {tag} {b.name}: {status}" + (f" ({count})" if count else "") + f" — {detail}")
        if status in ("not_found","error"):
            any_err = True
    if not args.check and not any_err:
        print("\nRestart Claude Code for the patch to take effect.")
    return 1 if any_err else 0

if __name__ == "__main__":
    sys.exit(main())
```

用法：

```bash
python3 patch-claude-code-subagent-thinking.py --check   # 只检查，不改
python3 patch-claude-code-subagent-thinking.py           # 应用 patch + 自动重签
python3 patch-claude-code-subagent-thinking.py --root /path/to/claude-code  # 手动指定
```

Windows 上把 codesign 那几个 subprocess.run 包裹成只在 darwin 执行（脚本里已经加了 `sys.platform == "darwin"` 判断，Linux / Windows 直接跳过）。

## 一些我不确定的事

- 不同版本 minifier 出来的变量名不一定还是 `P` / `q`。脚本用了宽松正则兼容变量名变化，但不敢保证未来的 bun build 会不会改生成形式。
- 不知道 Claude Code 后续会不会把 JS 压缩/加密塞进 blob（哈雷佬第二篇也提到这个可能性："如果某日开始 cch 的机制更进一步的完全强硬实施..."）。真压了字节 patch 就没戏了，得走 bun 或 Node SEA 的 blob 提取重注入，麻烦很多。
- Linux 应该不需要重签步骤，但我没 Linux 机器测。
- 哈雷佬的 AST 脚本本身在旧版本 JS 分发上还是最干净的思路，我这个只是 native 分发之后的妥协方案。
- `npm update -g` 覆盖后 patch 和签名都会丢，每次升级后要重跑脚本。
- 升级到 2.1.114 之后的 APFS clonefile 副作用我不完全确定是不是 clonefile 准确造成的，但现象确定存在，脚本已处理。

## 致谢

全程是跟 Claude Code 一句一句边问边做试出来的，定位明文嵌入、想出等长度注释填充、发现 codesign 的坑、以及后来诊断 2.1.114 的 clonefile 副作用这几步都是它先指路的，我主要负责确认和点确定。所以也不敢说这个路子一定对，只是现在我机器上能跑。哈雷佬那两篇原帖我来回翻了好几遍，尤其是第二篇对 114 bun 化的分析让我立刻知道升级不是死路，多谢大佬 🙏。
