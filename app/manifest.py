import hashlib,json,time
from datetime import datetime,timezone
from app.config import RULE_VERSION
def digest(raw,params=None,scope=""):
    # scope 为空时保持旧格式批次身份不变；新格式把契约定义摘要并入身份。
    material=raw+json.dumps(params or {},sort_keys=True,ensure_ascii=False).encode()+RULE_VERSION.encode()+scope.encode()
    return hashlib.sha256(material).hexdigest()
def manifest(raw,params,started,scope=""):
    return {"input_sha256":hashlib.sha256(raw).hexdigest(),"rule_version":RULE_VERSION,"contract_scope":scope,"parameters":params,"generated_at":datetime.now(timezone.utc).isoformat(),"elapsed_ms":round((time.monotonic()-started)*1000,2)}
