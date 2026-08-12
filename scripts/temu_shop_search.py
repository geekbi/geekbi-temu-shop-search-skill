#!/usr/bin/env python3
"""调用极鲸云的 Temu 店铺搜索接口。"""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from geekbi_auth import ActionRequired, authenticated_json_request, response_message


DEFAULT_BASE_URL = "https://openapi.geekbi.com"
ENDPOINT = "/api/v1/temu/mall/ai-search"
BASE_PARAMS = {
    "keyword",
    "catIds",
    "siteId",
    "page",
    "size",
    "sort",
    "order",
    "hostingMode",
}
RANGE_PARAMS = {
    "mallSold",
    "mallSales",
    "daySold",
    "weekSold",
    "monthSold",
    "daySales",
    "weekSales",
    "monthSales",
    "mallStar",
    "reviewNum",
    "goodsNum",
    "followerNum",
    "avgPrice",
    "daySoldRate",
    "weekSoldRate",
    "monthSoldRate",
    "daySalesRate",
    "weekSalesRate",
    "monthSalesRate",
    "dayItemCount",
    "weekItemCount",
    "monthItemCount",
    "dayItemCountRate",
    "weekItemCountRate",
    "monthItemCountRate",
    "dayFollower",
    "weekFollower",
    "monthFollower",
    "dayFollowerRate",
    "weekFollowerRate",
    "monthFollowerRate",
    "daySellthroughCount",
    "weekSellthroughCount",
    "monthSellthroughCount",
    "daySellthroughRate",
    "weekSellthroughRate",
    "monthSellthroughRate",
    "mallOpenTime",
}
SORT_FIELDS = {
    "mallSold",
    "mallSales",
    "mallStar",
    "reviewNum",
    "goodsNum",
    "followerNum",
    "avgPrice",
    "hot",
    "daySold",
    "weekSold",
    "monthSold",
    "daySoldRate",
    "weekSoldRate",
    "monthSoldRate",
    "daySales",
    "weekSales",
    "monthSales",
    "daySalesRate",
    "weekSalesRate",
    "monthSalesRate",
    "dayItemCount",
    "weekItemCount",
    "monthItemCount",
    "dayItemCountRate",
    "weekItemCountRate",
    "monthItemCountRate",
    "dayFollower",
    "weekFollower",
    "monthFollower",
    "dayFollowerRate",
    "weekFollowerRate",
    "monthFollowerRate",
    "daySellthroughCount",
    "weekSellthroughCount",
    "monthSellthroughCount",
    "daySellthroughRate",
    "weekSellthroughRate",
    "monthSellthroughRate",
    "mallOpenTime",
    "updateTime",
}


def is_allowed_param(key):
    if key in BASE_PARAMS:
        return True
    return any(key == f"{prefix}{suffix}" for prefix in RANGE_PARAMS for suffix in ("Min", "Max"))


def parse_positive_int(key, value, maximum=None):
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{key} 必须是整数") from error
    if parsed < 1:
        raise ValueError(f"{key} 必须大于等于 1")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{key} 最大值为 {maximum}")


def parse_percentage(key, value):
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError("动销率必须是数字") from error
    if parsed < 0 or parsed > 100:
        raise ValueError("动销率必须在 0 到 100 之间")


def parse_params(raw_params):
    params = []
    single_values = {}
    for raw_param in raw_params:
        if "=" not in raw_param:
            raise ValueError(f"参数必须使用 key=value 格式: {raw_param}")
        key, value = raw_param.split("=", 1)
        if not key:
            raise ValueError(f"参数名不能为空: {raw_param}")
        if not is_allowed_param(key):
            raise ValueError(f"当前店铺搜索 Skill 不支持参数: {key}")
        params.append((key, value))
        if key != "catIds":
            single_values[key] = value

    if "sort" in single_values and single_values["sort"] not in SORT_FIELDS:
        raise ValueError(f"当前店铺搜索 Skill 不支持排序字段: {single_values['sort']}")
    if "order" in single_values and single_values["order"] not in ("asc", "desc"):
        raise ValueError("order 只支持 asc 或 desc")
    if "page" in single_values:
        parse_positive_int("page", single_values["page"])
    if "size" in single_values:
        parse_positive_int("size", single_values["size"], maximum=200)
    if "siteId" in single_values:
        parse_positive_int("站点 ID", single_values["siteId"])
    if "keyword" in single_values and len(single_values["keyword"]) > 300:
        raise ValueError("keyword 不能超过 300 个字符")
    for key, value in single_values.items():
        if key.startswith(("daySellthroughRate", "weekSellthroughRate", "monthSellthroughRate")):
            parse_percentage(key, value)
    return params


def build_url(base_url, params):
    url = f"{base_url.rstrip('/')}{ENDPOINT}"
    query = urlencode(params)
    return f"{url}?{query}" if query else url


def validate_response(payload):
    if not isinstance(payload, dict):
        raise ValueError("接口响应必须是 JSON 对象")
    if payload.get("code") != 0:
        raise ValueError(response_message(payload, "接口返回失败"))
    if not isinstance(payload.get("data"), dict):
        raise ValueError("成功响应缺少 data 对象")
    return {"code": 0, "data": payload["data"]}


def main():
    parser = argparse.ArgumentParser(description="查询 Temu 店铺并输出 JSON")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"极鲸云服务地址，默认 {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="查询参数，格式为 key=value；列表字段可重复传入",
    )
    parser.add_argument("--timeout", type=float, default=30, help="请求超时秒数")
    args = parser.parse_args()

    try:
        params = parse_params(args.param)
        payload = authenticated_json_request(
            build_url(args.base_url, params),
            args.base_url,
            args.timeout,
        )
        payload = validate_response(payload)
    except ActionRequired as error:
        print(json.dumps(error.public_payload(), ensure_ascii=False, indent=2))
        return 2
    except (ValueError, HTTPError, URLError, TimeoutError) as error:
        print(
            json.dumps({"error": True, "msg": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
