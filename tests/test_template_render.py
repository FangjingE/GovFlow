from govflow.services.gov_types import GovServiceRow, MaterialRow, ProcessRow
from govflow.services.template_render import render_service_answer


def test_render_uses_architecture_shape() -> None:
    svc = GovServiceRow(
        id=1,
        service_name="测试事项",
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
