from dataclasses import dataclass
import os
import shutil
from concurrent.futures import as_completed, ThreadPoolExecutor

from lemony_utils.media import convert_audio

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
                if sum(((i in sfile) for i in IGNORE_KWLIST)):
                    stat.ignore += 1
                    continue
                if os.path.exists(dfile):
                    if os.path.getsize(dfile) > 0 and os.path.getmtime(
                        sfile
                    ) <= os.path.getmtime(dfile):
                        stat.skip += 1
                        continue
                    os.remove(dfile)
                    stat.override += 1
                else:
                    stat.create += 1
            else:
                if os.path.exists(dfile):
                    if os.path.getsize(dfile) > 0 and os.path.getmtime(
                        sfile
                    ) <= os.path.getmtime(dfile):
                        stat.skip += 1
                        continue
                    os.remove(dfile)
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
            shutil.rmtree(droot)
            stat.dfolder += 1
            continue
        for dfilename in dfilenames:
            bare, ext = os.path.splitext(dfilename)
            if ext.lower() not in EXPECTED_EXTS:
                continue
            dfile = os.path.join(droot, dfilename)
            if sum(((i in dfile) for i in IGNORE_KWLIST)):
                stat.ignore += 1
                continue
            flag = 0
            for ext in EXPECTED_EXTS + COPY_EXTS:
                sfile = os.path.join(sroot, (bare + ext))
                if os.path.exists(sfile):
                    flag = 1
                    break
            if flag == 0:
                os.remove(dfile)
                stat.dfile += 1
    return stat


if __name__ == "__main__":
    srcdir = input("src:")
    dstdir = input("dst:")
    counter = 0
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = []
        gen = straight_sync(srcdir, dstdir)
        ret = None
        while True:
            try:
                args, kwargs = next(gen)
                futures.append(
                    executor.submit(
                        lambda *args_, **kwargs_: (
                            convert_audio(*args_, **kwargs_),
                            *args_,
                        ),
                        *args,
                        **kwargs,
                        check=False,
                    )
                )
            except StopIteration as e:
                ret = e.value
                break
        for future in as_completed(futures):
            print(counter := counter + 1, ", code =", *future.result(), sep="\t")
        print(ret)
    print(reversed_sync(srcdir, dstdir))
