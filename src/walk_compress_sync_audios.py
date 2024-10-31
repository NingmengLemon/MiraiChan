from dataclasses import dataclass
import os
import shutil

import psutil

from lemony_utils.media import convert_audio

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

IGNORE_KWLIST = ("SyncToy_",)


@dataclass
class StraiStat:
    create: int = 0
    skip: int = 0
    override: int = 0
    ignore: int = 0


@dataclass
class RevStat:
    dfile: int = 0
    dfolder: int = 0
    ignore: int = 0


def straight_sync(src: str, dst: str):
    src = os.path.normpath(os.path.abspath(src))
    dst = os.path.normpath(os.path.abspath(dst))
    stat = StraiStat()

    for sroot, _, sfilenames in os.walk(src):
        droot = sroot.replace(src, dst)
        for sfilename in sfilenames:
            if os.path.splitext(sfilename)[1].lower() not in EXPECTED_EXTS:
                stat.ignore += 1
                continue
            sfile = os.path.join(sroot, sfilename)
            dfile = os.path.join(droot, os.path.splitext(sfilename)[0] + ".mp3")
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
            if not os.path.exists(droot):
                os.makedirs(droot, exist_ok=True)
            convert_audio(sfile, dfile, quality="128k")
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
        for dfilename in dfilenames:
            if os.path.splitext(dfilename)[1].lower() not in EXPECTED_EXTS:
                stat.ignore += 1
                continue
            dfile = os.path.join(sroot, dfilename)
            if sum(((i in dfile) for i in IGNORE_KWLIST)):
                stat.ignore += 1
                continue
            for ext in EXPECTED_EXTS:
                sfile = os.path.join(droot, ext)
                if os.path.exists(sfile):
                    continue
            os.remove(dfile)
            stat.dfile += 1
    return stat


if __name__ == "__main__":
    srcdir = input("src:")
    dstdir = input("dst:")
    print(straight_sync(srcdir, dstdir))
    print(reversed_sync(srcdir, dstdir))
