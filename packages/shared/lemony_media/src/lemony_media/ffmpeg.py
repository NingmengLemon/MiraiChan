"""ffmpeg 的轻量封装: 错误带 stderr, 调用方可设超时."""

import logging
import subprocess

logger = logging.getLogger(__name__)


def call_ffmpeg(
    *args: str,
    check: bool = True,
    timeout: float | None = None,
) -> int:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-nostdin", "-hide_banner"]
    cmd.extend(args)
    process = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if process.returncode != 0:
        logger.error(
            "ffmpeg 失败 (exit=%s): %s", process.returncode, process.stderr[-4000:]
        )
        if check:
            raise subprocess.CalledProcessError(
                process.returncode, cmd, process.stdout, process.stderr
            )
    return process.returncode


def merge_avfile(
    au_file: str | None,
    vi_file: str,
    output_file: str,
    cover_image: str | None = None,
    metadata: dict[str, str] | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> int:
    """调用ffmpeg进行合流，并能添加元数据"""
    args = ["-i", vi_file]
    if au_file:
        args.extend(["-i", au_file])
    if cover_image:
        args.extend(["-i", cover_image])

    if au_file and cover_image:
        args.extend(["-map", "0", "-map", "1", "-map", "2"])
    elif au_file or cover_image:
        args.extend(["-map", "0", "-map", "1"])
    else:
        args.extend(["-map", "0"])

    args.extend(["-c", "copy"])

    if metadata:
        for key, value in metadata.items():
            args.extend(["-metadata", f"{key}={value}"])

    args.append(output_file)
    return call_ffmpeg(*args, check=check, timeout=timeout)


def convert_audio(
    input_file: str,
    output_file: str,
    quality: str | None = None,
    metadata: dict[str, str] | None = None,
    cover_image: str | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> int:
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
    return call_ffmpeg(*args, check=check, timeout=timeout)
