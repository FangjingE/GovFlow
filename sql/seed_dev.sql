-- 开发用示例数据（可选）。零向量占位满足 embedding 非空；默认「文本相似度」检索主要依赖 service_name / vector_text。

INSERT INTO gov_service (
    service_name, department, service_object, promise_days, legal_days, on_site_times,
    is_charge, accept_condition, general_scope, handle_form, item_type,
    handle_address, handle_time, consult_way, complaint_way, query_way, status
)
SELECT * FROM (VALUES (
    '居民身份证申领',
    '公安局户政窗口',
    '自然人',
    5,
    60,
    1,
    false,
    '年满16周岁中国公民，持户口簿等材料。',
    '全市通办',
    '窗口办理,网上办理',
    '即办件',
    '市政务服务中心2楼公安专区',
    '工作日 9:00-12:00, 14:00-17:00',
    '电话：0771-12345',
    '12345热线',
    '广西数字政务一体化平台',
    true
)) AS v(
    service_name, department, service_object, promise_days, legal_days, on_site_times,
    is_charge, accept_condition, general_scope, handle_form, item_type,
    handle_address, handle_time, consult_way, complaint_way, query_way, status
)
WHERE NOT EXISTS (SELECT 1 FROM gov_service g WHERE g.service_name = v.service_name);

INSERT INTO service_embedding (service_id, service_name, vector_text, embedding)
SELECT
    gs.id,
    gs.service_name,
    gs.service_name || E'\n' || COALESCE(gs.accept_condition, ''),
    (('[' || repeat('0,', 767) || '0]')::vector)
FROM gov_service gs
WHERE gs.service_name = '居民身份证申领'
  AND NOT EXISTS (SELECT 1 FROM service_embedding se WHERE se.service_id = gs.id);

INSERT INTO service_material (service_id, material_name, is_required, material_form, original_num, copy_num)
SELECT gs.id, '居民户口簿原件', true, '纸质', 1, 0
FROM gov_service gs
WHERE gs.service_name = '居民身份证申领'
  AND NOT EXISTS (SELECT 1 FROM service_material m WHERE m.service_id = gs.id AND m.material_name = '居民户口簿原件');

INSERT INTO service_process (service_id, step_name, step_desc, sort)
SELECT gs.id, '取号受理', '到窗口提交材料并核对信息。', 1
FROM gov_service gs
WHERE gs.service_name = '居民身份证申领'
  AND NOT EXISTS (SELECT 1 FROM service_process p WHERE p.service_id = gs.id AND p.sort = 1);

INSERT INTO service_process (service_id, step_name, step_desc, sort)
SELECT gs.id, '制证发放', '制证完成后凭回执领取。', 2
FROM gov_service gs
WHERE gs.service_name = '居民身份证申领'
  AND NOT EXISTS (SELECT 1 FROM service_process p WHERE p.service_id = gs.id AND p.sort = 2);
