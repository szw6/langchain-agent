"""
MCP Server 数据模型：订单、物流、退款规则。
"""
from dataclasses import dataclass, field
from enum import Enum


class OrderStatus(str, Enum):
    PENDING = "pending"          # 待付款
    PAID = "paid"                # 已付款
    SHIPPED = "shipped"          # 已发货
    IN_TRANSIT = "in_transit"    # 运输中
    DELIVERED = "delivered"      # 已签收
    COMPLETED = "completed"      # 已完成
    CANCELLED = "cancelled"      # 已取消
    REFUNDING = "refunding"      # 退款中
    REFUNDED = "refunded"        # 已退款


class LogisticsStatus(str, Enum):
    PENDING_PICKUP = "pending_pickup"      # 待取件
    PICKED_UP = "picked_up"                # 已取件
    IN_TRANSIT = "in_transit"              # 运输中
    OUT_FOR_DELIVERY = "out_for_delivery"  # 派送中
    DELIVERED = "delivered"                # 已签收
    EXCEPTION = "exception"                # 异常


class RefundEligibility(str, Enum):
    ELIGIBLE = "eligible"              # 可退款
    CONDITIONALLY = "conditionally"    # 有条件退款
    NOT_ELIGIBLE = "not_eligible"      # 不可退款


@dataclass
class Order:
    order_id: str
    user_id: str
    product_name: str
    product_model: str
    quantity: int
    amount: float
    status: OrderStatus
    created_at: str
    paid_at: str = ""
    address: str = ""


@dataclass
class LogisticsEvent:
    timestamp: str
    status: str
    location: str
    description: str


@dataclass
class LogisticsInfo:
    order_id: str
    carrier: str
    tracking_number: str
    status: LogisticsStatus
    shipped_at: str = ""
    events: list[LogisticsEvent] = field(default_factory=list)


@dataclass
class RefundRule:
    rule_id: str
    name: str
    description: str
    conditions: list[str]
    time_limit_days: int
    exceptions: list[str]
    requires_photos: bool = False


@dataclass
class RefundCheckResult:
    order_id: str
    reason: str
    eligible: RefundEligibility
    matched_rule: str
    time_limit_remaining: int
    message: str
    next_steps: list[str] = field(default_factory=list)


ORDER_STATUS_LABELS = {
    OrderStatus.PENDING: "待付款",
    OrderStatus.PAID: "已付款",
    OrderStatus.SHIPPED: "已发货",
    OrderStatus.IN_TRANSIT: "运输中",
    OrderStatus.DELIVERED: "已签收",
    OrderStatus.COMPLETED: "已完成",
    OrderStatus.CANCELLED: "已取消",
    OrderStatus.REFUNDING: "退款中",
    OrderStatus.REFUNDED: "已退款",
}

LOGISTICS_STATUS_LABELS = {
    LogisticsStatus.PENDING_PICKUP: "待取件",
    LogisticsStatus.PICKED_UP: "已取件",
    LogisticsStatus.IN_TRANSIT: "运输中",
    LogisticsStatus.OUT_FOR_DELIVERY: "派送中",
    LogisticsStatus.DELIVERED: "已签收",
    LogisticsStatus.EXCEPTION: "异常",
}

REFUND_ELIGIBILITY_LABELS = {
    RefundEligibility.ELIGIBLE: "可退款",
    RefundEligibility.CONDITIONALLY: "有条件退款",
    RefundEligibility.NOT_ELIGIBLE: "不可退款",
}
