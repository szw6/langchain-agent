"""
MCP 工具的 LangChain 包装器：将 MCP Server 工具包装为 @tool 函数，
返回 ToolResult 以复用现有中间件。
"""
from dataclasses import asdict
from datetime import datetime

from langchain_core.tools import tool

from agent.tools.tool_schema import ToolResult, ToolStatus
from mcp_server.data_store import get_order, get_logistics, load_refund_rules
from mcp_server.models import (
    OrderStatus, RefundEligibility,
    ORDER_STATUS_LABELS, LOGISTICS_STATUS_LABELS,
)


@tool(description="查询订单详情，返回订单状态、商品信息、金额等。order_id: 订单编号（如ORD20250101001）。")
def query_order(order_id: str):
    """查询订单详情工具。"""
    order = get_order(order_id)
    if not order:
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到订单 {order_id}，请确认订单编号是否正确。",
            evidence={"order_id": order_id},
            next_step="请用户提供正确的订单编号",
        ))

    status_label = ORDER_STATUS_LABELS.get(order.status, order.status.value)
    message = (
        f"订单编号：{order.order_id}\n"
        f"用户ID：{order.user_id}\n"
        f"商品：{order.product_name}（{order.product_model}）\n"
        f"数量：{order.quantity}\n"
        f"金额：¥{order.amount:.2f}\n"
        f"状态：{status_label}\n"
        f"下单时间：{order.created_at}\n"
        f"付款时间：{order.paid_at or '未付款'}\n"
        f"收货地址：{order.address}"
    )
    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message=message,
        evidence={"order_id": order_id, "status": order.status.value, "amount": order.amount},
    ))


@tool(description="查询物流信息，返回承运商、运单号、物流状态和运输轨迹。order_id: 订单编号。")
def query_logistics(order_id: str):
    """查询物流信息工具。"""
    info = get_logistics(order_id)
    if not info:
        order = get_order(order_id)
        if not order:
            return asdict(ToolResult(
                status=ToolStatus.NOT_FOUND,
                message=f"未找到订单 {order_id} 的物流信息，请确认订单编号。",
                evidence={"order_id": order_id},
                next_step="请用户提供正确的订单编号",
            ))
        return asdict(ToolResult(
            status=ToolStatus.NO_DATA,
            message=f"订单 {order_id} 暂无物流信息，可能尚未发货。",
            evidence={"order_id": order_id},
            next_step="请稍后查询或联系客服",
        ))

    status_label = LOGISTICS_STATUS_LABELS.get(info.status, info.status.value)
    lines = [
        f"订单编号：{info.order_id}",
        f"承运商：{info.carrier}",
        f"运单号：{info.tracking_number}",
        f"物流状态：{status_label}",
        f"发货时间：{info.shipped_at or '未发货'}",
    ]
    if info.events:
        lines.append("运输轨迹：")
        for evt in info.events:
            lines.append(f"  [{evt.timestamp}] {evt.location} - {evt.description}")

    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message="\n".join(lines),
        evidence={
            "order_id": info.order_id,
            "carrier": info.carrier,
            "tracking_number": info.tracking_number,
            "status": info.status.value,
            "event_count": len(info.events),
        },
    ))


@tool(description="检查退款规则，判断是否符合退款条件。order_id: 订单编号; reason: 退款原因（如：质量问题、不想要了、发错货、商品损坏等）。")
def check_refund_rules(order_id: str, reason: str):
    """退款规则检查工具。"""
    order = get_order(order_id)
    if not order:
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到订单 {order_id}，请确认订单编号是否正确。",
            evidence={"order_id": order_id},
            next_step="请用户提供正确的订单编号",
        ))

    info = get_logistics(order_id)
    rules = load_refund_rules()

    # 确定签收时间
    delivered_at = None
    if info and info.events:
        for evt in info.events:
            if evt.status == "delivered":
                delivered_at = datetime.fromisoformat(evt.timestamp)
                break

    now = datetime.now()
    days_since_delivery = -1
    if delivered_at:
        days_since_delivery = (now - delivered_at).days

    # 匹配退款规则
    reason_lower = reason.lower()
    quality_keywords = ["质量", "故障", "坏了", "损坏", "不能用", "不好用", "异常", "bug"]
    is_quality_issue = any(kw in reason_lower for kw in quality_keywords)

    matched_rule = None
    eligibility = RefundEligibility.NOT_ELIGIBLE
    time_limit_remaining = -1

    for rule in rules:
        if rule.rule_id == "R001" and days_since_delivery >= 0:
            remaining = rule.time_limit_days - days_since_delivery
            if remaining > 0:
                if "耗材" in order.product_name or "定制" in order.product_name:
                    continue
                matched_rule = rule
                eligibility = RefundEligibility.ELIGIBLE
                time_limit_remaining = remaining
                break

        if rule.rule_id in ("R002", "R003") and is_quality_issue and days_since_delivery >= 0:
            remaining = rule.time_limit_days - days_since_delivery
            if remaining > 0:
                matched_rule = rule
                eligibility = RefundEligibility.ELIGIBLE
                time_limit_remaining = remaining
                break

        if rule.rule_id == "R004" and is_quality_issue:
            created_at = datetime.fromisoformat(order.created_at)
            days_since_purchase = (now - created_at).days
            remaining = rule.time_limit_days - days_since_purchase
            if remaining > 0 and not matched_rule:
                matched_rule = rule
                eligibility = RefundEligibility.CONDITIONALLY
                time_limit_remaining = remaining

    if not matched_rule:
        status_label = ORDER_STATUS_LABELS.get(order.status, order.status.value)
        return asdict(ToolResult(
            status=ToolStatus.SUCCESS,
            message=f"很抱歉，您的订单不满足退款条件。当前订单状态：{status_label}。",
            evidence={
                "order_id": order_id,
                "status": order.status.value,
                "reason": reason,
                "eligible": False,
            },
            next_step="如有疑问请联系人工客服",
        ))

    elig_label = {
        RefundEligibility.ELIGIBLE: "可退款",
        RefundEligibility.CONDITIONALLY: "有条件退款",
        RefundEligibility.NOT_ELIGIBLE: "不可退款",
    }.get(eligibility, "未知")

    message = (
        f"根据「{matched_rule.name}」规则，您的订单满足退款条件。\n"
        f"退款资格：{elig_label}\n"
        f"剩余有效期：{time_limit_remaining}天\n"
        f"规则说明：{matched_rule.description}"
    )

    next_steps = []
    if eligibility == RefundEligibility.ELIGIBLE:
        next_steps = ["可立即申请退款", "请在退款页面提交申请"]
        if matched_rule.requires_photos:
            next_steps.insert(0, "请准备好商品照片作为凭证")
    elif eligibility == RefundEligibility.CONDITIONALLY:
        next_steps = ["请联系客服确认退款条件", "请准备好商品照片和故障说明"]

    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message=message,
        evidence={
            "order_id": order_id,
            "reason": reason,
            "eligible": eligibility.value,
            "matched_rule": matched_rule.rule_id,
            "time_limit_remaining": time_limit_remaining,
        },
        next_step="；".join(next_steps) if next_steps else "",
    ))
