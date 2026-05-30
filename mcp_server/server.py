"""
订单客服 MCP Server：提供订单查询、物流查询、退款规则检查工具，
以及订单状态和退款规则 Resources。
"""
import json
from datetime import datetime, timedelta

from fastmcp import FastMCP

from mcp_server.data_store import get_order, get_logistics, load_refund_rules, get_refund_rules_text
from mcp_server.models import (
    OrderStatus, LogisticsStatus, RefundEligibility,
    ORDER_STATUS_LABELS, LOGISTICS_STATUS_LABELS,
)
from utils.config_handler import mcp_conf

mcp = FastMCP(mcp_conf.get("name", "order-customer-service"))


# ────────────────────── Tools ──────────────────────


@mcp.tool()
def query_order(order_id: str) -> str:
    """查询订单详情，返回订单状态、商品信息、金额等。
    order_id: 订单编号（如ORD20250101001）。"""
    order = get_order(order_id)
    if not order:
        return json.dumps({
            "status": "not_found",
            "message": f"未找到订单 {order_id}，请确认订单编号是否正确。",
        }, ensure_ascii=False)

    status_label = ORDER_STATUS_LABELS.get(order.status, order.status.value)
    result = {
        "status": "success",
        "order_id": order.order_id,
        "user_id": order.user_id,
        "product_name": order.product_name,
        "product_model": order.product_model,
        "quantity": order.quantity,
        "amount": order.amount,
        "order_status": status_label,
        "created_at": order.created_at,
        "paid_at": order.paid_at or "未付款",
        "address": order.address,
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def query_logistics(order_id: str) -> str:
    """查询物流信息，返回承运商、运单号、物流状态和运输轨迹。
    order_id: 订单编号。"""
    info = get_logistics(order_id)
    if not info:
        return json.dumps({
            "status": "not_found",
            "message": f"未找到订单 {order_id} 的物流信息。",
        }, ensure_ascii=False)

    status_label = LOGISTICS_STATUS_LABELS.get(info.status, info.status.value)
    events = [
        {
            "timestamp": evt.timestamp,
            "status": evt.status,
            "location": evt.location,
            "description": evt.description,
        }
        for evt in info.events
    ]
    result = {
        "status": "success",
        "order_id": info.order_id,
        "carrier": info.carrier,
        "tracking_number": info.tracking_number,
        "logistics_status": status_label,
        "shipped_at": info.shipped_at or "未发货",
        "events": events,
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def check_refund_rules(order_id: str, reason: str) -> str:
    """检查退款规则，判断是否符合退款条件。
    order_id: 订单编号; reason: 退款原因（如：质量问题、不想要了、发错货、商品损坏等）。"""
    order = get_order(order_id)
    if not order:
        return json.dumps({
            "status": "not_found",
            "message": f"未找到订单 {order_id}，请确认订单编号是否正确。",
        }, ensure_ascii=False)

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
        # 7天无理由退货：签收7天以内即可
        if rule.rule_id == "R001" and days_since_delivery >= 0:
            remaining = rule.time_limit_days - days_since_delivery
            if remaining > 0:
                # 检查例外情况
                if "耗材" in order.product_name or "定制" in order.product_name:
                    continue
                matched_rule = rule
                eligibility = RefundEligibility.ELIGIBLE
                time_limit_remaining = remaining
                break

        # 质量问题规则
        if rule.rule_id in ("R002", "R003") and is_quality_issue and days_since_delivery >= 0:
            remaining = rule.time_limit_days - days_since_delivery
            if remaining > 0:
                matched_rule = rule
                eligibility = RefundEligibility.ELIGIBLE
                time_limit_remaining = remaining
                break

        # 保修期规则
        if rule.rule_id == "R004" and is_quality_issue:
            # 以订单创建时间计算保修期
            created_at = datetime.fromisoformat(order.created_at)
            days_since_purchase = (now - created_at).days
            remaining = rule.time_limit_days - days_since_purchase
            if remaining > 0 and not matched_rule:
                matched_rule = rule
                eligibility = RefundEligibility.CONDITIONALLY
                time_limit_remaining = remaining

    # 构建结果
    if not matched_rule:
        status_label = ORDER_STATUS_LABELS.get(order.status, order.status.value)
        return json.dumps({
            "status": "success",
            "order_id": order_id,
            "order_status": status_label,
            "eligible": "不可退款",
            "reason": reason,
            "message": f"很抱歉，您的订单不满足退款条件。当前订单状态：{status_label}。",
            "next_steps": ["如有疑问请联系人工客服"],
        }, ensure_ascii=False)

    elig_label = {
        RefundEligibility.ELIGIBLE: "可退款",
        RefundEligibility.CONDITIONALLY: "有条件退款",
        RefundEligibility.NOT_ELIGIBLE: "不可退款",
    }.get(eligibility, "未知")

    next_steps = []
    if eligibility == RefundEligibility.ELIGIBLE:
        next_steps = ["可立即申请退款", "请在退款页面提交申请"]
        if matched_rule.requires_photos:
            next_steps.insert(0, "请准备好商品照片作为凭证")
    elif eligibility == RefundEligibility.CONDITIONALLY:
        next_steps = ["请联系客服确认退款条件", "请准备好商品照片和故障说明"]

    return json.dumps({
        "status": "success",
        "order_id": order_id,
        "eligible": elig_label,
        "matched_rule": matched_rule.name,
        "reason": reason,
        "time_limit_remaining_days": time_limit_remaining,
        "message": f"根据「{matched_rule.name}」规则，您的订单满足退款条件，剩余{time_limit_remaining}天有效期。",
        "next_steps": next_steps,
    }, ensure_ascii=False)


# ────────────────────── Resources ──────────────────────


@mcp.resource("order_status://{order_id}")
def get_order_status(order_id: str) -> str:
    """获取订单状态文档。"""
    order = get_order(order_id)
    if not order:
        return f"未找到订单 {order_id}。"

    status_label = ORDER_STATUS_LABELS.get(order.status, order.status.value)
    lines = [
        f"订单状态报告",
        f"=" * 40,
        f"订单编号：{order.order_id}",
        f"用户ID：{order.user_id}",
        f"商品名称：{order.product_name}",
        f"商品型号：{order.product_model}",
        f"数量：{order.quantity}",
        f"订单金额：¥{order.amount:.2f}",
        f"订单状态：{status_label}",
        f"下单时间：{order.created_at}",
        f"付款时间：{order.paid_at or '未付款'}",
        f"收货地址：{order.address}",
    ]

    info = get_logistics(order_id)
    if info:
        logistics_label = LOGISTICS_STATUS_LABELS.get(info.status, info.status.value)
        lines.extend([
            f"",
            f"物流信息",
            f"-" * 40,
            f"承运商：{info.carrier}",
            f"运单号：{info.tracking_number}",
            f"物流状态：{logistics_label}",
            f"发货时间：{info.shipped_at or '未发货'}",
        ])
        if info.events:
            lines.append(f"运输轨迹：")
            for evt in info.events:
                lines.append(f"  [{evt.timestamp}] {evt.location} - {evt.description}")

    return "\n".join(lines)


@mcp.resource("refund_rules://policy")
def get_refund_policy() -> str:
    """获取退款政策规则文档。"""
    return get_refund_rules_text()


if __name__ == "__main__":
    transport = mcp_conf.get("transport", "stdio")
    if transport == "sse":
        host = mcp_conf.get("sse_host", "0.0.0.0")
        port = mcp_conf.get("sse_port", 8765)
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run(transport="stdio")
