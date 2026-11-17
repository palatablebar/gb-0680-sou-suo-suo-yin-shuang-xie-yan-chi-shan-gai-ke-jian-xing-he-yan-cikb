# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离；具有字段含义的阶段还返回contract。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV，隔离行与契约冲突段都保留原始行。

`GET /api/schema` 额外返回 `registry`：已登记的契约版本、字段、可检索属性、登记摘要，以及准入错误码。

## 契约裁决

- 批级结论在 `contract`：`admission`（FORMAL / PARTIAL / QUARANTINED）、`declared_version`、`used_versions`、`formal_batches`、`quarantined_batches`、`attributes`、`conflicts`、`run_scope`。
- M1 返回 `segments`：每个表头分段的独立裁决（版本、理由、是否准入）。
- M2、M6、M7 返回的 `contract` 与 M1 是同一份，页面、差异结果和导出都读它。
- 批次身份：`run_id` 由输入摘要、规则版本、参数组成；涉及扩展属性时并入本批实际用到的契约版本定义摘要，定义变更后重跑得到新批次。
- `POST /api/runs` 的 `parameters.schema_version` 可声明本批契约版本（`v1`/`v2`）；声明未登记版本时该批整段隔离并保留原始行，而不是拒绝写入。
- M7 的 `ready` 在 `admission=QUARANTINED` 时为假；`PARTIAL` 批次中的采纳行照常回补。