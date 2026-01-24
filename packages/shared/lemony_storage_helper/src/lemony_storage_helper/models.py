"""
数据模型基类模块.

提供 SQLModel 表定义的基类和泛型 AsyncAttrs 类型.
"""

from typing import TYPE_CHECKING, Generic, TypeVar

from sqlalchemy.ext.asyncio.session import AsyncAttrs as _AsyncAttrs
from sqlmodel import SQLModel

__all__ = [
    "GenericAsyncAttrs",
    "LemonyStorageBase",
]

T = TypeVar("T")


class GenericAsyncAttrs(_AsyncAttrs, Generic[T]):
    """
    泛型 AsyncAttrs 类, 用于为关系字段提供类型标注.

    用法示例:
        class _UserAwaitableAttrs:
            groups: Awaitable[list["Group"]]

        class User(Base, GenericAsyncAttrs[_UserAwaitableAttrs], table=True):
            ...
    """

    if TYPE_CHECKING:
        awaitable_attrs: T  # type: ignore


class LemonyStorageBase(SQLModel):
    """
    所有表模型的基类.

    继承此类时需要指定 metadata 和 registry 参数,
    以便将表定义注册到指定的 metadata 中.

    用法示例:
        from sqlalchemy.orm import registry

        my_registry = registry()
        my_metadata = my_registry.metadata

        class MyTable(LemonyStorageBase, registry=my_registry, metadata=my_metadata, table=True):
            ...
    """

    pass
