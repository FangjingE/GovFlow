"""政务事项：Top-1 检索（文本相似度 / 可选向量）。"""

from __future__ import annotations

import re
from typing import Any, Literal

from psycopg.rows import dict_row

from govflow.services.gov_types import (
    EMBEDDING_DIM,
    GovServiceRow,
    MaterialRow,
    ProcessRow,
)

RetrievalMode = Literal["text", "vector"]

__all__ = [
    "EMBEDDING_DIM",
    "RetrievalMode",
    "GovServiceRow",
    "MaterialRow",
    "ProcessRow",
    "find_service_by_exact_name",
    "find_topk_services_text",
    "find_topk_services_vector",
    "find_top1_service_text",
    "find_top1_service_vector",
    "find_topk_service_names_text",
    "find_topk_service_names_vector",
    "load_materials",
    "load_processes",
]

_SERVICE_SELECT_COLUMNS = """
    gs.id,
    gs.service_name,
    gs.department,
    gs.service_object,
    gs.promise_days,
    gs.legal_days,
    gs.on_site_times,
    gs.is_charge,
    gs.accept_condition,
    gs.general_scope,
    gs.handle_form,
    gs.item_type,
    gs.handle_address,
    gs.handle_time,
    gs.consult_way,
    gs.complaint_way,
    gs.query_way
"""


def _vec_literal(values: list[float]) -> str:
    if len(values) != EMBEDDING_DIM:
        raise ValueError(f"query_vector 必须为 {EMBEDDING_DIM} 维，当前 {len(values)}")
    return "[" + ",".join(str(float(x)) for x in values) + "]"


def _build_query_terms(query: str, *, max_terms: int = 12) -> list[str]:
    q = query.strip()
    if not q:
        return []
    tokens: list[str] = []
    for seg in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", q):
        s = seg.strip()
        if len(s) >= 2:
            tokens.append(s)
        # 对中文短句补充 2-gram，提升“社保/医保”等关键词命中概率
        if re.search(r"[\u4e00-\u9fff]", s) and len(s) >= 3:
            for i in range(len(s) - 1):
                gram2 = s[i : i + 2]
                if len(gram2) == 2:
                    tokens.append(gram2)

    out: list[str] = []
    seen: set[str] = set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= max_terms:
            break
    return out


def _normalize_service_name(text: str) -> str:
    out = text.strip()
    if not out:
        return ""
    out = out.translate(
        str.maketrans(
            {
                "（": "(",
                "）": ")",
                "【": "[",
                "】": "]",
                "－": "-",
                "—": "-",
                "–": "-",
                "　": " ",
            }
        )
    )
    out = re.sub(r"\s+", "", out)
    return out.casefold()


def _service_from_row(
    row: dict[str, Any],
    *,
    score_field: str | None = None,
    distance_field: str | None = None,
) -> GovServiceRow:
    score: float | None = None
    if score_field is not None and row.get(score_field) is not None:
        score = float(row.pop(score_field))
    if distance_field is not None and row.get(distance_field) is not None:
        score = 1.0 - float(row.pop(distance_field))
    keyword_hits = row.pop("keyword_hits", None)
    return GovServiceRow(
        **row,
        match_score=score,
        keyword_hits=int(keyword_hits) if keyword_hits is not None else None,
    )


def find_service_by_exact_name(conn: Any, query: str) -> GovServiceRow | None:
    norm_query = _normalize_service_name(query)
    if not norm_query:
        return None
    stmt = f"""
SELECT
{_SERVICE_SELECT_COLUMNS}
FROM gov_service gs
WHERE gs.status = true
ORDER BY gs.id;
"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(stmt)
        rows = cur.fetchall()
    matches = [
        GovServiceRow(**row, match_score=1.0)
        for row in rows
        if _normalize_service_name(str(row.get("service_name") or "")) == norm_query
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def find_topk_services_text(conn: Any, query: str, *, limit: int = 3) -> list[GovServiceRow]:
    q = query.strip()
    if not q:
        return []
    terms = _build_query_terms(q)
    stmt = f"""
