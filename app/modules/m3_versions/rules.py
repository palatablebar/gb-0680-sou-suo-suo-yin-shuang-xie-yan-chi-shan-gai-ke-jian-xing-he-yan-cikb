from collections import defaultdict
from app.reasons import reject,sources
from app.values import number
from app import schemas
def evaluate(rows,context):
    grouped=defaultdict(list);good=[];bad=[]
    for row in rows:grouped[(row["doc_id"],row["side"],row["version"])].append(row)
    by_doc=defaultdict(list);blocked=set()
    for key,events in sorted(grouped.items()):
        ordered=sorted(events,key=lambda e:e["event_id"])
        # 同内容合并来源；旧导出缺失的扩展属性不算内容冲突，两边都声明过的才算。
        if any(not schemas.compatible(ordered[0],other) for other in ordered[1:]):
            bad.extend(reject(e,"SAME_VERSION_CONFLICT","同文档同版本内容冲突") for e in events);blocked.add((key[0],key[1]));continue
        merged={**ordered[0],"_sources":[n for e in events for n in sources(e)],"version_duplicate_count":len(events)-1}
        for event in ordered[1:]: schemas.merge_attributes(merged,event)
        by_doc[(key[0],key[1])].append(merged)
    for (doc,side),events in sorted(by_doc.items()):
        if (doc,side) in blocked:
            bad.extend(reject(e,"UNRESOLVED_VERSION","当前文档存在版本冲突") for e in events);continue
        winner=max(events,key=lambda e:number(e["version"]))
        good.append({**winner,"_sources":[n for e in events for n in sources(e)],"superseded_versions":sorted([e["version"] for e in events if e is not winner],key=number),"tombstone":winner["op"]=="delete"})
    return {"rows":good,"quarantine":bad,"metrics":{"states":len(good),"tombstones":sum(r["tombstone"] for r in good),"conflict_rows":len(bad)}}
