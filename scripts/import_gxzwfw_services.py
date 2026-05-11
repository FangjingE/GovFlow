#!/usr/bin/env python3
"""Import Guangxi gov service items into GovFlow tables.

Default target:
防城港市公安局网上办事窗口
https://zwfw.gxzf.gov.cn/eportal/ui?regionCode=3113105254&pageId=d0144e0713974fa886c580945ed17165
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

try:
    from govflow.config import get_settings
except ModuleNotFoundError:
    sys.path.append(str(__file__).rsplit("/scripts/", 1)[0] + "/src")
    from govflow.config import get_settings


BASE_URL = "https://zwfw.gxzf.gov.cn"
DEFAULT_REGION_CODE = "3113105254"
DEFAULT_LIST_PAGE_ID = "d0144e0713974fa886c580945ed17165"
DEFAULT_DETAIL_PAGE_ID = "d0349fe94d1c4d139b006db643fb9e52"
DEFAULT_LIST_MODULE_ID = "ebdb702018aa466d8d12562fe9c89103"
SOURCE_PLATFORM = "gxzwfw"

MATERIAL_FORM = {
    "1": "纸质",
    "2": "电子",
    "3": "纸质和电子",
    "4": "纸质或电子",
}

MATERIAL_TYPE = {
    "1": "原件",
    "2": "复印件",
    "3": "原件和复印件",
    "4": "原件或复印件",
}

SOURCE_CHANNEL = {
    "99": "其他",
    "20": "政府部门核发",
    "10": "申请人自备",
}

ZERO_VECTOR_768 = "[" + ",".join(["0"] * 768) + "]"
EXPORT_DEFAULT_SENTINEL = "__DEFAULT__"


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\s+\n", "\n", text)
    text = text.strip()
    if not text or text in {"-", "null", "None"}:
        return None
    return text


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def bool_from_zh(value: str | None) -> bool | None:
    if not value:
        return None
    text = value.strip()
    if text in {"是", "收费", "1", "true", "True"}:
        return True
    if text in {"否", "不收费", "0", "false", "False"}:
        return False
    return None


class SimpleHTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "tr", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def text(self) -> str | None:
        return clean_text("".join(self.parts))


def html_to_text(fragment: str | None) -> str | None:
    if not fragment:
        return None
    parser = SimpleHTMLTextExtractor()
    parser.feed(fragment)
    return parser.text()


def first_match(pattern: str, text: str, flags: int = re.S) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return html_to_text(match.group(1))


def field_after_label(label: str, page_html: str) -> str | None:
    pattern = (
        r"<label[^>]*>\s*"
        + re.escape(label)
        + r"\s*</label>\s*<span[^>]*>(.*?)</span>"
    )
    return first_match(pattern, page_html)


def metric_value(metric_label: str, page_html: str) -> str | None:
    pattern = (
        r'<div class="bszn_item[^"]*">(?:(?!<div class="bszn_item).)*?'
        r'<span class="bszn_num_text">\s*'
        + re.escape(metric_label)
        + r".*?</span>"
    )
    block_match = re.search(pattern, page_html, re.S)
    if not block_match:
        return None
    block = block_match.group(0)
    return first_match(r'<span class="bszn_num[^"]*">(.*?)</span>', block)


def title_from_detail(page_html: str) -> str:
    title = first_match(r'<h1 class="titles">\s*(.*?)\s*</h1>', page_html)
    if title:
        return title
    title = first_match(r"<title>\s*(.*?)\s*</title>", page_html)
    if title:
        return title
    raise ValueError("detail page missing service title")


def extract_processes(page_html: str) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    flow_match = re.search(r'<div class="bs_lc">(.*?)</div>\s*</div>\s*<div id="tab4"', page_html, re.S)
    flow_html = flow_match.group(1) if flow_match else page_html
    table_pattern = r'<table class="table">\s*<thead class="title">(.*?)</thead>\s*<tbody class="item first">(.*?)</tbody>'
    for index, match in enumerate(re.finditer(table_pattern, flow_html, re.S), start=1):
        title_text = html_to_text(match.group(1)) or ""
        title_text = re.sub(r"^\d+\s*", "", title_text).strip() or f"步骤{index}"
        body = match.group(2)
        cells = re.findall(r"<td[^>]*>(.*?)</td>|<th[^>]*>(.*?)</th>", body, re.S)
        texts = [html_to_text(a or b) for a, b in cells]
        texts = [t for t in texts if t]
        step_desc = texts[0] if texts else None
        result = None
        standard = None
        for i, value in enumerate(texts):
            if value == "办理结果" and i + 1 < len(texts):
                result = texts[i + 1]
            if value == "审查标准" and i + 1 < len(texts):
                standard = texts[i + 1]
        desc_parts = [step_desc]
        if result:
            desc_parts.append(f"办理结果：{result}")
        if standard:
            desc_parts.append(f"审查标准：{standard}")
        processes.append(
            {
                "step_name": title_text,
                "step_desc": "\n".join(part for part in desc_parts if part),
                "sort": index,
            }
        )
    return processes


@dataclass
class ServiceItem:
    item_detail_id: str
    item_name: str
    parent_name: str | None = None
    implement_subject_name: str | None = None
    apply_way: str | None = None
    online_url: str | None = None
    detail_url: str | None = None
    raw_list_node: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedService:
    service: dict[str, Any]
    materials: list[dict[str, Any]]
    processes: list[dict[str, Any]]
    vector_text: str
    vector_text_main: str
    vector_text_aux: str
    raw_payload: dict[str, Any]


class GxzwfwClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        list_page_id: str = DEFAULT_LIST_PAGE_ID,
        detail_page_id: str = DEFAULT_DETAIL_PAGE_ID,
        list_module_id: str = DEFAULT_LIST_MODULE_ID,
        timeout: int = 30,
        sleep_seconds: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.list_page_id = list_page_id
        self.detail_page_id = detail_page_id
        self.list_module_id = list_module_id
        self.timeout = timeout
        self.sleep_seconds = sleep_seconds
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(),
        )

    def _request(self, url: str, data: dict[str, Any] | None = None) -> bytes:
        encoded_data = None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.base_url}/eportal/ui?regionCode={DEFAULT_REGION_CODE}&pageId={self.list_page_id}",
        }
        if data is not None:
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            headers["X-Requested-With"] = "XMLHttpRequest"
        req = urllib.request.Request(url, data=encoded_data, headers=headers, method="POST" if data else "GET")
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {url}: {body[:300]}") from exc

    def request_json(self, url: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        time.sleep(self.sleep_seconds)
        body = self._request(url, data=data).decode("utf-8", errors="replace")
        return json.loads(body)

    def request_html(self, url: str) -> str:
        time.sleep(self.sleep_seconds)
        return self._request(url).decode("utf-8", errors="replace")

    def list_items(self, region_code: str, *, page_size: int = 10, max_pages: int | None = None) -> list[ServiceItem]:
        endpoint = (
            f"{self.base_url}/eportal/ui?"
            f"pageId={urllib.parse.quote(self.list_page_id)}"
            f"&moduleId={urllib.parse.quote(self.list_module_id)}"
            "&portal.url=/portlet/officeServicePortlet/queryMainItemList"
        )
        items: list[ServiceItem] = []
        seen: set[str] = set()
        current = 1
        while True:
            payload = self.request_json(endpoint, {"current": current, "regionCode": region_code})
            if not payload.get("success"):
                raise RuntimeError(f"list API failed: {payload}")
            data = payload.get("data") or {}
            records = data.get("itemTreeNode") or []
            for item in flatten_service_items(records, self.detail_page_id):
                if item.item_detail_id in seen:
                    continue
                seen.add(item.item_detail_id)
                items.append(item)
            page = data.get("page") or {}
            total = int(page.get("total") or len(items))
            pages = int(page.get("pages") or ((total + page_size - 1) // page_size) or 1)
            if current >= pages:
                break
            if max_pages and current >= max_pages:
                break
            current += 1
        return items

    def detail_url(self, item_detail_id: str) -> str:
        return f"{self.base_url}/eportal/ui?pageId={self.detail_page_id}&itemDetailId={item_detail_id}"

    def fetch_detail(self, item_detail_id: str) -> str:
        return self.request_html(self.detail_url(item_detail_id))

    def fetch_materials(self, item_detail_id: str) -> list[dict[str, Any]]:
        endpoint = (
            f"{self.base_url}/eportal/ui?"
            f"pageId={urllib.parse.quote(self.detail_page_id)}"
            "&moduleId=3&portal.url=/portlet/officeServicePortlet/getMaterialsBySceneIds"
        )
        payload = self.request_json(endpoint, {"sceneIds": "", "itemDetailId": item_detail_id})
        if not payload.get("success"):
            raise RuntimeError(f"material API failed for {item_detail_id}: {payload}")
        return payload.get("data") or []


def flatten_service_items(records: list[dict[str, Any]], detail_page_id: str) -> list[ServiceItem]:
    items: list[ServiceItem] = []

    def visit(node: dict[str, Any], parent_name: str | None = None) -> None:
        obj = node.get("obj") or {}
        children = node.get("children") or []
        detail_id = obj.get("id") if obj.get("itemName") else None
        if detail_id:
            item_name = clean_text(obj.get("itemName") or node.get("name")) or str(detail_id)
            detail_url = f"{BASE_URL}/eportal/ui?pageId={detail_page_id}&itemDetailId={detail_id}"
            if str(obj.get("isExternalLink")) == "1" and obj.get("externalLinkUrl"):
                detail_url = obj.get("externalLinkUrl")
            items.append(
                ServiceItem(
                    item_detail_id=str(detail_id),
                    item_name=item_name,
                    parent_name=clean_text(parent_name),
                    implement_subject_name=clean_text(obj.get("implementSubjectName")),
                    apply_way=clean_text(obj.get("applyWay")),
                    online_url=clean_text(obj.get("onlineUrl")),
                    detail_url=detail_url,
                    raw_list_node=node,
                )
            )
        elif node.get("govItemDetail"):
            detail = node.get("govItemDetail") or {}
            detail_id = detail.get("id")
            if detail_id:
                items.append(
                    ServiceItem(
                        item_detail_id=str(detail_id),
                        item_name=clean_text(detail.get("itemName") or node.get("name")) or str(detail_id),
                        parent_name=clean_text(parent_name),
                        implement_subject_name=clean_text(detail.get("implementSubjectName")),
                        apply_way=clean_text(detail.get("applyWay")),
                        online_url=clean_text(detail.get("onlineUrl")),
                        detail_url=f"{BASE_URL}/eportal/ui?pageId={detail_page_id}&itemDetailId={detail_id}",
                        raw_list_node=node,
                    )
                )
        for child in children:
            visit(child, clean_text(node.get("name")) or parent_name)

    for record in records:
        visit(record)
    return items


def parse_detail_html(
    *,
    page_html: str,
    item: ServiceItem,
    region_code: str,
    detail_url: str,
    materials_api_raw: list[dict[str, Any]],
) -> ParsedService:
    service_name = title_from_detail(page_html)
    department = field_after_label("办理部门", page_html) or item.implement_subject_name
    service_object = field_after_label("服务对象", page_html)
    handle_form = field_after_label("办理形式", page_html)
    item_type = field_after_label("办件类型", page_html)
    accept_condition = field_after_label("受理条件", page_html)
    handle_address = field_after_label("办理地点", page_html)
    handle_time = field_after_label("办理时间", page_html)
    consult_way = field_after_label("咨询方式", page_html)
    complaint_way = field_after_label("监督投诉方式", page_html)
    query_way = field_after_label("办理进度查询", page_html) or field_after_label("查询方式", page_html)

    promise_days = parse_int(metric_value("承诺办结时限", page_html))
    legal_days = parse_int(metric_value("法定办结时限", page_html))
    on_site_times = parse_int(metric_value("到现场次数", page_html))
    is_charge = bool_from_zh(metric_value("是否收费", page_html))
    general_scope = metric_value("通办范围", page_html) or "-"

    processes = extract_processes(page_html)
    materials = parse_materials(materials_api_raw)

    raw_payload = {
        "list_item": item.raw_list_node,
        "materials": materials_api_raw,
        "detail_extract": {
            "source_title": service_name,
            "detail_url": detail_url,
            "parent_name": item.parent_name,
        },
    }
    service = {
        "service_name": service_name,
        "department": department,
        "service_object": service_object,
        "promise_days": promise_days,
        "legal_days": legal_days,
        "on_site_times": on_site_times,
        "is_charge": is_charge if is_charge is not None else False,
        "accept_condition": accept_condition,
        "general_scope": general_scope,
        "handle_form": handle_form,
        "item_type": item_type,
        "handle_address": handle_address,
        "handle_time": handle_time,
        "consult_way": consult_way,
        "complaint_way": complaint_way,
        "query_way": query_way,
        "source_platform": SOURCE_PLATFORM,
        "source_region_code": region_code,
        "source_item_id": item.item_detail_id,
        "source_url": detail_url,
        "raw_payload": raw_payload,
    }
    vector_text_main, vector_text_aux = build_vector_text_parts(service, materials, processes)
    vector_text = vector_text_main if vector_text_main.strip() else vector_text_aux
    return ParsedService(
        service=service,
        materials=materials,
        processes=processes,
        vector_text=vector_text,
        vector_text_main=vector_text_main,
        vector_text_aux=vector_text_aux,
        raw_payload=raw_payload,
    )


def parse_materials(raw_materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []

    def visit(raw: dict[str, Any]) -> None:
        material_form = MATERIAL_FORM.get(str(raw.get("materialFormal") or ""), clean_text(raw.get("materialFormal")))
        material_type = MATERIAL_TYPE.get(str(raw.get("materialType") or ""), clean_text(raw.get("materialType")))
        note_parts = []
        for label, key in [
            ("类型", "materialType"),
            ("来源渠道", "sourceChannel"),
            ("填报须知", "fillNotice"),
            ("受理标准", "acceptStandard"),
            ("备注", "remark"),
            ("纸质规格", "paperFormat"),
            ("是否需要签章", "isNeedSign"),
            ("签名签章要求", "signRequirement"),
            ("示例样表", "sampleFilePath"),
            ("空白表格", "blankFilePath"),
        ]:
            value = raw.get(key)
            if key == "materialType":
                value = material_type
            elif key == "sourceChannel":
                value = SOURCE_CHANNEL.get(str(value or ""), clean_text(value))
            elif key == "isNeedSign":
                value = "是" if str(value) == "1" else "否"
            value_text = clean_text(value)
            if value_text:
                note_parts.append(f"{label}：{value_text}")
        parsed.append(
            {
                "material_name": clean_text(raw.get("materialName")) or "-",
                "is_required": str(raw.get("necessity")) == "1",
                "material_form": material_form,
                "original_num": parse_int(raw.get("materialNum")),
                "copy_num": parse_int(raw.get("copyAmount")),
                "note": "\n".join(note_parts) or None,
            }
        )
        for child in raw.get("childList") or []:
            visit(child)

    for material in raw_materials:
        visit(material)
    return parsed


def default_export_path(region_code: str) -> str:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"gxzwfw_services_{region_code}_{ts}.json"
    return os.path.join(project_root, "data", filename)


def build_vector_text(
    service: dict[str, Any],
    materials: list[dict[str, Any]],
    processes: list[dict[str, Any]],
) -> str:
    main_text, aux_text = build_vector_text_parts(service, materials, processes)
    return main_text if main_text.strip() else aux_text


def build_vector_text_parts(
    service: dict[str, Any],
    materials: list[dict[str, Any]],
    processes: list[dict[str, Any]],
) -> tuple[str, str]:
    main_lines = [
        f"事项名称：{service.get('service_name') or ''}",
        f"办理部门：{service.get('department') or ''}",
        f"服务对象：{service.get('service_object') or ''}",
        f"受理条件：{service.get('accept_condition') or ''}",
        f"办件类型：{service.get('item_type') or ''}",
        f"办理形式：{service.get('handle_form') or ''}",
    ]
    aux_lines = [
        "申请材料：" + "；".join(m["material_name"] for m in materials if m.get("material_name")),
        "办理流程：" + "；".join(p["step_name"] for p in processes if p.get("step_name")),
    ]
    main_text = "\n".join(line for line in main_lines if line.strip())
    aux_text = "\n".join(line for line in aux_lines if line.strip())
    return main_text, aux_text


def upsert_service(conn: Any, parsed: ParsedService) -> int:
    from psycopg.types.json import Jsonb

    service = parsed.service
    stmt = """
