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
from govflow.models.schemas import ChatRequest, GetServiceDetailRequest, SearchServicesRequest
from govflow.services.gov_types import EMBEDDING_DIM, GovServiceRow, MaterialRow, ProcessRow


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
        "conversation_session_ttl_minutes": 30,
        "conversation_max_retries": 3,
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


def test_post_chat_legacy_answer_for_high_confidence(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings(llm_ranker_enabled=False))
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
    assert resp.session_state == "answer"
    assert resp.reply.startswith("事项名称：居民身份证申领")
    assert resp.stages_executed == ["retrieve_vector", "load_detail", "template"]


def test_post_chat_legacy_clarify_for_close_candidates(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings(llm_ranker_enabled=False))
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
    assert resp.session_state == "clarify"
    assert resp.clarify_question is not None
    assert len(resp.clarify_options) == 3
    assert resp.stages_executed == ["retrieve_vector", "plain_clarify"]


def test_post_chat_legacy_fallback_for_low_confidence(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings(llm_ranker_enabled=False))
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [_service(1, "社会保险登记", 0.62)],
    )

    resp = chat.post_chat(ChatRequest(message="随便测试一个极不相关的查询词"), pool=_FakePool())

    assert resp.kind == "fallback"
    assert resp.session_state == "fallback"
    assert "LLM 决策不可用" in resp.reply
    assert resp.stages_executed == ["retrieve_vector", "plain_fallback"]


def test_post_chat_react_clarifies_when_user_not_clear(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings(llm_ranker_enabled=True))
    monkeypatch.setattr(
        chat,
        "assess_user_intent_with_llm",
        lambda *_args, **_kwargs: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMIntentAssessment"]
        ).LLMIntentAssessment(
            is_clear=False,
            rewritten_query="",
            reply="你要咨询的是新办、补办还是换领？",
            missing_info=["办理阶段"],
            reason="事项不够明确",
        ),
    )

    resp = chat.post_chat(ChatRequest(message="我要办身份证"), pool=_FakePool())

    assert resp.kind == "clarify"
    assert resp.session_state == "clarify"
    assert resp.reply == "你要咨询的是新办、补办还是换领？"
    assert resp.retry_count == 0
    assert resp.stages_executed == ["assess_intent", "llm_clarify"]


def test_post_chat_react_answers_after_search(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings(llm_ranker_enabled=True))
    monkeypatch.setattr(
        chat,
        "assess_user_intent_with_llm",
        lambda *_args, **_kwargs: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMIntentAssessment"]
        ).LLMIntentAssessment(
            is_clear=True,
            rewritten_query="居民身份证换领办理",
            reply="",
            missing_info=[],
            reason="已明确到事项阶段",
        ),
    )
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [
            _service(2, "居民身份证换领", 0.80),
            _service(1, "居民身份证申领", 0.79),
        ],
    )
    monkeypatch.setattr(
        chat,
        "plan_next_step_with_llm",
        lambda *_args, **_kwargs: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMNextStepDecision"]
        ).LLMNextStepDecision(
            action="answer",
            best_id=2,
            reply="",
            rewritten_query="",
            cited_ids=[2],
            reason="候选足够回答",
        ),
    )
    monkeypatch.setattr(chat.gr, "find_service_by_id", lambda *_args, **_kwargs: _service(2, "居民身份证换领", 1.0))
    monkeypatch.setattr(chat.gr, "load_materials", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat.gr, "load_processes", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat, "generate_service_answer_with_llm", lambda *_args, **_kwargs: "可以办理居民身份证换领。")

    resp = chat.post_chat(ChatRequest(message="身份证到期了怎么办"), pool=_FakePool())

    assert resp.kind == "answer"
    assert resp.session_state == "answer"
    assert resp.reply == "可以办理居民身份证换领。"
    assert resp.sources[0].title == "居民身份证换领"
    assert resp.stages_executed == ["assess_intent", "retrieve_vector", "llm_plan", "load_detail", "llm_answer"]


