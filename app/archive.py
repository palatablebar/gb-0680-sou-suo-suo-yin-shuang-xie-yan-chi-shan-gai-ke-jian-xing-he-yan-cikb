import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    # 原有列位置保持不变，契约版本作为附加列追加在末尾。
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence","schema"])
    meta=run["manifest"];contract=run.get("contract",{})
    for row in run["stages"][-1]["rows"]:
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(row,ensure_ascii=False),row.get("_schema","")])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False),row.get("_schema","")])
    # 契约裁决本身也入证据：隔离段保留原始行，差异结论与页面读同一份批次。
    for conflict in contract.get("conflicts",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"schema_conflict",json.dumps(conflict.get("segment")),conflict.get("reason",""),json.dumps(conflict,ensure_ascii=False),""])
    return "﻿"+stream.getvalue()
