from typing import Unpack, TypedDict

from sqlmodel import select, col, and_, or_, Session

from recorder_models import Message


class RangeContextParams(TypedDict):
    base_msgid: int
    group_id: int
    sender_id: int
    edge_e: int = 0
    edge_l: int = 0
    sender_only: bool = False


def get_context_messages(
    session: Session, **context: Unpack[RangeContextParams]
) -> list[Message]:
    """
    ```
    Index
    -3 ↑ Earlier
    -2 |
    -1 |
    0  |-- base_msgid
    1  |
    2  |
    3  ↓ Later
    ```
    以 base_msgid 基准消息的索引为 0, 向时间更晚方向为正索引, 更早方向为负索引,
    取得 [edge_e, edge_l] 闭区间内的消息 (按时间戳递增排序)

    按照 message_id 可能不唯一的情况进行处理, 所以在获取基准消息时还需要再约束 sender_id
    真正唯一的列是消息录入时自动生成的 store_id, 类型为 uuid4
    """
    _ = (context["edge_e"], context["edge_l"])
    edge_e, edge_l = min(_), max(_)
    gid = context["group_id"]
    uid = context["sender_id"]
    mid = context["base_msgid"]
    extra_filters = [Message.sender_id == uid] if context["sender_only"] else []

    base_message = session.exec(
        select(Message)
        .where(
            Message.group_id == gid,
            Message.sender_id == uid,
            Message.message_id == mid,
        )
        .order_by(col(Message.timestamp).desc(), col(Message.message_id).desc())
    ).first()
    if not base_message:
        return []
    if edge_e == edge_l == 0:
        return [base_message]

    base_mid = base_message.message_id
    base_time = base_message.timestamp
    earliers = []
    laters = []
    if edge_e < 0:
        earliers = session.exec(
            select(Message)
            .where(
                Message.group_id == gid,
                or_(
                    Message.timestamp < base_time,
                    and_(
                        Message.timestamp == base_time,
                        Message.message_id < base_mid,
                    ),
                ),
                *extra_filters,
            )
            .distinct()
            .order_by(col(Message.timestamp).desc(), col(Message.message_id).desc())
            # 按时间倒序获取最新早消息, 在上报的时间戳重复时按局部随时间递增的 message_id 二次排序
            # 不同实现端的行为可能不太一样 但是没办法了 ()
            .limit(abs(edge_e))
        ).all()
    if edge_l > 0:
        laters = session.exec(
            select(Message)
            .where(
                Message.group_id == gid,
                or_(
                    Message.timestamp > base_time,
                    and_(
                        Message.timestamp == base_time,
                        Message.message_id > base_mid,
                    ),
                ),
                *extra_filters,
            )
            .distinct()
            .order_by(
                col(Message.timestamp).asc(), col(Message.message_id).asc()
            )  # 按时间正序获取
            .limit(edge_l)
        ).all()
    if edge_e > 0:
        return laters[edge_e - 1 :] if edge_e <= len(laters) else []
    elif edge_l < 0:
        return earliers[abs(edge_l) - 1 :][::-1] if abs(edge_l) <= len(earliers) else []
    else:
        return earliers[::-1] + [base_message] + laters
