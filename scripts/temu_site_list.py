#!/usr/bin/env python3
"""实时查询 Temu 站点列表，并按国家或地区名称解析站点。"""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError

from geekbi_auth import ActionRequired, authenticated_json_request, response_message


DEFAULT_BASE_URL = "https://openapi.geekbi.com"
ENDPOINT = "/api/v1/temu/site/ai-list"


def normalize_name(value):
    normalized = value.strip().casefold()
    for suffix in ("站点", "站"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()
            break
    return normalized


def validate_response(payload):
    if not isinstance(payload, dict):
        raise ValueError("站点列表响应必须是 JSON 对象")
    if payload.get("code") != 0:
        raise ValueError(response_message(payload, "站点列表查询失败"))
    if not isinstance(payload.get("data"), list):
        raise ValueError("站点列表响应缺少 data 数组")
    return payload["data"]


def resolve_site(sites, country):
    target = normalize_name(country)
    if not target:
        raise ValueError("国家或地区名称不能为空")

    matches = []
    seen = set()
    for site in sites:
        if not isinstance(site, dict):
            continue
        site_names = [site.get("name"), site.get("cnName")]
        normalized_site_names = {
            normalize_name(name) for name in site_names if isinstance(name, str)
        }
        if normalized_site_names.intersection({"all", "all sites", "全部"}):
            continue
        site_id = site.get("siteId")
        if isinstance(site_id, bool) or not isinstance(site_id, int):
            continue
        if target not in normalized_site_names:
            continue
        key = (site_id, site.get("name"), site.get("cnName"))
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "siteId": site_id,
                "name": site.get("name"),
                "cnName": site.get("cnName"),
                "currency": site.get("currency"),
            }
        )

    if not matches:
        raise ValueError("未找到该 Temu 站点，请确认国家或地区名称")
    return matches


def main():
    parser = argparse.ArgumentParser(description="实时解析 Temu 站点")
    parser.add_argument("--country", required=True, help="国家或地区的中文名或英文名")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"极鲸云服务地址，默认 {DEFAULT_BASE_URL}",
    )
    parser.add_argument("--timeout", type=float, default=30, help="请求超时秒数")
    args = parser.parse_args()

    try:
        payload = authenticated_json_request(
            f"{args.base_url.rstrip('/')}{ENDPOINT}",
            args.base_url,
            args.timeout,
        )
        matches = resolve_site(validate_response(payload), args.country)
    except ActionRequired as error:
        print(json.dumps(error.public_payload(), ensure_ascii=False, indent=2))
        return 2
    except (ValueError, HTTPError, URLError, TimeoutError) as error:
        print(
            json.dumps({"error": True, "msg": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(json.dumps({"code": 0, "data": {"matches": matches}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