INSERT INTO gov_service (
    service_name, department, service_object, promise_days, legal_days, on_site_times,
    is_charge, accept_condition, general_scope, handle_form, item_type,
    handle_address, handle_time, consult_way, complaint_way, query_way,
    source_platform, source_region_code, source_item_id, source_url, raw_payload,
    last_crawled_at, status, updated_at
) VALUES (
    %(service_name)s, %(department)s, %(service_object)s, %(promise_days)s, %(legal_days)s, %(on_site_times)s,
    %(is_charge)s, %(accept_condition)s, %(general_scope)s, %(handle_form)s, %(item_type)s,
    %(handle_address)s, %(handle_time)s, %(consult_way)s, %(complaint_way)s, %(query_way)s,
    %(source_platform)s, %(source_region_code)s, %(source_item_id)s, %(source_url)s, %(raw_payload)s,
    now(), true, now()
)
ON CONFLICT (source_platform, source_region_code, source_item_id)
WHERE source_platform IS NOT NULL
  AND source_region_code IS NOT NULL
  AND source_item_id IS NOT NULL
DO UPDATE SET
    service_name = EXCLUDED.service_name,
    department = EXCLUDED.department,
    service_object = EXCLUDED.service_object,
    promise_days = EXCLUDED.promise_days,
    legal_days = EXCLUDED.legal_days,
    on_site_times = EXCLUDED.on_site_times,
    is_charge = EXCLUDED.is_charge,
    accept_condition = EXCLUDED.accept_condition,
    general_scope = EXCLUDED.general_scope,
    handle_form = EXCLUDED.handle_form,
    item_type = EXCLUDED.item_type,
    handle_address = EXCLUDED.handle_address,
    handle_time = EXCLUDED.handle_time,
    consult_way = EXCLUDED.consult_way,
    complaint_way = EXCLUDED.complaint_way,
    query_way = EXCLUDED.query_way,
    source_url = EXCLUDED.source_url,
    raw_payload = EXCLUDED.raw_payload,
    last_crawled_at = now(),
    status = true,
    updated_at = now()
