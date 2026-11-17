import hashlib,json
from app.errors import DomainError
from app.reasons import sources
def evaluate(rows,context):
    stages=[v for v in context.values() if isinstance(v,dict) and "metrics" in v]
    balances=[s["metrics"]["balanced"] for s in stages if "balanced" in s["metrics"]]
    if balances and not all(balances): raise DomainError("UNBALANCED","来源行未对平，不能归档")
    ids=[str(r.get("doc_id",r.get("_line",""))) for r in rows]
    if len(ids)!=len(set(ids)): raise DomainError("ARCHIVE_DUPLICATE","归档业务键重复")
    # 契约裁决是批次能否进入正式结果的唯一闸门：有段未准入只留证据，
    # 采纳行照常回补（避免一段冲突就停住整日回补），整批隔离才算不就绪。
    contract=context.get("contract",{}) or {}
    admission=contract.get("admission","FORMAL")
    encoded=json.dumps(rows,ensure_ascii=False,sort_keys=True,default=str).encode()
    return {"rows":rows,"quarantine":[],"metrics":{"records":len(rows),"source_lines":len(set(x for row in rows for x in sources(row))),"sha256":hashlib.sha256(encoded).hexdigest(),
            "ready":admission!="QUARANTINED","admission":admission,"contract_conflicts":len(contract.get("conflicts",[])),
            "formats":"+".join(contract.get("used_versions",[])) or "—","differences":sum(r.get("status")=="差异" for r in rows)}}
