"""
业务工具定义：所有工具返回 ToolResult（经 asdict 序列化为 dict）。
"""
import json
import os.path
import re
import csv
from dataclasses import asdict
from datetime import datetime
from typing import Dict
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from langchain_core.tools import tool
from rag.rag_service import RagSummarizeService
from utils.config_handler import agent_conf
from utils.path_tool import get_abs_path
from utils.logger_handler import logger
from agent.tools.tool_schema import (
    ToolResult, ToolStatus, QueryType, DataCategory, TimeRange,
)

rag = RagSummarizeService()
external_data: Dict[str, Dict[str, dict]] = {}

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_MONTHS_HARD_LIMIT = 12


def _request_json(base_url: str, params: dict) -> dict:
    """发起一个简单的 GET 请求并解析 JSON。"""
    url = f"{base_url}?{urlencode(params)}"
    with urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _format_record(user_id: str, month: str, record: dict) -> str:
    """把结构化用户记录转成更适合模型消费的纯文本。"""
    parts = [f"用户ID: {user_id}", f"月份: {month}"]
    for key in ("特征", "效率", "耗材", "对比"):
        value = (record.get(key) or "").strip()
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _filter_record(record: dict, category: DataCategory) -> dict:
    """按类别过滤单条记录。"""
    if category == DataCategory.ALL:
        return record
    category_map = {
        DataCategory.FEATURE: "特征",
        DataCategory.EFFICIENCY: "效率",
        DataCategory.CONSUMABLE: "耗材",
        DataCategory.COMPARISON: "对比",
    }
    key = category_map.get(category)
    if key and record.get(key):
        return {key: record[key]}
    return {}


def _validate_month(month: str) -> bool:
    """校验月份格式 YYYY-MM。"""
    return bool(MONTH_PATTERN.match(month.strip()))


def generate_external_data():
    """懒加载外部用户记录，只在首次需要时读取 CSV。"""
    if external_data:
        return
    external_data_path = get_abs_path(agent_conf["external_data_path"])
    if not os.path.exists(external_data_path):
        raise FileNotFoundError(f"外部数据文件{external_data_path}不存在")

    with open(external_data_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_id = (row.get("用户ID") or "").strip()
            month = (row.get("时间") or "").strip()
            if not user_id or not month:
                continue

            if user_id not in external_data:
                external_data[user_id] = {}

            external_data[user_id][month] = {
                "特征": (row.get("特征") or "").strip(),
                "效率": (row.get("清洁效率") or "").strip(),
                "耗材": (row.get("耗材") or "").strip(),
                "对比": (row.get("对比") or "").strip(),
            }


# ────────────────────── 工具函数 ──────────────────────


@tool(description="从本地知识库中检索与扫地机器人相关的参考资料并总结返回。query_type: fault(故障排查), maintenance(维护保养), purchase(选购建议), usage(使用技巧), general(通用咨询)。")
def rag_summarize(query: str, query_type: QueryType = QueryType.GENERAL):
    """知识库问答工具，代理到 RAG 服务并包装为 ToolResult。"""
    result = rag.rag_summarize(query, query_type=query_type.value)
    return asdict(ToolResult(
        status=ToolStatus(result["status"]),
        message=result["message"],
        evidence=result.get("evidence", {}),
        next_step=result.get("next_step", ""),
    ))


@tool(description="获取指定城市的实时天气信息，返回温度、体感温度、降水、风速等数据。")
def get_weather(city: str):
    """实时天气工具，先地理编码，再查询当前天气。"""
    city = city.strip()
    if not city:
        return asdict(ToolResult(
            status=ToolStatus.ERROR,
            message="城市名称不能为空。",
            next_step="请提供有效的城市名称",
        ))

    try:
        geocode_data = _request_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": city, "count": 1, "language": "zh", "format": "json"},
        )
        results = geocode_data.get("results") or []
        if not results:
            return asdict(ToolResult(
                status=ToolStatus.NOT_FOUND,
                message=f"未查询到城市 {city} 的地理信息，请确认城市名称。",
                evidence={"city": city},
                next_step="请确认城市名称是否正确",
            ))

        location = results[0]
        latitude = location["latitude"]
        longitude = location["longitude"]
        resolved_name = location.get("name", city)
        admin1 = location.get("admin1", "")
        country = location.get("country", "")

        weather_data = _request_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join([
                    "temperature_2m",
                    "apparent_temperature",
                    "relative_humidity_2m",
                    "precipitation",
                    "wind_speed_10m",
                    "weather_code",
                ]),
                "timezone": "auto",
            },
        )
        current = weather_data.get("current") or {}
        if not current:
            return asdict(ToolResult(
                status=ToolStatus.NO_DATA,
                message=f"已定位到 {resolved_name}，但未获取到实时天气数据。",
                evidence={"city": resolved_name, "latitude": latitude, "longitude": longitude},
                next_step="稍后重试天气查询",
            ))

        weather_code_map = {
            0: "晴", 1: "大部晴朗", 2: "局部多云", 3: "阴",
            45: "雾", 48: "冻雾",
            51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨",
            61: "小雨", 63: "中雨", 65: "大雨",
            71: "小雪", 73: "中雪", 75: "大雪",
            80: "阵雨", 81: "较强阵雨", 82: "强阵雨",
            95: "雷暴",
        }
        weather_text = weather_code_map.get(current.get("weather_code"), "未知天气")
        location_text = ", ".join(filter(None, [resolved_name, admin1, country]))

        weather_info = {
            "location": location_text,
            "weather": weather_text,
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind_speed": current.get("wind_speed_10m"),
        }

        message = (
            f"{location_text} 当前天气：{weather_text}；"
            f"温度 {current.get('temperature_2m')}°C，"
            f"体感 {current.get('apparent_temperature')}°C，"
            f"相对湿度 {current.get('relative_humidity_2m')}%，"
            f"降水 {current.get('precipitation')} mm，"
            f"风速 {current.get('wind_speed_10m')} km/h。"
        )

        return asdict(ToolResult(
            status=ToolStatus.SUCCESS,
            message=message,
            evidence=weather_info,
        ))

    except URLError as e:
        logger.warning(f"天气查询失败: {str(e)}")
        return asdict(ToolResult(
            status=ToolStatus.ERROR,
            message=f"天气服务当前不可用，无法获取 {city} 的实时天气。",
            evidence={"error": str(e)},
            next_step="稍后重试",
        ))
    except Exception as e:
        logger.error(f"天气查询异常: {str(e)}", exc_info=True)
        return asdict(ToolResult(
            status=ToolStatus.ERROR,
            message=f"获取 {city} 天气时发生异常。",
            evidence={"error": str(e)},
            next_step="稍后重试或联系技术支持",
        ))


