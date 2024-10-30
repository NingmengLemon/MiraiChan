import subprocess
from typing import Optional

from .asyncutils import run_as_async_decorator


def call_ffmpeg(*args, check=True):
    cmd = ["ffmpeg", "-loglevel", "quiet", "-nostdin", "-hide_banner"]
    cmd.extend(args)
    p = subprocess.run(cmd, capture_output=True, text=True, check=check)
    return p.returncode


async_call_ffmpeg = run_as_async_decorator()(call_ffmpeg)


def merge_avfile(
    au_file: Optional[str],
    vi_file: str,
    output_file: str,
    cover_image: Optional[str] = None,
    metadata: Optional[dict[str, str]] = None,
) -> int:
    """调用ffmpeg进行合流，并能添加元数据"""
    args = ["-i", vi_file]
    if au_file:
        args.extend(["-i", au_file])
    if cover_image:
        args.extend(["-i", cover_image])

    if au_file and cover_image:
        args.extend(["-map", "0", "-map", "1", "-map", "2"])
    elif au_file:
        args.extend(["-map", "0", "-map", "1"])
    elif cover_image:
        args.extend(["-map", "0", "-map", "1"])
    else:
        args.extend(["-map", "0"])

    args.extend(["-c", "copy"])

    if metadata:
        for key, value in metadata.items():
            args.extend(["-metadata", f"{key}={value}"])

    args.append(output_file)
    return call_ffmpeg(*args)


async_merge_avfile = run_as_async_decorator()(merge_avfile)


def convert_audio(
    input_file: str,
    output_file: str,
    quality: Optional[str] = None,
    metadata: Optional[dict[str, str]] = None,
    cover_image: Optional[str] = None,
):
    """
    转换音频文件格式，且能添加元数据和封面图片
    元数据名称参见：https://kodi.wiki/view/Video_file_tagging#Supported_Tags

    :param input_file: 输入文件路径
    :param output_file: 输出文件路径
    :param metadata: 包含元数据的字典
    :param cover_image: 封面图片文件路径
    """
    args = ["-i", input_file]

    if cover_image:
        args.extend(["-i", cover_image])

    if cover_image:
        args.extend(["-map", "0", "-map", "1"])
    else:
        args.extend(["-map", "0"])

    if quality:
        args.extend(["-b:a", quality])

    if cover_image:
        args.extend(["-c:v", "mjpeg"])  # 封面图片一般为 JPEG 格式
        args.extend(["-disposition:v", "attached_pic"])  # 标记图片为封面

    if metadata:
        for key, value in metadata.items():
            args.extend(["-metadata", f"{key}={value}"])

    args.append(output_file)
    return call_ffmpeg(*args)


async_convert_audio = run_as_async_decorator()(convert_audio)
