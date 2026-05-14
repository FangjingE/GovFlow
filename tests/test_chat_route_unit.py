from contextlib import nullcontext
import sys
from types import SimpleNamespace
import types

sys.modules.setdefault("psycopg_pool", types.SimpleNamespace(ConnectionPool=object))
psycopg_mod = types.ModuleType("psycopg")
rows_mod = types.ModuleType("psycopg.rows")
rows_mod.dict_row = object()
psycopg_mod.rows = rows_mod
sys.modules.setdefault("psycopg", psycopg_mod)
sys.modules.setdefault("psycopg.rows", rows_mod)

from govflow.api.routes import chat
from govflow.models.schemas import ChatRequest
from govflow.services.gov_types import EMBEDDING_DIM, GovServiceRow


class _FakePool:
    def connection(self):
        return nullcontext(object())


def _settings(**overrides):
    base = {
        "default_hotline": "12345",
        "retrieval_mode": "vector",
        "retrieval_candidate_limit": 3,
        "retrieval_clarify_min_score_gap": 0.03,
        "retrieval_keyword_ranking_enabled": False,
        "text_match_min_score": 0.05,
        "vector_ivfflat_probes": 10,
        "vector_fallback_min_score": 0.70,
        "vector_answer_min_score": 0.78,
        "embedding_enabled": True,
        "llm_ranker_enabled": False,
        "llm_ranker_api_key": "test-key",
        "llm_ranker_base_url": "https://api.deepseek.com/v1",
        "llm_ranker_model": "deepseek-chat",
        "llm_ranker_top_k": 10,
        "llm_ranker_answer_threshold": 0.80,
        "llm_ranker_clarify_threshold": 0.60,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _service(service_id: int, name: str, score: float) -> GovServiceRow:
    return GovServiceRow(
        id=service_id,
        service_name=name,
        source_url=f"https://example.com/services/{service_id}",
        department="测试局",
        service_object="自然人",
        promise_days=1,
        legal_days=1,
        on_site_times=0,
        is_charge=False,
        accept_condition="条件",
        general_scope="全市",
        handle_form="窗口办理",
        item_type="即办件",
        handle_address="大厅",
        handle_time="工作日",
        consult_way="12345",
        complaint_way="12345",
        query_way="线上",
        match_score=score,
    )


def test_post_chat_returns_answer_for_high_confidence(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings())
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [
            _service(1, "居民身份证申领", 0.91),
            _service(2, "居民身份证换领", 0.82),
        ],
    )
    monkeypatch.setattr(chat.gr, "load_materials", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat.gr, "load_processes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat, "render_service_answer", lambda **_kwargs: "事项名称：居民身份证申领\n")

    resp = chat.post_chat(ChatRequest(message="我要办身份证"), pool=_FakePool())

    assert resp.kind == "answer"
    assert resp.reply.startswith("事项名称：居民身份证申领")
    assert resp.clarify_options == []
    assert resp.stages_executed == ["retrieve_vector", "load_detail", "template"]


def test_post_chat_returns_clarify_for_close_candidates(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings())
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [
            _service(1, "居民身份证申领", 0.80),
            _service(2, "居民身份证换领", 0.79),
            _service(3, "临时居民身份证申领", 0.76),
        ],
    )

    resp = chat.post_chat(ChatRequest(message="我要办身份证"), pool=_FakePool())

    assert resp.kind == "clarify"
    assert resp.clarify_question is not None
    assert len(resp.clarify_options) == 3
    assert resp.clarify_options[0].value == "居民身份证申领"
    assert resp.stages_executed == ["retrieve_vector", "template_clarify"]


def test_post_chat_returns_fallback_for_low_confidence(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings())
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [_service(1, "社会保险登记", 0.62)],
    )

    resp = chat.post_chat(ChatRequest(message="随便测试一个极不相关的查询词"), pool=_FakePool())

    assert resp.kind == "fallback"
    assert "LLM 决策不可用" in resp.reply
    assert resp.clarify_options == []
    assert resp.stages_executed == ["retrieve_vector", "reason_fallback"]