@tool(description="获取当前会话绑定的城市名称。未绑定时明确返回未知，不允许编造。")
def get_user_location():
    """从环境变量中读取当前会话绑定城市。"""
    city = os.getenv("AGENT_USER_CITY", "").strip()
    if city:
        return asdict(ToolResult(
            status=ToolStatus.SUCCESS,
            message=city,
            evidence={"city": city},
        ))
    return asdict(ToolResult(
        status=ToolStatus.NO_DATA,
        message="当前会话未绑定城市信息，请让用户明确提供所在城市。",
        next_step="请用户提供所在城市",
    ))


@tool(description="获取当前会话绑定的用户ID。未绑定时明确返回未知，不允许随机生成。")
def get_user_id():
    """从环境变量中读取当前会话绑定的用户 ID。"""
    generate_external_data()
    user_id = os.getenv("AGENT_USER_ID", "").strip()
    if user_id and user_id in external_data:
        return asdict(ToolResult(
            status=ToolStatus.SUCCESS,
            message=user_id,
            evidence={"user_id": user_id},
        ))
    return asdict(ToolResult(
        status=ToolStatus.NO_DATA,
        message="当前会话未绑定用户ID，请让用户明确提供用户ID。",
        next_step="请用户提供用户ID",
    ))


@tool(description="获取当前月份，格式为 YYYY-MM。")
def get_current_month():
    """返回当前月份，给报告类工具补默认时间参数。"""
    month = datetime.now().strftime("%Y-%m")
    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message=month,
        evidence={"current_month": month},
    ))


@tool(description="列出指定用户有哪些可查询的报告月份。")
def list_report_months(user_id: str):
    """返回某个用户有哪些可查询的月份。"""
    generate_external_data()
    months = sorted(external_data.get(user_id, {}).keys())
    if not months:
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到用户 {user_id} 的可用报告月份。",
            evidence={"user_id": user_id},
            next_step="请确认用户ID是否正确",
        ))
    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message=f"用户 {user_id} 可查询月份：{', '.join(months)}",
        evidence={"user_id": user_id, "months": months, "count": len(months)},
    ))