RETURNING id;
"""
    values = dict(service)
    values["raw_payload"] = Jsonb(service["raw_payload"])
    with conn.cursor() as cur:
        cur.execute(stmt, values)
        service_id = cur.fetchone()[0]
        cur.execute("DELETE FROM service_material WHERE service_id = %s", (service_id,))
        cur.execute("DELETE FROM service_process WHERE service_id = %s", (service_id,))
        cur.execute("DELETE FROM service_embedding WHERE service_id = %s", (service_id,))
        if parsed.materials:
            cur.executemany(
                """
INSERT INTO service_material (
    service_id, material_name, is_required, material_form, original_num, copy_num, note
) VALUES (
    %(service_id)s, %(material_name)s, %(is_required)s, %(material_form)s, %(original_num)s, %(copy_num)s, %(note)s
)
""",
                [{**material, "service_id": service_id} for material in parsed.materials],
            )
        if parsed.processes:
            cur.executemany(
                """
INSERT INTO service_process (service_id, step_name, step_desc, sort)
VALUES (%(service_id)s, %(step_name)s, %(step_desc)s, %(sort)s)
""",
                [{**process, "service_id": service_id} for process in parsed.processes],
            )
        cur.execute(
            """
INSERT INTO service_embedding (service_id, service_name, vector_text, embedding)
VALUES (%s, %s, %s, %s::vector)
""",
            (service_id, service["service_name"], parsed.vector_text, ZERO_VECTOR_768),
        )
    return int(service_id)


def ensure_database_ready(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'gov_service' AND column_name = 'source_item_id'
)
"""
        )
        has_source_fields = cur.fetchone()[0]
        if not has_source_fields:
            raise RuntimeError(
                "gov_service lacks source fields. Run sql/migrations/001_add_gov_service_source_fields.sql first."
            )
        cur.execute("SELECT to_regclass('public.uq_gov_service_source_item')")
        if cur.fetchone()[0] is None:
            raise RuntimeError(
                "missing uq_gov_service_source_item. Run sql/migrations/002_add_gov_service_source_unique.sql first."
            )


