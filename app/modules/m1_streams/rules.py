import csv,io
from app.errors import DomainError
from app.reasons import reject
from app import schemas
def decode(raw):
    for encoding in ("utf-8-sig","gb18030"):
        try: return raw.decode(encoding),encoding
        except UnicodeDecodeError: continue
    raise DomainError("ENCODING","无法识别文件编码")
def evaluate(raw,context=None):
    # 本批声明只读一次；未声明则由各段表头自行推导，旧段永远按旧定义解释。
    claimed=schemas.claim_from_parameters((context or {}).get("parameters",{}))
    text,encoding=decode(raw)
    if not text: raise DomainError("EMPTY_FILE","文件为空")
    if not text.strip(): raise DomainError("BLANK_ONLY","全部为空行")
    stream=csv.reader(io.StringIO(text,newline=""));first=next(stream,None)
    if first is None or not schemas.is_header(first): raise DomainError("BAD_HEADER","表头不匹配")
    batch=schemas.adjudicate(first,claimed)
    if batch["reason"]=="UNRECOGNIZED_HEADER": raise DomainError("BAD_HEADER","表头不匹配")
    segments=[batch];names=batch["header"]
    rows=[];bad=[];seen={};duplicate=blank=repeated=enriched=count=0
    try:
        for cells in stream:
            count+=1;line=stream.line_num
            if not cells or not any(c.strip() for c in cells): blank+=1;continue
            if schemas.is_header(cells):
                # 新旧导出会分段回放：每段按自己的表头重新裁决，旧段不会被新定义重解。
                repeated+=1;batch=schemas.adjudicate(cells,claimed);segments.append(batch);names=batch["header"];continue
            row={"_line":line,"_sources":[line],"_raw":[x for x in cells],"_batch":len(segments)-1}
            if batch["status"]!="ACCEPTED":
                # 整段隔离时保留原始行，不让它按另一版定义被硬解释进正式结果。
                bad.append(reject(row,batch["reason"],batch["detail"]));continue
            if len(cells)>len(names): bad.append(reject(row,"BAD_COLUMNS","列数不匹配"));continue
            cells=list(cells);supplied=len(cells)
            if supplied<len(names):
                absent=names[supplied:]
                if any(name in batch["required_fields"] for name in absent):
                    bad.append(reject(row,"BAD_COLUMNS","列数不匹配"));continue
                cells+=[""]*(len(names)-supplied)
            # 先按表头名字对齐再取业务键：新段插入属性列不会让旧段错位。
            # _fields 只记本行实际给出的列，截断的尾部属性视为"未提供"而非空值。
            normalized=[x.strip() for x in cells]
            values=dict(zip(names,normalized))
            row["_schema"]=batch["schema_id"]
            row["_fields"]=list(names[:supplied])
            row.update(values)
            if not values.get("event_id"): bad.append(reject(row,"EMPTY_VALUE","业务键为空"));continue
            key=values["event_id"]
            if key in seen:
                # 同键在新旧导出中一起回放：只比共同声明过的字段，旧导出不会因
                # 新导出多出属性列而被判成值冲突；共同字段冲突才隔离并保留原值。
                merged=schemas.replay(seen[key],row)
                if merged=="conflict": bad.append(reject(row,"DUPLICATE_CONFLICT","同键不同值"))
                else:
                    duplicate+=1;enriched+=merged=="enrich"
                continue
            seen[key]=row;rows.append(row)
    except csv.Error: raise DomainError("BAD_CSV","引号未闭合或文件损坏")
    if count==0: raise DomainError("HEADER_ONLY","仅有表头")
    if not rows and not bad: raise DomainError("BLANK_ONLY","全部为空行")
    used=sorted({row["_schema"] for row in rows},key=lambda item:schemas.SCHEMAS[item]["version"])
    formal=[segment for segment in segments if segment["status"]=="ACCEPTED"]
    conflicted=len(segments)-len(formal)
    contract={"fingerprint":schemas.registry_fingerprint(),"declared_version":claimed,
              "used_versions":used,"formal_batches":len(formal),"quarantined_batches":conflicted,
              "run_scope":schemas.run_scope(used,conflicted>0),
              "admission":"FORMAL" if not conflicted else ("PARTIAL" if formal else "QUARANTINED"),
              "attributes":sorted({name for row in rows for name in schemas.attributes(row)}),
              "conflicts":[{"segment":index,"reason":segment["reason"],"detail":segment["detail"]} for index,segment in enumerate(segments) if segment["status"]!="ACCEPTED"]}
    metrics={"input":count,"accepted":len(rows),"quarantine":len(bad),"duplicate":duplicate,"blank":blank,"repeated_headers":repeated,"encoding":encoding,
             "schema_versions":"+".join(used) or "—","schema_batches":len(segments),"schema_quarantined_batches":conflicted,
             "schema_attributes":len(contract["attributes"]),"schema_conflicts":len(contract["conflicts"]),
             "schema_enriched":enriched}
    return {"rows":rows,"quarantine":bad,"metrics":metrics,"contract":contract,"segments":segments}
