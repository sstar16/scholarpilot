"""NotificationChannel ABC + payload / result dataclasses。

每个 channel 实现：
    class FeishuChannel(NotificationChannel):
        channel_id = "feishu"
        async def send(self, config: dict, payload: NotificationPayload) -> NotificationResult:
            ...
        @classmethod
        def validate_config(cls, raw_config: dict) -> dict:
            # 校验 + 加密敏感字段，返回最终落库的 dict
            ...
        @classmethod
        def public_view(cls, config: dict) -> dict:
            # 给前端看的脱敏视图（webhook URL 截断、send_key 隐藏等）
            ...

不抛异常约定：channel.send 必须捕获所有错误返回 NotificationResult，让 dispatcher 统计成功/失败。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Optional


@dataclass
class NotificationPayload:
    """各 channel 渲染的统一输入。"""

    title: str
    body: str  # markdown / plain text，channel 自己决定如何转
    links: list[tuple[str, str]] = field(default_factory=list)  # [(label, url), ...]
    category: str = "info"  # info / warning / error / success
    # 可选：channel 特化字段（如 telegram 的 inline keyboard markup）
    extras: dict = field(default_factory=dict)


@dataclass
class NotificationResult:
    """channel.send 返回值。"""

    channel: str
    ok: bool
    message: str = ""  # 成功/失败原因；失败时供 admin debug
    response_body: Optional[str] = None  # 截断后的对方响应（debug 用）


class NotificationChannel(ABC):
    """推送通道抽象基类。

    子类必须设置 channel_id（与 ALLOWED_CHANNELS / DB 一致），并实现 send / validate_config / public_view。
    """

    channel_id: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    # webhook 类（推到群 / 自己绑定的账号）vs 邮件类，前端 UI 不一样
    config_kind: ClassVar[str] = "webhook"  # 'webhook' | 'email' | 'telegram'

    @abstractmethod
    async def send(
        self,
        config: dict,
        payload: NotificationPayload,
    ) -> NotificationResult:
        """实际发送，必须捕获所有异常，绝不抛错。"""

    @classmethod
    @abstractmethod
    def validate_config(cls, raw_config: dict) -> dict:
        """校验客户端传来的 raw_config + 加密敏感字段。

        失败抛 ValueError。返回值最终落库（config_json 列）。
        """

    @classmethod
    @abstractmethod
    def public_view(cls, config: dict) -> dict:
        """脱敏视图（前端展示用）。webhook URL / send_key 等敏感字段截断。"""
