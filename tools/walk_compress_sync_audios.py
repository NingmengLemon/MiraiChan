import argparse
import contextlib
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from lemony_media.ffmpeg import convert_audio

# 因为不可能把我的(大部分)无损曲库用于音乐抽签（出于带宽和服务器的存储容量考虑）
# 所以试图写了这样一个

EXPECTED_EXTS = (
    ".flac",
    ".mp3",
    ".wav",
    ".aac",
    ".m4a",
    ".ape",
    ".alac",
    ".ogg",
)
TO_EXT = ".mp3"
COPY_EXTS = (".lrc",)

IGNORE_KWLIST = ("SyncToy_",)


def _within(root: str, path: str) -> bool:
    try:
        root_real = os.path.realpath(root)
        return os.path.normcase(
            os.path.commonpath([root_real, os.path.realpath(path)])
        ) == os.path.normcase(root_real)
    except ValueError:
        return False


def _safe_remove(root: str, path: str) -> None:
    if not _within(root, path):
        raise RuntimeError(f"拒绝删除目录外的路径: {path}")
    if os.path.normcase(os.path.realpath(path)) == os.path.normcase(
        os.path.realpath(root)
    ):
        raise RuntimeError(f"拒绝删除同步根目录本身: {path}")
    os.remove(path)


def _relative_to(root: str, path: str) -> str:
    """root 下的相对路径; 跨盘符时 relpath 会拒绝, 退回前缀切片。"""
    try:
        return os.path.relpath(path, root)
    except ValueError:
        root_abs = os.path.abspath(root)
        path_abs = os.path.abspath(path)
        root_key = os.path.normcase(root_abs)
        path_key = os.path.normcase(path_abs)
        if path_key == root_key:
            return "."
        prefix = root_key + os.sep
        if not path_key.startswith(prefix):
            raise
        return path_abs[len(root_abs) :].lstrip("\\/")


def _prepare_roots(src: str, dst: str) -> tuple[str, str]:
    """规范化并校验同步两端, 避免把目标根目录当成待清理的旧目录。"""
    src = os.path.normpath(os.path.abspath(src))
    dst = os.path.normpath(os.path.abspath(dst))
    if not os.path.isdir(src):
        raise ValueError(f"源目录不存在或不是目录: {src}")
    src_real = os.path.realpath(src)
    dst_real = os.path.realpath(dst)
    src_key = os.path.normcase(src_real)
    dst_key = os.path.normcase(dst_real)
    if src_key == dst_key:
        raise ValueError("源目录和目标目录不能相同")
    try:
        common = os.path.normcase(os.path.commonpath([src_real, dst_real]))
    except ValueError:
        common = None
    if common in (src_key, dst_key):
        raise ValueError("源目录和目标目录不能互相包含")
    return src, dst


@dataclass
class StraiStat:
    create: int = 0
    skip: int = 0
    override: int = 0
    ignore: int = 0
    copy: int = 0


@dataclass
class RevStat:
    dfile: int = 0
    dfolder: int = 0
    ignore: int = 0


def straight_sync(src: str, dst: str):
    src, dst = _prepare_roots(src, dst)
    os.makedirs(dst, exist_ok=True)
    stat = StraiStat()

    for sroot, _, sfilenames in os.walk(src):
        rel = _relative_to(src, sroot)
        droot = os.path.normpath(os.path.join(dst, rel))
        for sfilename in sfilenames:
            ext = os.path.splitext(sfilename)[1].lower()
            if ext not in EXPECTED_EXTS and ext not in COPY_EXTS:
                stat.ignore += 1
                continue
            sfile = os.path.join(sroot, sfilename)
            dfile = os.path.join(
                droot,
                os.path.splitext(sfilename)[0]
                + (TO_EXT if ext in EXPECTED_EXTS else ext),
            )
            if not os.path.exists(droot):
                os.makedirs(droot, exist_ok=True)
            if ext in EXPECTED_EXTS:
                if sum((i in sfile) for i in IGNORE_KWLIST):
                    stat.ignore += 1
                    continue
                if os.path.exists(dfile):
                    if os.path.getsize(dfile) > 0 and os.path.getmtime(
                        sfile
                    ) <= os.path.getmtime(dfile):
                        stat.skip += 1
                        continue
                    # 交给 ffmpeg -y 覆盖; 失败时至少不会先把旧文件删掉
                    stat.override += 1
                else:
                    stat.create += 1
            else:
                if (
                    os.path.exists(dfile)
                    and os.path.getsize(dfile) > 0
                    and os.path.getmtime(sfile) <= os.path.getmtime(dfile)
                ):
                    stat.skip += 1
                    continue
                shutil.copyfile(sfile, dfile)
                stat.copy += 1
                continue
            yield (sfile, dfile)
    return stat


def reversed_sync(src: str, dst: str):
    src, dst = _prepare_roots(src, dst)
    stat = RevStat()

    for droot, _, dfilenames in os.walk(dst):
        rel = _relative_to(dst, droot)
        sroot = os.path.normpath(os.path.join(src, rel))
        if os.path.exists(droot) and not os.path.exists(sroot):
            if os.path.normcase(os.path.realpath(droot)) == os.path.normcase(
                os.path.realpath(dst)
            ):
                continue
            if not _within(dst, droot):
                raise RuntimeError(f"拒绝删除目录外的路径: {droot}")
            shutil.rmtree(droot)
            stat.dfolder += 1
            continue
        for dfilename in dfilenames:
            bare, ext = os.path.splitext(dfilename)
            if ext.lower() not in EXPECTED_EXTS:
                continue
            dfile = os.path.join(droot, dfilename)
            if sum((i in dfile) for i in IGNORE_KWLIST):
                stat.ignore += 1
                continue
            flag = 0
            for ext in EXPECTED_EXTS + COPY_EXTS:
                sfile = os.path.join(sroot, (bare + ext))
                if os.path.exists(sfile):
                    flag = 1
                    break
            if flag == 0:
                _safe_remove(dst, dfile)
                stat.dfile += 1
    return stat


def _convert(source: str, target: str, timeout: float) -> tuple[int, str]:
    stem, suffix = os.path.splitext(target)
    part = f"{stem}.part{suffix}"
    try:
        code = convert_audio(source, part, quality="128k", timeout=timeout)
        os.replace(part, target)
        return code, target
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.remove(part)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="批量同步并压缩音乐库")
    parser.add_argument("src", nargs="?")
    parser.add_argument("dst", nargs="?")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    srcdir = args.src or input("src:")
    dstdir = args.dst or input("dst:")

    counter = 0
    failed: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = []
        gen = straight_sync(srcdir, dstdir)
        ret = None
        while True:
            try:
                conv_args = next(gen)
            except StopIteration as exc:
                ret = exc.value
                break
            except Exception as exc:  # noqa: BLE001 - 扫描失败要转成非零退出码
                print(
                    f"扫描源目录失败: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                return 1
            futures.append(
                executor.submit(_convert, conv_args[0], conv_args[1], args.timeout)
            )
        for future in as_completed(futures):
            try:
                code, target = future.result()
            except Exception as exc:  # noqa: BLE001 - 汇总转换失败
                failed.append(exc)
                print(f"转换失败: {exc}", file=sys.stderr)
                continue
            counter += 1
            print(counter, target, "code =", code, sep="\t")
        print(ret)

    if failed:
        print(f"{len(failed)} 个文件转换失败, 未执行反向清理", file=sys.stderr)
        return 1
    print(reversed_sync(srcdir, dstdir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