WITH ranked AS (
    SELECT
{_SERVICE_SELECT_COLUMNS},
        CASE
            WHEN cardinality(%(terms)s::text[]) = 0 THEN 0
            ELSE (
                SELECT COUNT(*)
                FROM unnest(%(terms)s::text[]) AS t(term)
                WHERE gs.service_name ILIKE '%%' || t.term || '%%'
                   OR se.vector_text ILIKE '%%' || t.term || '%%'
            )
        END AS keyword_hits,
        GREATEST(
            similarity(gs.service_name, %(q)s),
            similarity(se.vector_text, %(q)s),
            CASE WHEN gs.service_name ILIKE '%%' || %(q)s || '%%' THEN 0.12 ELSE 0.0 END,
            CASE WHEN se.vector_text ILIKE '%%' || %(q)s || '%%' THEN 0.12 ELSE 0.0 END
        ) AS score
    FROM service_embedding se
    JOIN gov_service gs ON se.service_id = gs.id
    WHERE gs.status = true
)
SELECT *
FROM ranked
ORDER BY keyword_hits DESC, score DESC, service_name
LIMIT %(limit)s;
"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(stmt, {"q": q, "terms": terms, "limit": int(limit)})
        rows = cur.fetchall()
    return [_service_from_row(r, score_field="score") for r in rows]


def _build_keyword_order_clause(enabled: bool, score_expr: str) -> str:
    if enabled:
        return f"keyword_hits DESC, {score_expr}, service_name"
    return f"{score_expr}, service_name"


def find_top1_service_text(
    conn: Any,
    query: str,
    *,
    min_score: float,
) -> GovServiceRow | None:
    rows = find_topk_services_text(conn, query, limit=1)
    if not rows:
        return None
    if float(rows[0].match_score or 0.0) < min_score:
        return None
    return rows[0]


def find_topk_services_vector(
    conn: Any,
    query_vector: list[float],
    *,
    limit: int = 3,
    query_text: str | None = None,
    ivfflat_probes: int | None = None,
    keyword_ranking_enabled: bool = True,
) -> list[GovServiceRow]:
    literal = _vec_literal(query_vector)
    terms = _build_query_terms(query_text or "")
    stmt = f"""
WITH ranked AS (
    SELECT
{_SERVICE_SELECT_COLUMNS},
        CASE
            WHEN cardinality(%(terms)s::text[]) = 0 THEN 0
            ELSE (
                SELECT COUNT(*)
                FROM unnest(%(terms)s::text[]) AS t(term)
                WHERE gs.service_name ILIKE '%%' || t.term || '%%'
                   OR se.vector_text ILIKE '%%' || t.term || '%%'
            )
        END AS keyword_hits,
        (se.embedding <=> %(vec)s::vector) AS distance
    FROM service_embedding se
    JOIN gov_service gs ON se.service_id = gs.id
    WHERE gs.status = true
)
SELECT *
FROM ranked
ORDER BY {_build_keyword_order_clause(keyword_ranking_enabled, "distance ASC")}
LIMIT %(limit)s;
"""
    with conn.cursor(row_factory=dict_row) as cur:
        if ivfflat_probes is not None:
            cur.execute(
                "SELECT set_config('ivfflat.probes', %(p)s, true)",
                {"p": str(int(ivfflat_probes))},
            )
        cur.execute(stmt, {"vec": literal, "terms": terms, "limit": int(limit)})
        rows = cur.fetchall()
    return [_service_from_row(r, distance_field="distance") for r in rows]


def find_top1_service_vector(
    conn: Any, query_vector: list[float], *, ivfflat_probes: int | None = None
) -> GovServiceRow | None:
    rows = find_topk_services_vector(
        conn,
        query_vector,
        limit=1,
        ivfflat_probes=ivfflat_probes,
    )
    if not rows:
        return None
    return rows[0]


def find_topk_service_names_text(conn: Any, query: str, *, limit: int = 3) -> list[str]:
    rows = find_topk_services_text(conn, query, limit=limit)
    return [svc.service_name for svc in rows if svc.service_name]


def find_topk_service_names_vector(
    conn: Any,
    query_vector: list[float],
    *,
    limit: int = 3,
    query_text: str | None = None,
    ivfflat_probes: int | None = None,
    keyword_ranking_enabled: bool = True,
) -> list[str]:
    rows = find_topk_services_vector(
        conn,
        query_vector,
        limit=limit,
        query_text=query_text,
        ivfflat_probes=ivfflat_probes,
        keyword_ranking_enabled=keyword_ranking_enabled,
    )
    return [svc.service_name for svc in rows if svc.service_name]


def load_materials(conn: Any, service_id: int) -> list[MaterialRow]:
    stmt = """
SELECT material_name, is_required, material_form, original_num, copy_num, note
FROM service_material
WHERE service_id = %(sid)s
ORDER BY id;
"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(stmt, {"sid": service_id})
        rows = cur.fetchall()
    return [MaterialRow(**r) for r in rows]


def load_processes(conn: Any, service_id: int) -> list[ProcessRow]:
    stmt = """
SELECT step_name, step_desc, sort
FROM service_process
WHERE service_id = %(sid)s
ORDER BY sort NULLS LAST, id;
"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(stmt, {"sid": service_id})
        rows = cur.fetchall()
    return [ProcessRow(**r) for r in rows]
