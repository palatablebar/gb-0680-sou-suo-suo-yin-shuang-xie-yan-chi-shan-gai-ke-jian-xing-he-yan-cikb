# 深度登记 搜索索引双写延迟与删改可见性核验

规模：中型。使用者：搜索数据同步值班工程师。核心规则：按源版本重建目标可见状态，删除墓碑拦截迟到旧写入；延迟与缺失分开定责。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 双端采信 | 查看并运行双端采信 | `/api/streams` | `app/modules/m1_streams/rules.py` | `tests/test_m1.py` |
| M2 字段契约 | 查看并运行字段契约 | `/api/schema` | `app/modules/m2_schema/rules.py`、`app/schemas.py` | `tests/test_m2.py`、`tests/test_m8.py` |
| M3 版本裁决 | 查看并运行版本裁决 | `/api/versions` | `app/modules/m3_versions/rules.py` | `tests/test_m3.py` |
| M4 可见性重建 | 查看并运行可见性重建 | `/api/visibility` | `app/modules/m4_visibility/rules.py` | `tests/test_m4.py` |
| M5 延迟闸门 | 查看并运行延迟闸门 | `/api/latency` | `app/modules/m5_latency/rules.py` | `tests/test_m5.py` |
| M6 双写对账 | 查看并运行双写对账 | `/api/parity` | `app/modules/m6_parity/rules.py` | `tests/test_m6.py` |
| M7 回补归档 | 查看并运行回补归档 | `/api/backfills` | `app/modules/m7_backfills/rules.py` | `tests/test_m7.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | 旧编码 | 默认解码失败 | 回退GB18030 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_legacy_encoding_real_sample` |
| TRAP-02 | BOM | 首列名多字符 | utf-8-sig | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bom_real_sample` |
| TRAP-03 | 带引号换行 | 拆成两条 | csv逻辑行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_quoted_newline_is_one_record` |
| TRAP-05 | 列数不匹配 | 静默错列 | 隔离原行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_bad_columns_real_sample` |
| TRAP-08 | 前导零ID | 编码变形 | 全程字符串 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_identifier_preserved_real_sample` |
| TRAP-14 | 重复键冲突 | 后写覆盖 | 保留首条并隔离冲突行 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_duplicate_conflict_real_sample` |
| TRAP-18 | 空态三态 | 一律成功 | 分别错误码 | `app/modules/m1_streams/rules.py` | `tests/test_m1.py::test_three_empty_states` |
| TRAP-26 | 旧版本提交 | 覆盖新结果 | 版本条件更新 | `app/store.py` | `tests/test_e2e.py::test_stale_review_409` |
| TRAP-06 | 全角版本 | 解析失败 | Decimal归一 | `app/values.py` | `tests/test_m2.py::test_fullwidth_version` |
| TRAP-07 | 缺版本 | 当零处理 | 空值隔离 | `app/values.py` | `tests/test_m2.py::test_real_sentinel_isolated` |
| TRAP-09 | 超大版本 | JSON精度损失 | 文本序列化 | `app/values.py` | `tests/test_m2.py::test_large_version_precise` |
| TRAP-13 | 删除后迟到旧写 | 文档复活 | 最大版本墓碑 | `app/modules/m3_versions/rules.py` | `tests/test_m3.py::test_tombstone_beats_late_old_write` |
| TRAP-23 | 延迟阈值边界 | 多判延迟 | 等于阈值通过 | `app/modules/m5_latency/rules.py` | `tests/test_m5.py::test_threshold_equal_pass` |
| TRAP-27 | 新格式列位置漂移 | 按列序号取值，新旧段一起错位 | 全程按表头名字对齐 | `app/modules/m1_streams/rules.py` | `tests/test_m8.py::test_columns_align_by_name_not_position` |
| TRAP-28 | 旧批被新定义重解 | 统一用最新列集合解释 | 每段按自身表头裁决，旧段永远 v1 | `app/schemas.py`、`app/modules/m1_streams/rules.py` | `tests/test_m8.py::test_mixed_old_and_new_segments_both_admitted` |
| TRAP-29 | 未声明字段混入 | 多出的列静默接受或丢列 | 整段隔离并保留原始行 | `app/schemas.py` | `tests/test_m8.py::test_undeclared_field_isolates_whole_segment_and_keeps_raw_row` |
| TRAP-30 | 声明与表头不符 | 直接采信声明 | 冲突批隔离，保留原行 | `app/schemas.py` | `tests/test_m8.py::test_declared_v1_with_extended_header_is_isolated` |
| TRAP-31 | 声明新版把旧段停住 | 整批拒绝或整批按新解 | 旧段仍按 v1 原义读入，回补不停 | `app/schemas.py` | `tests/test_m8.py::test_declared_v2_lets_legacy_segment_through_unchanged` |
| TRAP-32 | 字段定义变更后重跑旧批 | 复用旧批次，结论被改写 | 契约摘要并入新格式批次身份 | `app/schemas.py`、`app/manifest.py`、`app/store.py` | `tests/test_m8.py::test_contract_is_part_of_batch_identity_when_extended` |
| TRAP-33 | 页面与差异各算一遍 | 各阶段自行推契约 | 裁决只在 M1 落一次，后续沿用同一份 | `app/pipeline.py`、`app/modules/m6_parity/rules.py` | `tests/test_m8.py::test_schema_verdict_matches_between_page_and_diff` |

## 对账规则

输入原始逻辑行=最终采纳来源行+隔离来源行+重复行+空白行+分段表头。契约冲突段的整段原始行计入隔离来源行，不参与派生记录。派生记录用_sources保存完整来源，因此分组不丢行。业务预期合计与上游申报合计之差等于逐行差异之和。结果按输入摘要、规则版本、参数及本批实际用到的契约定义摘要产生唯一批次，事务写入；同源同定义重跑只复用已有批次，既不新增记录也不改结论。

## 已知不覆盖

4MB以上文件需预先按业务键分批；不模拟生产支付与外部回调。人工复核只变更批次状态，不改写原始记录。可检索属性登记在 `app/schemas.py`，新增属性需先登记（否则相关批次整段隔离）；同一批次内新旧格式按表头分段共存，未实现跨批次的定义迁移。
