import argparse
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
        return os.path.commonpath(
            [os.path.abspath(root), os.path.abspath(path)]
        ) == os.path.abspath(root)
    except ValueError:
        return False


def _safe_remove(root: str, path: str) -> None:
    if not _within(root, path):
        raise RuntimeError(f"拒绝删除目录外的路径: {path}")
    os.remove(path)


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
    src = os.path.normpath(os.path.abspath(src))
    dst = os.path.normpath(os.path.abspath(dst))
    os.makedirs(dst, exist_ok=True)
    stat = StraiStat()

    for sroot, _, sfilenames in os.walk(src):
        droot = sroot.replace(src, dst)
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
            yield (sfile, dfile), {"quality": "128k"}
    return stat


def reversed_sync(src: str, dst: str):
    src = os.path.normpath(os.path.abspath(src))
    dst = os.path.normpath(os.path.abspath(dst))
    stat = RevStat()

    for droot, _, dfilenames in os.walk(dst):
        sroot = droot.replace(dst, src)
        if os.path.exists(droot) and not os.path.exists(sroot):
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


def _convert(source: str, target: str, timeout: float) -> int:
    return convert_audio(source, target, quality="128k", timeout=timeout)


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
                conv_args, _kwargs = next(gen)
            except StopIteration as exc:
                ret = exc.value
                break
            except Exception:  # noqa: BLE001 - 扫描失败要转成非零退出码
                print("扫描源目录失败", file=sys.stderr)
                return 1
            futures.append(
                executor.submit(_convert, conv_args[0], conv_args[1], args.timeout)
            )
        for future in as_completed(futures):
            try:
                code = future.result()
            except Exception as exc:  # noqa: BLE001 - 汇总转换失败
                failed.append(exc)
                print(f"转换失败: {exc}", file=sys.stderr)
                continue
            counter += 1
            print(counter, "code =", code)
        print(ret)

    if failed:
        print(f"{len(failed)} 个文件转换失败, 未执行反向清理", file=sys.stderr)
        return 1
    print(reversed_sync(srcdir, dstdir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
