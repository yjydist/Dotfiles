#!/usr/bin/env python3

# 基于 fuzzel 的壁纸选择器
#
# 依赖:
# - fuzzel
# - libvips 的 vipsthumbnail(Linux 推荐, 必需, 用于生成缩略图)
# - swww(设置壁纸)
# 注意: 脚本不做命令检测, 请自行确保上述工具已安装并在 PATH 中.
#
# 使用方式:
# - 直接运行: python3 wallpaper-picker.py
# - 如需自定义: 编辑脚本顶部的全局变量(WALLPAPER_DIRS, THUMB_SIZE, LINES, WIDTH, FUZZEL_ARGS)

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

# 全局配置(修改这里即可, 不需要命令行参数)
PROMPT = "WALLPAPER: "
THUMB_SIZE = 256
LINES = 10
WIDTH = 60
# 额外传给 fuzzel 的参数(示例: ["--minimal-lines", "--icon-theme=default"])
FUZZEL_ARGS: List[str] = []
# 支持的图片后缀
DEFAULT_EXTS = ("jpg", "jpeg", "png")
# 壁纸目录(按顺序扫描)
WALLPAPER_DIRS = [
    "~/.local/share/backgrounds",
    "~/Pictures/Wallpapers",
    "~/Wallpapers",
    "~/Pictures",
    "/usr/share/backgrounds",
]
# 缩略图缓存目录(全局固定路径)
THUMB_CACHE_DIR = Path(os.path.expanduser("~/.cache/wallpaper-thumbs")).resolve()


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)

# 创建目录(包含父目录), 若已存在则不报错
def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

# 过滤存在的目录, 返回有效目录列表
def existing_dirs(paths: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        if p.is_dir():
            out.append(p)
    return out

# 使用 vipsthumbnail 生成/复用缩略图(size x size), 成功返回 PNG 路径; 失败返回 None
def make_thumb(src: Path, size: int) -> Optional[Path]:
    ensure_dir(THUMB_CACHE_DIR)
    # 注意: 按文件名缓存, 例: 1.jpg -> 1.jpg.png, 1.png -> 1.png.png, 不会冲突
    out = THUMB_CACHE_DIR / f"{src.name}.png"
    if out.exists():
        return out

    try:
        # vipsthumbnail 会根据输出扩展名写出相应格式
        cmd = [
            "vipsthumbnail",
            str(src),
            "--size",
            f"{size}x{size}",
            "--crop",
            "centre",
            "--output",
            str(out),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return out if out.exists() else None
    except Exception:
        return None


# 非递归扫描指定目录顶层, 收集给定扩展名的图片, 返回绝对路径列表
def scan_images(dirs: Sequence[Path], exts: Tuple[str, ...]) -> List[Path]:
    lower_exts = {e.lower() for e in exts}
    results: List[Path] = []
    for base in dirs:
        try:
            # 仅列出顶层文件, 不进入子目录
            for name in os.listdir(base):
                p = Path(base) / name
                if p.is_file():
                    ext = p.suffix.lower().lstrip(".")
                    if ext in lower_exts:
                        try:
                            results.append(p.resolve())
                        except Exception:
                            results.append(p)
        except Exception as ex:
            eprint(f"Warning: failed to scan {base}: {ex}")
    # 按文件名排序, 保证稳定展示顺序
    results.sort(key=lambda p: p.name.lower())
    return results


# 构造 fuzzel 的 dmenu 输入; 每行包含 NUL 分隔的图标元数据; 返回 bytes 以保留 NUL
def build_fuzzel_input(files: Sequence[Path], thumb_size: int) -> bytes:
    out_chunks: List[bytes] = []
    for img in files:
        base = img.name
        img_abs = str(img)
        thumb_p = make_thumb(img, thumb_size)
        if thumb_p is not None:
            line = f"{base}\t{img_abs}\0icon\x1f{thumb_p}\n"
        else:
            line = f"{base}\t{img_abs}\n"
        out_chunks.append(line.encode("utf-8", errors="ignore"))
    return b"".join(out_chunks)


# 调用 fuzzel dmenu: 显示第一列, 接受第二列; 返回所选完整路径(取消返回空)
def run_fuzzel(prompt: str, lines: int, width: int, input_bytes: bytes) -> str:
    args = [
        "fuzzel",
        "--dmenu",
        "--with-nth=1",
        "--accept-nth=2",
        f"--lines={int(lines)}",
        f"--width={int(width)}",
        f"--prompt={prompt}",
    ]

    # 直接使用脚本顶部的 FUZZEL_ARGS
    if FUZZEL_ARGS:
        args.extend(FUZZEL_ARGS)

    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    try:
        stdout_data, _ = proc.communicate(input=input_bytes)
    except Exception:
        proc.kill()
        raise

    if proc.returncode not in (0, 1):  # 1 表示取消
        # 非致命: 当作取消
        pass

    # fuzzel 输出的是被 --accept-nth=2 接受的第二列(完整路径)
    sel = stdout_data.decode("utf-8", errors="ignore").strip()
    return sel


# cmd 
# check
def run_cmd(cmd: Sequence[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=check,
    )


# 使用 swww 设置壁纸: 若未初始化则 init; 优先使用过渡参数, 失败回退基础设置
def set_with_swww(img: Path) -> bool:
    # 如果 swww 未初始化则初始化, 忽略错误
    try:
        run_cmd(["swww", "init"], check=False)  # 若已在运行会自行忽略
    except Exception:
        pass

    # 优先使用过渡参数
    rc = run_cmd(
        [
            "swww",
            "img",
            str(img),
            "--transition-type=grow",
            "--transition-fps=60",
            "--transition-duration=0.35",
        ],
        check=False,
    ).returncode
    if rc == 0:
        return True

    # 回退为不带过渡参数的设置
    rc2 = run_cmd(["swww", "img", str(img)], check=False).returncode
    return rc2 == 0


def set_wallpaper(img: Path) -> bool:
    # 只使用 swww 设置壁纸（脚本精简化，不再支持环境变量覆盖）
    return set_with_swww(img)


# 不再使用命令行参数; 从脚本顶部全局变量获取配置
def resolve_dirs() -> List[Path]:
    return existing_dirs([Path(os.path.expanduser(p)).resolve() for p in WALLPAPER_DIRS])


def main() -> int:
    dirs = resolve_dirs()
    if not dirs:
        eprint("No valid wallpaper directories found.")
        eprint("Edit WALLPAPER_DIRS at the top of the script.")
        return 1

    # 假定系统已安装 vipsthumbnail; 不做存在性检测

    images = scan_images(dirs, DEFAULT_EXTS)
    if not images:
        eprint("No images found in the provided directories.")
        return 0

    input_bytes = build_fuzzel_input(images, THUMB_SIZE)

    try:
        selected = run_fuzzel(PROMPT, LINES, WIDTH, input_bytes)
    except Exception as ex:
        eprint(f"Failed to run fuzzel: {ex}")
        return 1

    if not selected:
        # 用户取消
        return 0

    img_path = Path(selected)


    if not set_wallpaper(img_path):
        eprint(f"Failed to set wallpaper via swww. Selected: {img_path}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
