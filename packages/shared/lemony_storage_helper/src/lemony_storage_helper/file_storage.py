"""
文件存储模块.

提供基于文件系统的数据存储功能, 用于存储非结构化数据如媒体文件等.
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any

import aiofiles
from melobot.log import get_logger

__all__ = [
    "FileStorageHelper",
    "FileInfo",
]

logger = get_logger()


class FileInfo:
    """文件信息类."""

    def __init__(
        self,
        file_id: str,
        path: Path,
        hash_value: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        初始化文件信息.

        Args:
            file_id: 文件唯一标识符.
            path: 文件路径.
            hash_value: 文件哈希值 (可选).
            metadata: 额外元数据 (可选).
        """
        self.file_id = file_id
        self.path = path
        self.hash_value = hash_value
        self.metadata = metadata or {}

    @property
    def exists(self) -> bool:
        """检查文件是否存在."""
        return self.path.exists()

    @property
    def size(self) -> int | None:
        """获取文件大小 (字节)."""
        if self.exists:
            return self.path.stat().st_size
        return None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "file_id": self.file_id,
            "path": str(self.path),
            "hash_value": self.hash_value,
            "metadata": self.metadata,
        }


class FileStorageHelper:
    """
    文件存储帮助类.

    提供基于文件系统的数据存储功能, 支持:
    - 文件保存和读取
    - 文件哈希计算
    - 文件索引管理

    用法示例:
        storage = FileStorageHelper(
            identifier="my_plugin",
            base_path="data",
        )

        # 保存文件
        file_info = await storage.save_file(b"content", extension=".txt")

        # 读取文件
        content = await storage.read_file(file_info.file_id)

        # 删除文件
        await storage.delete_file(file_info.file_id)
    """

    def __init__(
        self,
        identifier: str,
        base_path: str | Path = "data",
        *,
        use_hash_subdirs: bool = True,
        hash_subdir_depth: int = 2,
    ) -> None:
        """
        初始化文件存储帮助.

        Args:
            identifier: 唯一标识符.
            base_path: 基础存储路径.
            use_hash_subdirs: 是否使用哈希子目录组织文件.
            hash_subdir_depth: 哈希子目录深度 (默认为 2, 即 xx/yy/).
        """
        self._identifier = identifier
        self._base_path = Path(base_path).resolve() / identifier / "files"
        self._use_hash_subdirs = use_hash_subdirs
        self._hash_subdir_depth = hash_subdir_depth

        # 文件索引 (file_id -> FileInfo)
        self._file_index: dict[str, FileInfo] = {}

        # 确保目录存在
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def base_path(self) -> Path:
        return self._base_path

    def _generate_file_id(self) -> str:
        """生成唯一文件 ID."""
        return str(uuid.uuid4())

    def _compute_hash(self, data: bytes) -> str:
        """计算数据的 SHA256 哈希值."""
        return hashlib.sha256(data).hexdigest()

    def _get_file_path(self, file_id: str, extension: str = "") -> Path:
        """
        根据文件 ID 获取存储路径.

        Args:
            file_id: 文件 ID.
            extension: 文件扩展名.

        Returns:
            Path: 文件存储路径.
        """
        filename = f"{file_id}{extension}"

        if self._use_hash_subdirs:
            # 使用哈希值的前几位作为子目录
            hash_value = hashlib.md5(file_id.encode()).hexdigest()
            subdirs = "/".join(
                hash_value[i * 2 : (i + 1) * 2] for i in range(self._hash_subdir_depth)
            )
            return self._base_path / subdirs / filename

        return self._base_path / filename

    async def save_file(
        self,
        data: bytes,
        *,
        extension: str = "",
        file_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        compute_hash: bool = True,
    ) -> FileInfo:
        """
        保存文件.

        Args:
            data: 文件内容.
            extension: 文件扩展名 (如 ".txt", ".jpg").
            file_id: 指定的文件 ID (可选, 默认自动生成).
            metadata: 额外元数据.
            compute_hash: 是否计算哈希值.

        Returns:
            FileInfo: 文件信息.
        """
        if file_id is None:
            file_id = self._generate_file_id()

        hash_value = self._compute_hash(data) if compute_hash else None
        file_path = self._get_file_path(file_id, extension)

        # 确保目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 异步写入文件
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(data)

        file_info = FileInfo(
            file_id=file_id,
            path=file_path,
            hash_value=hash_value,
            metadata=metadata,
        )

        # 更新索引
        self._file_index[file_id] = file_info

        logger.debug(f"File saved: {file_id} -> {file_path}")
        return file_info

    async def save_from_path(
        self,
        source_path: str | Path,
        *,
        file_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        compute_hash: bool = True,
        copy: bool = True,
    ) -> FileInfo:
        """
        从路径保存文件.

        Args:
            source_path: 源文件路径.
            file_id: 指定的文件 ID (可选).
            metadata: 额外元数据.
            compute_hash: 是否计算哈希值.
            copy: 是否复制文件 (True) 或移动文件 (False).

        Returns:
            FileInfo: 文件信息.
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        async with aiofiles.open(source, "rb") as f:
            data = await f.read()

        extension = source.suffix
        file_info = await self.save_file(
            data,
            extension=extension,
            file_id=file_id,
            metadata=metadata,
            compute_hash=compute_hash,
        )

        # 如果是移动操作, 删除源文件
        if not copy:
            source.unlink()

        return file_info

    async def read_file(self, file_id: str) -> bytes | None:
        """
        读取文件内容.

        Args:
            file_id: 文件 ID.

        Returns:
            bytes | None: 文件内容, 如果文件不存在则返回 None.
        """
        file_info = self._file_index.get(file_id)
        if file_info is None:
            return None

        if not file_info.exists:
            return None

        async with aiofiles.open(file_info.path, "rb") as f:
            return await f.read()

    def get_file_info(self, file_id: str) -> FileInfo | None:
        """
        获取文件信息.

        Args:
            file_id: 文件 ID.

        Returns:
            FileInfo | None: 文件信息, 如果不存在则返回 None.
        """
        return self._file_index.get(file_id)

    def get_file_path(self, file_id: str) -> Path | None:
        """
        获取文件路径.

        Args:
            file_id: 文件 ID.

        Returns:
            Path | None: 文件路径, 如果不存在则返回 None.
        """
        file_info = self._file_index.get(file_id)
        if file_info is None:
            return None
        return file_info.path

    async def delete_file(self, file_id: str) -> bool:
        """
        删除文件.

        Args:
            file_id: 文件 ID.

        Returns:
            bool: 是否删除成功.
        """
        file_info = self._file_index.get(file_id)
        if file_info is None:
            return False

        if file_info.exists:
            file_info.path.unlink()

        del self._file_index[file_id]
        logger.debug(f"File deleted: {file_id}")
        return True

    def list_files(self) -> list[FileInfo]:
        """
        列出所有文件.

        Returns:
            list[FileInfo]: 文件信息列表.
        """
        return list(self._file_index.values())

    async def verify_file(self, file_id: str) -> bool:
        """
        验证文件完整性.

        通过比较存储的哈希值和当前文件的哈希值来验证.

        Args:
            file_id: 文件 ID.

        Returns:
            bool: 文件是否完整.
        """
        file_info = self._file_index.get(file_id)
        if file_info is None or file_info.hash_value is None:
            return False

        data = await self.read_file(file_id)
        if data is None:
            return False

        current_hash = self._compute_hash(data)
        return current_hash == file_info.hash_value

    def clear_index(self) -> None:
        """清空文件索引 (不删除实际文件)."""
        self._file_index.clear()

    async def scan_files(self, extension_filter: str | None = None) -> int:
        """
        扫描目录重建文件索引.

        Args:
            extension_filter: 扩展名过滤器 (可选).

        Returns:
            int: 扫描到的文件数量.
        """
        count = 0

        for file_path in self._base_path.rglob("*"):
            if not file_path.is_file():
                continue

            if extension_filter and not file_path.suffix == extension_filter:
                continue

            # 从文件名提取 file_id
            file_id = file_path.stem

            # 计算哈希
            async with aiofiles.open(file_path, "rb") as f:
                data = await f.read()
            hash_value = self._compute_hash(data)

            file_info = FileInfo(
                file_id=file_id,
                path=file_path,
                hash_value=hash_value,
            )
            self._file_index[file_id] = file_info
            count += 1

        logger.info(f"Scanned {count} files in {self._base_path}")
        return count