@tool(description="获取指定用户最近一个月的使用记录。data_category: feature(特征), efficiency(效率), consumable(耗材), comparison(对比), all(全部)。")
def fetch_latest_external_data(user_id: str, data_category: DataCategory = DataCategory.ALL):
    """返回某个用户最新一期记录。"""
    generate_external_data()
    if user_id not in external_data:
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到用户 {user_id} 的使用数据。",
            evidence={"user_id": user_id},
            next_step="请确认用户ID是否正确",
        ))

    latest_month = sorted(external_data[user_id].keys())[-1]
    raw_record = external_data[user_id][latest_month]
    filtered = _filter_record(raw_record, data_category)

    if not filtered:
        return asdict(ToolResult(
            status=ToolStatus.NO_DATA,
            message=f"用户 {user_id} 在 {latest_month} 无 {data_category.value} 类别数据。",
            evidence={"user_id": user_id, "month": latest_month, "category": data_category.value},
            next_step="尝试查询其他数据类别或使用 all 类别",
        ))

    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message=_format_record(user_id, latest_month, filtered),
        evidence={
            "user_id": user_id,
            "month": latest_month,
            "category": data_category.value,
            "record": filtered,
        },
    ))


@tool(description="获取指定用户的基础画像和最近记录摘要。")
def get_user_profile(user_id: str):
    """返回用户画像和最近记录摘要，适合做报告前的概览。"""
    generate_external_data()
    user_records = external_data.get(user_id)
    if not user_records:
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到用户 {user_id} 的画像信息。",
            evidence={"user_id": user_id},
            next_step="请确认用户ID是否正确",
        ))

    months = sorted(user_records.keys())
    latest_month = months[-1]
    latest_record = user_records[latest_month]
    feature = latest_record.get("特征") or "未知"

    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message=(
            f"用户 {user_id} 的基础画像：{feature}。\n"
            f"可查询月份：{', '.join(months)}。\n"
            f"最近一期记录摘要：\n{_format_record(user_id, latest_month, latest_record)}"
        ),
        evidence={
            "user_id": user_id,
            "feature": feature,
            "available_months": months,
            "latest_month": latest_month,
        },
    ))


@tool(description="获取指定用户在指定月份的使用记录（严格查询，不存在则返回未找到）。month 格式必须为 YYYY-MM。")
def fetch_external_data(user_id: str, month: str):
    """严格查询指定月份记录，不做降级。"""
    generate_external_data()

    if not _validate_month(month):
        return asdict(ToolResult(
            status=ToolStatus.ERROR,
            message=f"月份格式无效：{month}，正确格式为 YYYY-MM（如 2024-03）。",
            evidence={"user_id": user_id, "month": month},
            next_step="请使用 YYYY-MM 格式的月份",
        ))

    if user_id not in external_data:
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到用户 {user_id} 的使用数据。",
            evidence={"user_id": user_id},
            next_step="请确认用户ID是否正确",
        ))

    user_records = external_data[user_id]
    if month not in user_records:
        available = sorted(user_records.keys())
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到用户 {user_id} 在 {month} 的数据。",
            evidence={
                "user_id": user_id,
                "month": month,
                "available_months": available,
            },
            next_step=f"可查询月份：{', '.join(available)}。可使用 fetch_external_data_range 查询时间范围。",
        ))

    record = user_records[month]
    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message=_format_record(user_id, month, record),
        evidence={"user_id": user_id, "month": month, "record": record},
    ))


