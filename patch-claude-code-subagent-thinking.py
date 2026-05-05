#!/usr/bin/env python3
"""
Claude Code SubAgent thinkingConfig 修复脚本 —— 版本无关的字节级 patch。

适配单可执行文件分发的 Claude Code（约 2.1.112~2.1.113 的 Node SEA、
2.1.114+ 的 Bun 编译产物），前提是 JS bundle 仍以明文嵌入二进制。

基于哈雷佬的 AST 修复思路（https://linux.do/t/topic/1991311）改写。
原脚本针对 `cli.js`，本脚本针对编译后的二进制，用等长度字节替换，
不改变 SEA / Bun blob 的偏移。

用法：
    python3 patch-claude-code-subagent-thinking.py              # 应用修复
    python3 patch-claude-code-subagent-thinking.py --check      # 只检查不改
    python3 patch-claude-code-subagent-thinking.py --restore    # 从最近备份还原
    python3 patch-claude-code-subagent-thinking.py --root PATH  # 手动指定安装路径

macOS 注意：Apple Silicon 对签名完整性有强制校验，任何字节修改都会让
原签名失效，启动时会被 kernel SIGKILL。本脚本在 patch 完之后自动
ad-hoc 重签（`codesign -s -`），本机使用足够了。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 宽松正则：兼容不同版本的 minifier 变量名变化。
# 捕获条件变量（X?）和 options 持有者（Y.），这样替换串能按同样长度重建。
PATTERN = re.compile(
    rb'thinkingConfig:'
    rb'(?P<cond>[A-Za-z_$][A-Za-z0-9_$]{0,3})\?'
    rb'(?P<obj>[A-Za-z_$][A-Za-z0-9_$]{0,3})\.options\.thinkingConfig:'
    rb'\{type:"disabled"\}'
)

# 识别已经 patch 过的形态（兼容任意 minifier 变量名），
# 这样重复运行不会误判为"未找到模式"。
PATCHED_PATTERN = re.compile(
    rb'thinkingConfig:/\*[\s]*\*/'
    rb'[A-Za-z_$][A-Za-z0-9_$]{0,3}\.options\.thinkingConfig'
)

MIN_BINARY_BYTES = 10 * 1024 * 1024  # 10 MB —— 过滤掉 wrapper 脚本
BACKUP_SUFFIX = ".backup-subagent-thinking-"


def is_backup(path: Path) -> bool:
    """脚本自己生成的备份文件不应再被当成候选目标。"""
    return BACKUP_SUFFIX in path.name


def find_install_root(override: str | None) -> Path | None:
    if override:
        p = Path(override).expanduser().resolve()
        return p if p.is_dir() else None
    candidates: list[Path] = []
    try:
        npm_root = subprocess.check_output(
            ["npm", "root", "-g"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if npm_root:
            # 同时支持官方包和 CometixSpace 的 cli.js 还原版
            candidates.append(Path(npm_root) / "@anthropic-ai" / "claude-code")
            candidates.append(Path(npm_root) / "@cometix" / "claude-code")
    except Exception:
        pass
    base_dirs = [
        Path.home() / ".claude/local/node_modules",
        Path("/usr/local/lib/node_modules"),
        Path("/usr/lib/node_modules"),
        Path("/opt/homebrew/lib/node_modules"),
    ]
    for base in base_dirs:
        candidates.append(base / "@anthropic-ai" / "claude-code")
        candidates.append(base / "@cometix" / "claude-code")
    # 原生安装器（2.1.120+ 推荐方式）：~/.local/share/claude/versions/<version>
    # 以及官方 install.sh 可能选择的其他布局。
    native_dirs = [
        Path.home() / ".local/share/claude",
        Path.home() / ".claude/local",
        Path("/usr/local/share/claude"),
        Path("/opt/claude"),
    ]
    for base in native_dirs:
        if (base / "versions").is_dir():
            candidates.append(base)
    for p in candidates:
        if p.is_dir():
            return p
    return None


def find_binaries(root: Path) -> list[Path]:
    """收集 wrapper bin + 每个平台子包里的二进制 + Cometix 还原的 cli.js
    + 原生安装器（~/.local/share/claude/versions/<ver>）下的裸二进制。"""
    found: list[Path] = []
    # 原生安装器布局：root/versions/<version>（单个 Mach-O / ELF，无子目录）
    versions_dir = root / "versions"
    if versions_dir.is_dir():
        for entry in sorted(versions_dir.iterdir()):
            if (
                entry.is_file()
                and not entry.is_symlink()
                and not is_backup(entry)
                and entry.stat().st_size >= MIN_BINARY_BYTES
            ):
                found.append(entry)
    # CometixSpace 还原版：根目录直接放 cli.js（不是二进制）
    cli_js = root / "cli.js"
    if cli_js.exists() and cli_js.is_file() and cli_js.stat().st_size >= MIN_BINARY_BYTES:
        found.append(cli_js)
    # 顶层 wrapper bin（postinstall 从平台子包复制过来）
    for name in ("claude", "claude.exe"):
        p = root / "bin" / name
        if p.exists() and p.is_file() and p.stat().st_size >= MIN_BINARY_BYTES:
            found.append(p)
    # 平台特定的子包
    sub = root / "node_modules" / "@anthropic-ai"
    if sub.is_dir():
        for pkg in sorted(sub.iterdir()):
            if not pkg.is_dir() or "claude-code-" not in pkg.name:
                continue
            for name in ("claude", "claude.exe"):
                p = pkg / name
                if p.exists() and p.is_file() and p.stat().st_size >= MIN_BINARY_BYTES:
                    found.append(p)
    # 按 real path 去重（处理 hardlink / symlink）
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in found:
        real = p.resolve()
        if real not in seen:
            seen.add(real)
            unique.append(p)
    return unique


def is_macho(path: Path) -> bool:
    """检测是否是 Mach-O 二进制（决定要不要 codesign）。"""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    # Mach-O magic numbers (32/64 bit, BE/LE, fat)
    return magic in (
        b"\xCA\xFE\xBA\xBE",  # fat
        b"\xFE\xED\xFA\xCE",  # 32-bit BE
        b"\xCE\xFA\xED\xFE",  # 32-bit LE
        b"\xFE\xED\xFA\xCF",  # 64-bit BE
        b"\xCF\xFA\xED\xFE",  # 64-bit LE
    )


def needs_codesign(path: Path) -> bool:
    """macOS 上只有 Mach-O 才需要重签；纯 JS 文件（如 Cometix 的 cli.js）跳过。"""
    return sys.platform == "darwin" and is_macho(path)


def build_replacement(match: re.Match) -> bytes:
    """构造等长度替换串，语义等价于始终继承父级 thinkingConfig。"""
    orig_len = match.end() - match.start()
    obj = match.group("obj").decode()
    # 目标形态：thinkingConfig:/*<填空>*/<obj>.options.thinkingConfig
    base = f"thinkingConfig:/**/{obj}.options.thinkingConfig".encode()
    pad = orig_len - len(base)
    if pad < 0:
        raise RuntimeError(
            f"替换模板比原匹配长（{len(base)} > {orig_len}），"
            "pattern / 模板不匹配"
        )
    replacement = (
        f"thinkingConfig:/*{' ' * pad}*/{obj}.options.thinkingConfig"
    ).encode()
    assert len(replacement) == orig_len
    return replacement


def codesign_adhoc(path: Path) -> None:
    """去掉原签名后做 ad-hoc 自签。仅 macOS 使用。"""
    subprocess.run(
        ["codesign", "--remove-signature", str(path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(["codesign", "-s", "-", str(path)], check=True)
    subprocess.run(["codesign", "-v", str(path)], check=True)


def codesign_is_valid(path: Path) -> bool:
    """检查二进制的代码签名是否有效（包括 ad-hoc 签名）。"""
    r = subprocess.run(
        ["codesign", "-v", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def patch_file(path: Path, check_only: bool) -> tuple[str, int, str]:
    """
    返回 (状态, 匹配数, 说明)。
    状态 ∈ {'patched', 'would_patch', 'already', 'not_found', 'error'}
    """
    data = path.read_bytes()
    matches = list(PATTERN.finditer(data))
    if not matches:
        if PATCHED_PATTERN.search(data):
            # 已 patch。但在 macOS 上，如果 npm 的 clonefile / hardlink
            # 把本文件和之前刚 patch 的兄弟二进制共享了存储，它的签名可能
            # 是坏的 —— 防御性重签一下，免得启动被 SIGKILL。
            if needs_codesign(path) and not check_only and not codesign_is_valid(path):
                try:
                    codesign_adhoc(path)
                    return ("already", 0, "已 patch，签名之前损坏 → 已重签")
                except subprocess.CalledProcessError as e:
                    return ("error", 0, f"已 patch 但重签失败：{e}")
            return ("already", 0, "已是 patched 形态")
        return ("not_found", 0, "未匹配到模式，版本可能不兼容")

    sample = matches[0]
    detail = f'匹配到 {sample.group(0).decode()!r}'

    if check_only:
        return ("would_patch", len(matches), detail)

    # 从右向左替换（虽然长度不变，保险起见）
    new_data = bytearray(data)
    for m in reversed(matches):
        new_data[m.start(): m.end()] = build_replacement(m)
    if len(new_data) != len(data):
        return ("error", 0, "长度发生变化 —— 放弃写入")

    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    backup = path.with_name(path.name + f".backup-subagent-thinking-{ts}")
    shutil.copy2(path, backup)
    path.write_bytes(bytes(new_data))

    extra = ""
    if needs_codesign(path):
        try:
            codesign_adhoc(path)
            extra = "，ad-hoc 重签完成"
        except subprocess.CalledProcessError as e:
            return ("error", len(matches), f"codesign 失败：{e}")

    return ("patched", len(matches), f"备份={backup.name}{extra}")


def restore_latest(path: Path) -> tuple[str, str]:
    parent = path.parent
    prefix = path.name + ".backup-subagent-thinking-"
    backups = sorted(parent.glob(prefix + "*"))
    if not backups:
        return ("no_backup", "未找到备份文件")
    latest = backups[-1]
    shutil.copy2(latest, path)
    extra = ""
    if needs_codesign(path):
        try:
            codesign_adhoc(path)
            extra = "，ad-hoc 重签完成"
        except subprocess.CalledProcessError as e:
            return ("error", f"已还原但重签失败：{e}")
    return ("restored", f"来源 {latest.name}{extra}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--check", action="store_true",
                    help="只检查状态，不修改任何文件")
    ap.add_argument("--restore", action="store_true",
                    help="从最近一次备份还原每个二进制")
    ap.add_argument("--root",
                    help="手动指定 @anthropic-ai/claude-code 安装路径"
                         "（省略时自动探测）")
    args = ap.parse_args()

    if args.check and args.restore:
        print("--check 和 --restore 不能同时使用", file=sys.stderr)
        return 2

    root = find_install_root(args.root)
    if not root:
        print("错误：找不到 @anthropic-ai/claude-code 安装目录。")
        print("     可以加 --root /path/to/@anthropic-ai/claude-code 手动指定")
        return 1
    print(f"安装目录：{root}")

    bins = find_binaries(root)
    if not bins:
        print(f"错误：此安装下未发现候选二进制"
              f"（查找大于 {MIN_BINARY_BYTES // (1024*1024)} MB 的文件）。")
        return 1
    print(f"发现 {len(bins)} 个二进制：")
    for b in bins:
        size_mb = b.stat().st_size / (1024 * 1024)
        print(f"  - {b}  ({size_mb:.0f} MB)")
    print()

    # 状态码到中文标签的映射（只做显示，不改变内部逻辑）
    status_zh = {
        "patched": "已修复",
        "would_patch": "待修复",
        "already": "已是修复状态",
        "not_found": "未匹配",
        "error": "失败",
        "restored": "已还原",
        "no_backup": "无备份",
    }

    any_error = False
    for b in bins:
        if args.restore:
            status, detail = restore_latest(b)
            tag = {"restored": "[+]", "no_backup": "[!]", "error": "[X]"}.get(status, "[?]")
            print(f"  {tag} {b.name}：{status_zh.get(status, status)} —— {detail}")
            if status in ("no_backup", "error"):
                any_error = True
            continue
        status, count, detail = patch_file(b, check_only=args.check)
        tag = {
            "patched": "[+]",
            "would_patch": "[?]",
            "already": "[=]",
            "not_found": "[!]",
            "error": "[X]",
        }.get(status, "[?]")
        msg = f"  {tag} {b.name}：{status_zh.get(status, status)}"
        if count:
            msg += f"（{count} 处）"
        msg += f" —— {detail}"
        print(msg)
        if status in ("not_found", "error"):
            any_error = True

    if not args.check and not args.restore and not any_error:
        print("\n请重启 Claude Code 让 patch 生效。")
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
