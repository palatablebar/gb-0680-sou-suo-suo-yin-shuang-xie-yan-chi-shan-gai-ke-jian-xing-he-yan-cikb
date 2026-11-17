import time
from app.config import ROOT,MODULES
from app.errors import DomainError
from app.values import scalar
from app.manifest import digest,manifest
from app import store
from app.modules.m1_streams.rules import evaluate as stage1
from app.modules.m2_schema.rules import evaluate as stage2
from app.modules.m3_versions.rules import evaluate as stage3
from app.modules.m4_visibility.rules import evaluate as stage4
from app.modules.m5_latency.rules import evaluate as stage5
from app.modules.m6_parity.rules import evaluate as stage6
from app.modules.m7_backfills.rules import evaluate as stage7
STAGES=[stage1,stage2,stage3,stage4,stage5,stage6,stage7]
def load_sample(name):
    if name not in {"dirty.csv","clean.csv","legacy.csv"}: raise DomainError("BAD_SAMPLE","样例不存在",404)
    return (ROOT/"sample_data"/name).read_bytes()
def calculate(raw,params=None,stop=6):
    params=params or {};started=time.monotonic();context={"parameters":params,"raw":raw,"quarantine":[]};stages=[];rows=[];scope=""
    for index,stage in enumerate(STAGES[:stop+1]):
        result=stage(raw if index==0 else rows,context)
        result=scalar(result);rows=result["rows"]
        context["quarantine"].extend(result.get("quarantine",[]))
        if index==0:
            context["intake"]=result["metrics"]
            context["contract"]=result.get("contract",{})
            # 契约裁决在 M1 落地一次；批次身份与清单都读这一份，页面与导出不会各说各话。
            scope=result.get("contract",{}).get("run_scope","")
        result["cumulative_quarantine"]=list(context["quarantine"])
        context[MODULES[index][0]]=result
        stages.append(result)
    manifest_data=manifest(raw,params,started,scope)
    return {"run_id":digest(raw,params,scope)[:20],"stages":stages,"manifest":manifest_data,"parameters":params,"contract":context.get("contract",{})}
def execute(raw,params=None):
    result=calculate(raw,params);return store.save(result["run_id"],result)
def stage_preview(index,payload):
    if "rows" in payload and index>0:
        if not isinstance(payload["rows"],list) or any(not isinstance(row,dict) for row in payload["rows"]): raise DomainError("BAD_ROWS","记录需要对象列表")
        if not isinstance(payload.get("context",{}),dict): raise DomainError("BAD_CONTEXT","上下文需要对象")
        return scalar(STAGES[index](payload["rows"],payload.get("context",{"parameters":{},"quarantine":[]})))
    raw=payload.get("csv")
    raw=raw.encode() if isinstance(raw,str) else load_sample(payload.get("sample","dirty.csv"))
    return calculate(raw,payload.get("parameters",{}),index)["stages"][-1]
