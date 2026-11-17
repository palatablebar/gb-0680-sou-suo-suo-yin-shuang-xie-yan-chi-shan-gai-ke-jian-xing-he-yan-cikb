from flask import Blueprint,request,jsonify
from app.errors import DomainError
from app.pipeline import stage_preview
from app import schemas
bp=Blueprint("schema",__name__)
@bp.route("/api/schema",methods=["GET","POST"])
def preview():
    payload=request.get_json(silent=True) if request.method=="POST" else {}
    if payload is None or not isinstance(payload,dict): raise DomainError("BAD_BODY","请求需要对象")
    result=stage_preview(1,payload)
    # GET 除当前批次结论外，还给出登记表，便于对照"哪些属性已声明"。
    if request.method=="GET" or "rows" not in payload and "csv" not in payload and "sample" not in payload:
        result=dict(result);result["registry"]=schemas.descriptor()
    return jsonify(result)