def test_post_chat_react_retries_then_fallback(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings(llm_ranker_enabled=True, conversation_max_retries=1))
    monkeypatch.setattr(
        chat,
        "assess_user_intent_with_llm",
        lambda *_args, **_kwargs: __import__(
            "govflow.services.llm_ranker", fromlist=["LLMIntentAssessment"]
        ).LLMIntentAssessment(
            is_clear=True,
            rewritten_query="社保办理",
            reply="",
            missing_info=[],
            reason="可先检索",
        ),
    )
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat.gr, "find_topk_services_vector", lambda *_args, **_kwargs: [_service(1, "社会保险登记", 0.70)])

    decisions = iter(
        [
            __import__("govflow.services.llm_ranker", fromlist=["LLMNextStepDecision"]).LLMNextStepDecision(
                action="retry_search",
                best_id=None,
                reply="",
                rewritten_query="企业社会保险登记办理",
                cited_ids=[],
                reason="当前问题太宽泛",
            ),
            __import__("govflow.services.llm_ranker", fromlist=["LLMNextStepDecision"]).LLMNextStepDecision(
                action="fallback",
                best_id=None,
                reply="我暂时无法准确定位到唯一事项，原因是当前候选仍然过于宽泛。",
                rewritten_query="",
                cited_ids=[],
                reason="多次重试后仍不确定",
            ),
        ]
    )
    monkeypatch.setattr(chat, "plan_next_step_with_llm", lambda *_args, **_kwargs: next(decisions))
    monkeypatch.setattr(chat, "explain_fallback_with_llm", lambda *_args, **_kwargs: "我暂时无法准确定位到唯一事项，原因是当前候选仍然过于宽泛。")

    resp = chat.post_chat(ChatRequest(message="社保怎么办"), pool=_FakePool())

    assert resp.kind == "fallback"
    assert resp.session_state == "fallback"
    assert resp.retry_count == 1
    assert "原因是当前候选仍然过于宽泛" in resp.reply
    assert resp.stages_executed == [
        "assess_intent",
        "retrieve_vector",
        "llm_plan",
        "rewrite_query",
        "retrieve_vector",
        "llm_plan",
        "llm_fallback",
    ]


def test_search_services_returns_exact_match(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings())
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: None)
    monkeypatch.setattr(
        chat.gr,
        "find_service_by_exact_name",
        lambda *_args, **_kwargs: _service(8, "居民身份证申领", 1.0),
    )

    resp = chat.search_services(
        SearchServicesRequest(query="居民身份证申领"),
        pool=_FakePool(),
    )

    assert resp.search_mode == "exact"
    assert resp.suggested_action == "answer"
    assert resp.exact_match_hit is True
    assert resp.candidates[0].service_name == "居民身份证申领"
    assert resp.stages_executed == ["retrieve_exact_name"]


def test_search_services_returns_clarify_hint(monkeypatch) -> None:
    monkeypatch.setattr(chat, "get_settings", lambda: _settings())
    monkeypatch.setattr(chat, "embed_query", lambda _msg, _settings: [0.0] * EMBEDDING_DIM)
    monkeypatch.setattr(chat.gr, "find_service_by_exact_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        chat.gr,
        "find_topk_services_vector",
        lambda *_args, **_kwargs: [
            _service(1, "居民身份证申领", 0.80),
            _service(2, "居民身份证换领", 0.79),
            _service(3, "临时居民身份证申领", 0.78),
        ],
    )

    resp = chat.search_services(
        SearchServicesRequest(query="我要办身份证", top_k=3),
        pool=_FakePool(),
    )

    assert resp.search_mode == "vector"
    assert resp.suggested_action == "clarify"
    assert resp.clarify_hint is not None
    assert len(resp.candidates) == 3
    assert resp.stages_executed == ["retrieve_vector", "decide_retrieval"]


def test_get_service_detail_returns_requested_sections(monkeypatch) -> None:
    monkeypatch.setattr(chat.gr, "find_service_by_id", lambda *_args, **_kwargs: _service(11, "企业社保登记", 1.0))
    monkeypatch.setattr(
        chat.gr,
        "load_materials",
        lambda *_args, **_kwargs: [
            MaterialRow(
                material_name="营业执照",
                is_required=True,
                material_form="电子",
                original_num=0,
                copy_num=0,
                note="原件扫描件",
            )
        ],
    )
    monkeypatch.setattr(
        chat.gr,
        "load_processes",
        lambda *_args, **_kwargs: [
            ProcessRow(step_name="提交申请", step_desc="线上提交", sort=1),
        ],
    )

    resp = chat.get_service_detail(
        GetServiceDetailRequest(service_id=11, include=["basic", "materials"]),
        pool=_FakePool(),
    )

    assert resp.service_id == 11
    assert resp.basic is not None
    assert resp.basic.service_name == "企业社保登记"
    assert len(resp.materials) == 1
    assert resp.processes == []
    assert resp.included_sections == ["basic", "materials"]
    assert resp.stages_executed == ["load_basic", "load_materials"]