def import_services(args: argparse.Namespace) -> None:
    if args.export_json and args.dry_run:
        raise ValueError("--export-json and --dry-run cannot be used together.")
    if args.import_json and (args.export_json or args.dry_run):
        raise ValueError("--import-json cannot be combined with --export-json or --dry-run.")

    if args.import_json:
        import psycopg

        dsn = args.database_url or os.environ.get("GOVFLOW_DATABASE_URL") or get_settings().database_url
        with open(args.import_json, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        rows = payload.get("items") or []
        imported = 0
        failed = 0
        with psycopg.connect(dsn) as conn:
            ensure_database_ready(conn)
            for index, row in enumerate(rows, start=1):
                try:
                    service = row.get("service") or {}
                    if "raw_payload" not in service:
                        service["raw_payload"] = row.get("raw_payload") or {}
                    parsed = ParsedService(
                        service=service,
                        materials=row.get("materials") or [],
                        processes=row.get("processes") or [],
                        vector_text=row.get("vector_text") or build_vector_text(
                            service,
                            row.get("materials") or [],
                            row.get("processes") or [],
                        ),
                        vector_text_main=(
                            row.get("vector_text_main")
                            or build_vector_text_parts(
                                service,
                                row.get("materials") or [],
                                row.get("processes") or [],
                            )[0]
                        ),
                        vector_text_aux=(
                            row.get("vector_text_aux")
                            or build_vector_text_parts(
                                service,
                                row.get("materials") or [],
                                row.get("processes") or [],
                            )[1]
                        ),
                        raw_payload=row.get("raw_payload") or service.get("raw_payload") or {},
                    )
                    service_id = upsert_service(conn, parsed)
                    conn.commit()
                    imported += 1
                    print(
                        f"[{index}/{len(rows)}] saved service_id={service_id}, "
                        f"materials={len(parsed.materials)}, processes={len(parsed.processes)}"
                    )
                except Exception as exc:  # noqa: BLE001 - continue importing other items.
                    conn.rollback()
                    failed += 1
                    print(f"[{index}/{len(rows)}] ERROR: {exc}", file=sys.stderr)
                    if not args.continue_on_error:
                        raise
        print(f"Done. imported={imported}, failed={failed}, source={args.import_json}")
        return

    client = GxzwfwClient(
        list_page_id=args.list_page_id,
        detail_page_id=args.detail_page_id,
        list_module_id=args.list_module_id,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
    )
    items = client.list_items(args.region_code, max_pages=args.max_pages)
    if args.limit:
        items = items[: args.limit]
    print(f"Found {len(items)} service detail items for regionCode={args.region_code}.")
    if args.export_json:
        export_rows: list[dict[str, Any]] = []
        failed = 0
        for index, item in enumerate(items, start=1):
            detail_url = item.detail_url or client.detail_url(item.item_detail_id)
            if detail_url.startswith("/"):
                detail_url = BASE_URL + detail_url
            try:
                print(f"[{index}/{len(items)}] fetching {item.item_name} ({item.item_detail_id})")
                page_html = client.request_html(detail_url)
                materials_raw = client.fetch_materials(item.item_detail_id)
                parsed = parse_detail_html(
                    page_html=page_html,
                    item=item,
                    region_code=args.region_code,
                    detail_url=detail_url,
                    materials_api_raw=materials_raw,
                )
                export_rows.append(
                    {
                        "service": parsed.service,
                        "materials": parsed.materials,
                        "processes": parsed.processes,
                        "vector_text": parsed.vector_text,
                        "vector_text_main": parsed.vector_text_main,
                        "vector_text_aux": parsed.vector_text_aux,
                        "raw_payload": parsed.raw_payload,
                    }
                )
                print(
                    f"  parsed materials={len(parsed.materials)}, "
                    f"processes={len(parsed.processes)}"
                )
            except Exception as exc:  # noqa: BLE001 - best-effort export.
                failed += 1
                print(f"  ERROR: {exc}", file=sys.stderr)
                if not args.continue_on_error:
                    raise
        output_path = (
            default_export_path(args.region_code)
            if args.export_json == EXPORT_DEFAULT_SENTINEL
            else args.export_json
        )
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fp:
            json.dump(
                {
                    "source_platform": SOURCE_PLATFORM,
                    "source_region_code": args.region_code,
                    "list_page_id": args.list_page_id,
                    "detail_page_id": args.detail_page_id,
                    "total_items": len(export_rows),
                    "failed_items": failed,
                    "items": export_rows,
                },
                fp,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Done. exported={len(export_rows)}, failed={failed}, file={output_path}")
        return

    if args.dry_run:
        for item in items:
            print(f"- {item.item_name} [{item.item_detail_id}]")
            if args.fetch_details:
                detail_url = item.detail_url or client.detail_url(item.item_detail_id)
                page_html = client.request_html(detail_url)
                materials_raw = client.fetch_materials(item.item_detail_id)
                parsed = parse_detail_html(
                    page_html=page_html,
                    item=item,
                    region_code=args.region_code,
                    detail_url=detail_url,
                    materials_api_raw=materials_raw,
                )
                service = parsed.service
                print(
                    "  "
                    f"department={service.get('department')}, "
                    f"promise_days={service.get('promise_days')}, "
                    f"legal_days={service.get('legal_days')}, "
                    f"on_site_times={service.get('on_site_times')}, "
                    f"materials={len(parsed.materials)}, "
                    f"processes={len(parsed.processes)}"
                )
        return

    import psycopg

    dsn = args.database_url or os.environ.get("GOVFLOW_DATABASE_URL") or get_settings().database_url
    imported = 0
    failed = 0
    with psycopg.connect(dsn) as conn:
        ensure_database_ready(conn)
        for index, item in enumerate(items, start=1):
            detail_url = item.detail_url or client.detail_url(item.item_detail_id)
            if detail_url.startswith("/"):
                detail_url = BASE_URL + detail_url
            try:
                print(f"[{index}/{len(items)}] fetching {item.item_name} ({item.item_detail_id})")
                page_html = client.request_html(detail_url)
                materials_raw = client.fetch_materials(item.item_detail_id)
                parsed = parse_detail_html(
                    page_html=page_html,
                    item=item,
                    region_code=args.region_code,
                    detail_url=detail_url,
                    materials_api_raw=materials_raw,
                )
                service_id = upsert_service(conn, parsed)
                conn.commit()
                imported += 1
                print(
                    f"  saved service_id={service_id}, "
                    f"materials={len(parsed.materials)}, processes={len(parsed.processes)}"
                )
            except Exception as exc:  # noqa: BLE001 - continue importing other public items.
                conn.rollback()
                failed += 1
                print(f"  ERROR: {exc}", file=sys.stderr)
                if not args.continue_on_error:
                    raise
    print(f"Done. imported={imported}, failed={failed}.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import Guangxi government service items into GovFlow.")
    parser.add_argument("--region-code", default=DEFAULT_REGION_CODE, help="Gov category/department regionCode.")
    parser.add_argument("--list-page-id", default=DEFAULT_LIST_PAGE_ID)
    parser.add_argument("--detail-page-id", default=DEFAULT_DETAIL_PAGE_ID)
    parser.add_argument("--list-module-id", default=DEFAULT_LIST_MODULE_ID)
    parser.add_argument("--database-url", default=None, help="Defaults to GOVFLOW_DATABASE_URL or app settings.")
    parser.add_argument("--limit", type=int, default=None, help="Only import the first N detail items.")
    parser.add_argument("--max-pages", type=int, default=None, help="Only crawl first N list pages.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds to sleep between site requests.")
    parser.add_argument("--dry-run", action="store_true", help="List matched detail items without writing DB.")
    parser.add_argument(
        "--import-json",
        default=None,
        help="Import items from an exported JSON file into database.",
    )
    parser.add_argument(
        "--export-json",
        nargs="?",
        const=EXPORT_DEFAULT_SENTINEL,
        default=None,
        help="Export parsed items to a JSON file instead of writing DB. "
        "If no path is given, writes to <project_root>/data/.",
    )
    parser.add_argument("--fetch-details", action="store_true", help="With --dry-run, fetch and parse detail pages.")
    parser.add_argument("--continue-on-error", action="store_true", help="Skip failed items and keep importing.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    import_services(args)


if __name__ == "__main__":
    main()
