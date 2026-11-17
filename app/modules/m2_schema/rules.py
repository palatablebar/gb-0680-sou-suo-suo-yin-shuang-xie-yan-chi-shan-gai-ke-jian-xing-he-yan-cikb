import json
from app.values import number,instant
from app.reasons import reject
from app.errors import DomainError
from app import schemas
ALIASES={"新增":"upsert","修改":"upsert","upsert":"upsert","删除":"delete","delete":"delete"}
def contract_for(rows,upstream):
    """配置结论：上游 M1 已按段裁决过就沿用同一份；直接传 rows 时此处补裁决，
    保证接口、页面与差异结果读的是同一条判定。"""
    if upstream and upstream.get("used_versions") is not None:return dict(upstream)
    conflicts=[]
    for index,row in enumerate(rows):
        problem=schemas.row_conflict(row)
        if problem:conflicts.append({"segment":index,"reason":problem[0],"detail":problem[1]})
    used=sorted({schemas.infer(row) for row in rows if not schemas.row_conflict(row)},key=lambda item:schemas.SCHEMAS[item]["version"])
    return {"fingerprint":schemas.registry_fingerprint(),"declared_version":None,"used_versions":used,
            "formal_batches":sum(1 for row in rows if not schemas.row_conflict(row)),"quarantined_batches":len(conflicts),
            "run_scope":schemas.run_scope(used,bool(conflicts)),
            "admission":"FORMAL" if not conflicts else ("PARTIAL" if len(conflicts)<len(rows) else "QUARANTINED"),
            "attributes":sorted({name for row in rows for name in schemas.attributes(row)}),"conflicts":conflicts}
def evaluate(rows,context):
    # 与 M1 共用同一份登记表：同一条行在这里得出同一版契约结论。
    good=[];bad=[];versions={};attributes=set()
    for row in rows:
        conflict=schemas.row_conflict(row)
        if conflict:bad.append(reject(row,conflict[0],conflict[1]));continue
        try:
            version=number(row["version"]);op=ALIASES.get(row["op"])
            if version<1 or version!=version.to_integral_value():raise DomainError("BAD_VERSION","版本必须为正整数")
            if op is None or row["side"] not in {"source","index"}:raise DomainError("BAD_OPERATION","操作或数据端无效")
            source=instant(row["source_time"]);visible=instant(row["visible_time"]) if row["visible_time"] not in {"","-","NULL"} else None
            if visible and visible<source:raise DomainError("NEGATIVE_LATENCY","可见时间早于源事件")
            payload=json.loads(row["payload"]) if op=="upsert" else None
            if op=="upsert" and not isinstance(payload,dict):raise DomainError("BAD_PAYLOAD","文档需要JSON对象")
            profile=schemas.infer(row);versions[profile]=versions.get(profile,0)+1
            extra=schemas.attributes(row);attributes.update(extra)
            good.append({**row,"version":format(version.to_integral_value(),"f"),"op":op,"source_at":source.isoformat(),"visible_at":visible.isoformat() if visible else None,"document":payload,"reported":str(number(row["reported"])),"_schema":profile,"attributes":extra})
        except (DomainError,KeyError,ValueError) as e:bad.append(reject(row,getattr(e,"code","BAD_PAYLOAD"),str(e)))
    return {"rows":good,"quarantine":bad,"metrics":{"accepted":len(good),"deletes":sum(r["op"]=="delete" for r in good),
            "schema_versions":"+".join(sorted(versions,key=lambda item:schemas.SCHEMAS[item]["version"])) or "—",
            "schema_attributes":len(attributes),"schema_rejected":len(bad)},"contract":contract_for(rows,context.get("contract"))}
