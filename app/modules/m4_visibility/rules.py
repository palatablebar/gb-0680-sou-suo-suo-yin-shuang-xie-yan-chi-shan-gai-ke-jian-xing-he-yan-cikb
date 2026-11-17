from collections import defaultdict
from app.reasons import sources
from app.values import number
from app import schemas
def evaluate(rows,context):
    grouped=defaultdict(dict)
    for row in rows:grouped[row["doc_id"]][row["side"]]=row
    out=[]
    for doc,sides in sorted(grouped.items()):
        source=sides.get("source");target=sides.get("index");lines=[n for r in sides.values() for n in sources(r)]
        if source is None:state="ORPHAN_INDEX"
        elif target is None:state="MISSING_INDEX" if source["op"]=="upsert" else "DELETE_NOT_CONFIRMED"
        elif number(target["version"])>number(source["version"]):state="INDEX_AHEAD"
        elif number(target["version"])<number(source["version"]):state="STALE_INDEX"
        elif source["op"]!=target["op"]:state="OP_MISMATCH"
        # 与版本裁决同一份内容定义：旧导出没有的扩展属性不参与比较，
        # 新导出之间声明过的属性不同才算内容差异。
        elif source["op"]=="upsert" and not schemas.compatible(source,target):state="CONTENT_MISMATCH"
        else:state="CONSISTENT"
        anchor=source or target
        out.append({**anchor,"_sources":lines,"source_version":source["version"] if source else "—","index_version":target["version"] if target else "—","source_op":source["op"] if source else "—","index_op":target["op"] if target else "—","visible_at":target.get("visible_at") if target else None,"visibility_state":state,"expected":"1","reported":"1" if state=="CONSISTENT" else "0","document_equal":state=="CONSISTENT"})
    return {"rows":out,"quarantine":[],"metrics":{"documents":len(out),"consistent":sum(r["visibility_state"]=="CONSISTENT" for r in out),"missing":sum(r["visibility_state"] in {"MISSING_INDEX","DELETE_NOT_CONFIRMED"} for r in out)}}
