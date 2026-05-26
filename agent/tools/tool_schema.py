"""
工具公共数据模型：枚举定义 + 统一返回结构。

所有工具返回 ToolResult，经 dataclasses.asdict() 序列化为 dict 后交给 LangChain。
"""
from dataclasses import dataclass, field
from enum import Enum


class ToolStatus(str, Enum):
    """工具执行状态"""
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    DEGRADED = "degraded"
    ERROR = "error"
    NO_DATA = "no_data"


class QueryType(str, Enum):
    """知识库查询类型"""
    FAULT = "fault"
    MAINTENANCE = "maintenance"
    PURCHASE = "purchase"
    USAGE = "usage"
    GENERAL = "general"


class DataCategory(str, Enum):
    """用户数据类别"""
    FEATURE = "feature"
    EFFICIENCY = "efficiency"
    CONSUMABLE = "consumable"
    COMPARISON = "comparison"
    ALL = "all"


class TimeRange(str, Enum):
    """时间范围预设"""
    LATEST = "latest"
    LAST_3_MONTHS = "last_3"
    LAST_6_MONTHS = "last_6"
    ALL = "all"


@dataclass
class ToolResult:
    """工具统一返回结构"""
    status: ToolStatus
    message: str
    evidence: dict = field(default_factory=dict)
    next_step: str = ""