@tool(description="按时间范围查询用户使用记录。time_range: latest(最近一期), last_3(最近3个月), last_6(最近6个月), all(全部)。也可用 start_month/end_month 自定义区间（格式 YYYY-MM），此时 time_range 会被忽略。data_category 过滤类别。max_months 限制最大返回月数（上限12）。")
def fetch_external_data_range(
    user_id: str,
    time_range: TimeRange = TimeRange.LATEST,
    start_month: str = "",
    end_month: str = "",
    data_category: DataCategory = DataCategory.ALL,
    max_months: int = 6,
):
    """按时间范围查询用户使用记录，支持类别过滤。"""
    generate_external_data()

    if max_months < 1:
        max_months = 1
    if max_months > MAX_MONTHS_HARD_LIMIT:
        max_months = MAX_MONTHS_HARD_LIMIT

    if user_id not in external_data:
        return asdict(ToolResult(
            status=ToolStatus.NOT_FOUND,
            message=f"未找到用户 {user_id} 的使用数据。",
            evidence={"user_id": user_id},
            next_step="请确认用户ID是否正确",
        ))

    user_records = external_data[user_id]
    all_months = sorted(user_records.keys())

    # 确定要查询的月份范围
    if start_month and end_month:
        # 自定义区间模式
        if not _validate_month(start_month):
            return asdict(ToolResult(
                status=ToolStatus.ERROR,
                message=f"start_month 格式无效：{start_month}，正确格式为 YYYY-MM。",
                evidence={"user_id": user_id, "start_month": start_month},
                next_step="请使用 YYYY-MM 格式的月份",
            ))
        if not _validate_month(end_month):
            return asdict(ToolResult(
                status=ToolStatus.ERROR,
                message=f"end_month 格式无效：{end_month}，正确格式为 YYYY-MM。",
                evidence={"user_id": user_id, "end_month": end_month},
                next_step="请使用 YYYY-MM 格式的月份",
            ))
        if start_month > end_month:
            return asdict(ToolResult(
                status=ToolStatus.ERROR,
                message="起始月份不能晚于结束月份。",
                evidence={"user_id": user_id, "start_month": start_month, "end_month": end_month},
                next_step="请调整起始和结束月份",
            ))
        target_months = [m for m in all_months if start_month <= m <= end_month]
    else:
        # 预设范围模式
        if time_range == TimeRange.LATEST:
            target_months = all_months[-1:] if all_months else []
        elif time_range == TimeRange.LAST_3_MONTHS:
            target_months = all_months[-3:]
        elif time_range == TimeRange.LAST_6_MONTHS:
            target_months = all_months[-6:]
        else:  # TimeRange.ALL
            target_months = all_months

    # 截断到 max_months
    if len(target_months) > max_months:
        target_months = target_months[-max_months:]

    if not target_months:
        return asdict(ToolResult(
            status=ToolStatus.NO_DATA,
            message=f"未找到用户 {user_id} 在指定时间范围内的数据。",
            evidence={
                "user_id": user_id,
                "time_range": time_range.value,
                "available_months": all_months,
            },
            next_step="可尝试扩大时间范围或确认用户ID",
        ))

    # 构建结果
    records = {}
    for m in target_months:
        raw = user_records[m]
        filtered = _filter_record(raw, data_category)
        if filtered:
            records[m] = filtered

    if not records:
        return asdict(ToolResult(
            status=ToolStatus.NO_DATA,
            message=f"用户 {user_id} 在指定时间范围内无 {data_category.value} 类别数据。",
            evidence={
                "user_id": user_id,
                "months_queried": target_months,
                "category": data_category.value,
            },
            next_step="尝试使用 all 类别查询",
        ))

    # 格式化输出
    parts = [f"用户ID: {user_id}", f"查询范围: {target_months[0]} ~ {target_months[-1]}（共{len(records)}个月）"]
    for m in sorted(records.keys()):
        parts.append(f"\n--- {m} ---")
        for key, value in records[m].items():
            if value:
                parts.append(f"{key}: {value}")

    return asdict(ToolResult(
        status=ToolStatus.SUCCESS if len(records) == len(target_months) else ToolStatus.DEGRADED,
        message="\n".join(parts),
        evidence={
            "user_id": user_id,
            "months_returned": sorted(records.keys()),
            "months_total": len(target_months),
            "category": data_category.value,
            "records": records,
        },
        next_step="" if len(records) == len(target_months) else "部分月份数据缺失",
    ))


@tool(description="为报告生成场景注入上下文标记，仅在生成个人使用报告前调用。")
def fill_context_for_report():
    """报告场景的上下文开关工具，本身不查数据，只负责触发 prompt 切换。"""
    return asdict(ToolResult(
        status=ToolStatus.SUCCESS,
        message="报告模式已激活",
        evidence={"action": "report_mode_activated"},
        next_step="接下来调用报告相关工具获取用户数据",
    ))
