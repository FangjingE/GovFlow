from govflow.services.gov_types import GovServiceRow, MaterialRow, ProcessRow
from govflow.services.template_render import (
    render_clarify_prompt,
    render_fallback_prompt,
    render_service_answer,
)


def test_render_uses_architecture_shape() -> None:
    svc = GovServiceRow(
        id=1,
        service_name="测试事项",
        source_url=None,
        department="测试局",
        service_object="自然人",
        promise_days=1,
        legal_days=10,
        on_site_times=0,
        is_charge=False,
        accept_condition="条件说明",
        general_scope="全市",
        handle_form="窗口办理",
        item_type="即办件",
        handle_address="政务大厅",
        handle_time="工作日",
        consult_way="12345",
        complaint_way="12345",
        query_way="网办平台",
    )
    mats = [MaterialRow("材料A", True, "纸质", 1, 0, None)]
    procs = [ProcessRow("第一步", "说明", 1)]
    out = render_service_answer(service=svc, materials=mats, processes=procs, query="怎么办理")
    assert "事项名称：测试事项" in out
    assert "【申请材料】" in out
    assert "材料A" in out
    assert "【办理流程】" in out
    assert "用户问题：怎么办理" in out


def test_render_clarify_prompt_lists_options() -> None:
    candidates = [
        GovServiceRow(
            id=1,
            service_name="居民身份证申领",
            source_url=None,
            department="公安局",
            service_object="自然人",
            promise_days=None,
            legal_days=None,
            on_site_times=None,
            is_charge=None,
            accept_condition=None,
            general_scope=None,
            handle_form=None,
            item_type=None,
            handle_address=None,
            handle_time=None,
            consult_way=None,
            complaint_way=None,
            query_way=None,
            match_score=0.81,
        ),
        GovServiceRow(
            id=2,
            service_name="居民身份证换领",
            source_url=None,
            department="公安局",
            service_object="自然人",
            promise_days=None,
            legal_days=None,
            on_site_times=None,
            is_charge=None,
            accept_condition=None,
            general_scope=None,
            handle_form=None,
            item_type=None,
            handle_address=None,
            handle_time=None,
            consult_way=None,
            complaint_way=None,
            query_way=None,
            match_score=0.8,
        ),
    ]
    reply, question, option_labels = render_clarify_prompt(candidates=candidates, hotline="12345")
    assert "你要查询的是否是以下事项之一？" in reply
    assert "1. 居民身份证申领" in reply
    assert "2. 居民身份证换领" in reply
    assert question.startswith("我找到了几条相近的事项")
    assert option_labels == ["居民身份证申领", "居民身份证换领"]


def test_render_fallback_prompt_shows_reference_candidates() -> None:
    candidates = [
        GovServiceRow(
            id=3,
            service_name="社会保险登记",
            source_url=None,
            department="人社局",
            service_object="企业法人",
            promise_days=None,
            legal_days=None,
            on_site_times=None,
            is_charge=None,
            accept_condition=None,
            general_scope=None,
            handle_form=None,
            item_type=None,
            handle_address=None,
            handle_time=None,
            consult_way=None,
            complaint_way=None,
            query_way=None,
            match_score=0.61,
        )
    ]
    out = render_fallback_prompt(candidates=candidates, hotline="12345")
    assert "未在事项库中匹配到足够相关的一条政务事项。" in out
    assert "社会保险登记" in out
    assert "咨询电话：12345" in out