def test_post_chat_returns_answer_for_exact_service_name(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings())
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: None)
    monkeypatch.setattr(
        chat.gr,
        "find_service_by_exact_name",
        lambda *_args, **_kwargs: _service(7, "企业社会保险登记", 1.0),
    )
    monkeypatch.setattr(chat.gr, "load_materials", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat.gr, "load_processes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat, "render_service_answer", lambda **_kwargs: "事项名称：企业社会保险登记\n")

    resp = chat.post_chat(ChatRequest(message="企业社会保险登记"), pool=_FakePool())

    assert resp.kind == "answer"
    assert resp.reply.startswith("事项名称：企业社会保险登记")
    assert resp.clarify_options == []
    assert resp.stages_executed == ["retrieve_exact_name", "load_detail", "template"]


def test_post_chat_uses_llm_ranker_for_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        chat,
        "get_settings",
        lambda: _settings(
            llm_ranker_enabled=True,
            llm_ranker_top_k=3,
            llm_ranker_answer_threshold=0.80,
            llm_ranker_clarify_threshold=0.60,
        ),
    )
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [
            _service(1, "大型活动审批", 0.73),
            _service(2, "大型群众活动许可", 0.72),
            _service(3, "大型户外广告审批", 0.70),
        ],
    )
    monkeypatch.setattr(
        chat,
        "rank_candidates_with_llm",
        lambda _msg, _cands, _settings: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMRankResult"]
        ).LLMRankResult(best_id=1, confidence=0.91, reason="语义最接近"),
    )
    monkeypatch.setattr(chat.gr, "load_materials", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat.gr, "load_processes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        chat,
        "decide_dialog_with_llm",
        lambda *_args, **_kwargs: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMDialogDecision"]
        ).LLMDialogDecision(
            action="answer",
            best_id=1,
            reply="建议先申请大型群众性活动安全许可。",
            follow_up_question="",
            cited_ids=[1],
            reason="命中",
        ),
    )
    monkeypatch.setattr(
        chat,
        "generate_service_answer_with_llm",
        lambda *_args, **_kwargs: "建议先申请大型群众性活动安全许可。",
    )

    resp = chat.post_chat(ChatRequest(message="我要开大型演唱会怎么审批"), pool=_FakePool())

    assert resp.kind == "answer"
    assert "大型群众性活动安全许可" in resp.reply
    assert resp.stages_executed == ["retrieve_vector", "decide_llm", "load_detail", "llm_freeform_answer"]
    assert resp.sources[0].uri == "https://example.com/services/1"


def test_post_chat_uses_llm_ranker_for_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        chat,
        "get_settings",
        lambda: _settings(
            llm_ranker_enabled=True,
            llm_ranker_top_k=3,
            llm_ranker_answer_threshold=0.80,
            llm_ranker_clarify_threshold=0.60,
        ),
    )
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [
            _service(1, "大型活动审批", 0.73),
            _service(2, "大型群众活动许可", 0.72),
            _service(3, "大型户外广告审批", 0.70),
        ],
    )
    monkeypatch.setattr(chat, "rank_candidates_with_llm", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat,
        "decide_dialog_with_llm",
        lambda *_args, **_kwargs: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMDialogDecision"]
        ).LLMDialogDecision(
            action="fallback",
            best_id=None,
            reply="这个问题我暂时无法准确判断对应事项，建议拨打政务服务热线咨询：12345",
            follow_up_question="",
            cited_ids=[],
            reason="差距过大",
        ),
    )

    resp = chat.post_chat(ChatRequest(message="我要开大型演唱会怎么审批"), pool=_FakePool())

    assert resp.kind == "fallback"
    assert "建议拨打政务服务热线咨询" in resp.reply


def test_post_chat_uses_llm_soft_clarify(monkeypatch) -> None:
    monkeypatch.setattr(
        chat,
        "get_settings",
        lambda: _settings(
            llm_ranker_enabled=True,
            llm_ranker_top_k=3,
            llm_ranker_answer_threshold=0.80,
            llm_ranker_clarify_threshold=0.60,
        ),
    )
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [
            _service(1, "企业社会保险登记", 0.80),
            _service(2, "机关事业单位社会保险登记", 0.79),
            _service(3, "企业参保登记", 0.78),
        ],
    )
    monkeypatch.setattr(chat, "rank_candidates_with_llm", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat,
        "decide_dialog_with_llm",
        lambda *_args, **_kwargs: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMDialogDecision"]
        ).LLMDialogDecision(
            action="clarify",
            best_id=None,
            reply="我初步判断是企业社会保险登记，但还需要确认参保主体类型。",
            follow_up_question="请问你是企业首次参保登记，还是机关事业单位登记？",
            cited_ids=[1, 2],
            reason="信息不足",
        ),
    )

    resp = chat.post_chat(ChatRequest(message="企业社会保险登记"), pool=_FakePool())

    assert resp.kind == "clarify"
    assert "企业社会保险登记" in resp.reply
    assert "企业首次参保登记" in (resp.clarify_question or "")
    assert resp.clarify_options == []
    assert resp.stages_executed == ["retrieve_vector", "decide_llm", "llm_freeform_clarify"]
