"""字段契约登记与批次准入裁决。

数据源在分批增加可检索属性，新旧导出会一起回放。这里把"这一批按哪一版
定义解释"变成一次显式、可复现的裁决：

* 旧格式（表头恰好是原始列）永远按 v1 解释，原义与旧批次身份都不变；
* 新格式只接收已登记的可检索属性，且按表头名字对齐，不依赖列位置，
  因此旧段行不会因为新段插入了属性而整体错位；
* 表头出现未登记字段、缺必填原始列、重复列，或声明版本与表头推导不一致
  时，整段隔离并保留原始行，不进入正式结果，也不回落成旧定义硬解释；
* 裁决只发生在这里。M1 用它对齐，M2 用它出结论，页面与差异结果读同一份
  已保存批次，因此判定一致；新格式批次身份绑定当前登记摘要，定义变更后
  重跑会得到新的批次身份，不会改写已封存的旧结论。
"""

import hashlib
import json

from app.config import COLUMNS
from app.errors import DomainError
from app.values import SENTINELS

LEGACY_FIELDS = tuple(COLUMNS)
SEARCHABLE_ATTRIBUTES = ("category", "tags")
SCHEMAS = {
    "v1": {"id": "v1", "version": 1, "label": "原始固定字段", "fields": LEGACY_FIELDS, "required": LEGACY_FIELDS, "searchable": ()},
    "v2": {"id": "v2", "version": 2, "label": "可检索属性扩展", "fields": LEGACY_FIELDS + SEARCHABLE_ATTRIBUTES, "required": LEGACY_FIELDS, "searchable": SEARCHABLE_ATTRIBUTES},
}
DECLARED_FIELDS = frozenset(COLUMNS) | frozenset(SEARCHABLE_ATTRIBUTES)
# 流水线自己派生的键，不属于契约字段；直接以 rows 调用接口时也接受。
DERIVED_FIELDS = frozenset({"version", "op", "source_at", "visible_at", "document", "reported", "attributes", "source_version", "index_version", "source_op", "index_op", "visibility_state", "document_equal", "expected", "delay_seconds", "gate", "threshold_seconds", "difference", "status", "tombstone", "superseded_versions", "version_duplicate_count"})

ADMISSION_CODES = ("UNRECOGNIZED_HEADER", "DUPLICATE_FIELD", "MISSING_DECLARED_FIELD", "UNDECLARED_FIELD", "SCHEMA_VERSION_CONFLICT", "UNKNOWN_SCHEMA")


def _canonical(version):
    schema = SCHEMAS[version]
    return {"fields": list(schema["fields"]), "required": list(schema["required"]), "searchable": list(schema["searchable"])}


def registry_fingerprint():
    """整份登记内容的稳定摘要。"""
    canonical = json.dumps({key: _canonical(key) for key in sorted(SCHEMAS)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def version_fingerprint(version):
    return hashlib.sha256(json.dumps(_canonical(version), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def descriptor():
    return {"fingerprint": registry_fingerprint(), "versions": [{"id": key, "version": value["version"], "label": value["label"], "fields": list(value["fields"]), "required": list(value["required"]), "searchable": list(value["searchable"]), "fingerprint": version_fingerprint(key)} for key, value in sorted(SCHEMAS.items())], "declared_attributes": list(SEARCHABLE_ATTRIBUTES), "admission_codes": list(ADMISSION_CODES)}


def names_of(cells):
    return [str(cell).strip() for cell in cells]


def is_header(cells):
    """分段表头识别：一行里过半单元格是已登记列名，即视为表头而不是数据。

    这样重排列、缺列、以及带未声明列的表头都能被识别并裁决，而数据行
    （业务键、数字、JSON）不会被误判。
    """
    names = names_of(cells)
    if not names:
        return False
    known = sum(1 for name in names if name in DECLARED_FIELDS)
    return known >= 2 and known * 2 >= len(names)


def claim_from_parameters(parameters):
    """本批声明的契约版本。未知版本不抛给入口，交给裁决隔离，避免回补停住。"""
    claimed = (parameters or {}).get("schema_version")
    if claimed is None:
        return None
    if not isinstance(claimed, str) or not claimed.strip():
        raise DomainError("BAD_SCHEMA_VERSION", "schema_version 需要契约版本标识")
    return claimed.strip()


def _result(status, reason=None, detail=None, schema_id=None, header=()):
    schema = SCHEMAS.get(schema_id)
    return {"status": status, "schema_id": schema["id"] if schema else None, "reason": reason, "detail": detail, "header": list(header), "declared_fields": list(schema["fields"]) if schema else list(DECLARED_FIELDS), "required_fields": list(schema["required"]) if schema else list(LEGACY_FIELDS), "searchable": list(schema["searchable"]) if schema else [], "admission": "formal" if status == "ACCEPTED" else "quarantined"}


def adjudicate(header, claimed=None):
    """裁决一个表头分段。返回裁决对象，定义冲突不抛错，原行留给隔离区。

    声明版本是不对称的：声明 v2 时，恰好只有原始列的旧段仍按其原义 v1
    读入（新定义向后兼容旧导出，回补不停）；声明 v1 却出现扩展属性，
    或声明一个未登记的版本，则说明语义不确定，整段隔离。
    """
    names = names_of(header)
    present = set(names)
    if not present & set(COLUMNS):
        return _result("QUARANTINED", "UNRECOGNIZED_HEADER", "表头不属于任何已登记契约", None, names)
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        return _result("QUARANTINED", "DUPLICATE_FIELD", "表头重复列：" + ",".join(duplicated), None, names)
    missing = [name for name in LEGACY_FIELDS if name not in present]
    if missing:
        return _result("QUARANTINED", "MISSING_DECLARED_FIELD", "缺少原始必填列：" + ",".join(missing), None, names)
    extras = [name for name in names if name not in set(LEGACY_FIELDS)]
    undeclared = [name for name in extras if name not in set(SEARCHABLE_ATTRIBUTES)]
    if undeclared:
        return _result("QUARANTINED", "UNDECLARED_FIELD", "表头包含未声明字段：" + ",".join(undeclared), None, names)
    inferred = "v2" if extras else "v1"
    if claimed is not None:
        if claimed not in SCHEMAS:
            return _result("QUARANTINED", "SCHEMA_VERSION_CONFLICT", f"本批声明未登记的契约版本 {claimed}，表头推导为 {inferred}", inferred, names)
        if SCHEMAS[claimed]["version"] < SCHEMAS[inferred]["version"]:
            return _result("QUARANTINED", "SCHEMA_VERSION_CONFLICT", f"本批声明 {claimed}，表头含 {inferred} 的扩展属性，定义不一致", inferred, names)
    return _result("ACCEPTED", None, None, inferred, names)


def infer(row):
    """行级契约：显式 _schema 优先，否则按已声明属性是否存在推断。"""
    declared = row.get("_schema")
    if declared in SCHEMAS:
        return declared
    return "v2" if any(name in row for name in SEARCHABLE_ATTRIBUTES) else "v1"


def row_conflict(row):
    """行级契约检查：未声明字段、以及声明版本与实际字段不符。"""
    declared = row.get("_schema")
    if declared is not None and declared not in SCHEMAS:
        return "UNKNOWN_SCHEMA", f"未登记的契约版本 {declared}"
    allowed = set(SCHEMAS[infer(row)]["fields"]) | DERIVED_FIELDS
    unknown = sorted(key for key in row if not str(key).startswith("_") and key not in allowed)
    if unknown:
        return "UNDECLARED_FIELD", "行内含未声明字段：" + ",".join(unknown)
    if declared is not None:
        has_extras = any(name in row for name in SEARCHABLE_ATTRIBUTES)
        if declared == "v1" and has_extras:
            return "SCHEMA_VERSION_CONFLICT", "声明 v1 但携带扩展属性"
    fields = row.get("_fields")
    if fields is not None:
        if not isinstance(fields, list) or any(name not in SCHEMAS[infer(row)]["fields"] for name in fields):
            return "UNDECLARED_FIELD", "行声明的字段清单未全部登记"
    return None


def attributes(row):
    """只取本行确有值的已登记可检索属性。空与哨兵视为未提供，不当零。"""
    found = {}
    for name in SEARCHABLE_ATTRIBUTES:
        if name in row and str(row[name]).strip().upper() not in SENTINELS:
            found[name] = row[name]
    return found


def compatible(left, right):
    """两条记录能否视为同一份内容。

    只比较双方都声明过的可检索属性：旧导出没有的扩展属性不参与比较，
    因此旧格式保持原义，不会被新定义读成"内容不同"；两边都声明过的
    属性取值不同才算内容差异。
    """
    if left.get("op") != right.get("op"):
        return False
    if json.dumps(left.get("document"), sort_keys=True, ensure_ascii=False) != json.dumps(right.get("document"), sort_keys=True, ensure_ascii=False):
        return False
    shared = set(attributes(left)) & set(attributes(right))
    return all(str(left[name]) == str(right[name]) for name in shared)


def merge_attributes(previous, row):
    """把 row 中已声明、previous 尚未声明的属性补记到 previous 上。

    返回 True 表示确有补记；没有新属性时返回 False（纯重复）。
    出现非属性的新字段返回 None（不能靠补记消除的差异）。
    """
    extra = [name for name in row.get("_fields", []) if name not in previous.get("_fields", [])]
    if any(name not in SEARCHABLE_ATTRIBUTES for name in extra):
        return None
    for name in extra:
        previous[name] = row[name]
    previous["_fields"] = list(previous.get("_fields", [])) + extra
    if extra:
        previous["_schema"] = "v2"
    return bool(extra)


def run_scope(used_versions, has_conflict):
    """批次身份里的契约范围。

    * 只用 v1 且无契约冲突的旧格式返回空串：旧批次身份保持原义，新增登记
      不会让旧导出换批次、也不会改写已复核结论；
    * 本批用到的扩展版本（v2+）把该版定义摘要并入身份，定义一旦变化，
      重跑得到新身份而不是复用/改写已封存结论；
    * 整批只有冲突、没有采纳行时用整份登记摘要兜底，不同定义下的隔离
      结论不会共用一个身份。
    """
    extended = sorted({version for version in used_versions if version != "v1"}, key=lambda item: SCHEMAS[item]["version"])
    if extended:
        return registry_fingerprint() + ":" + "+".join(version_fingerprint(version) for version in extended)
    return registry_fingerprint() + ":conflict" if has_conflict else ""


def shared_fields(previous, row):
    """两条重放记录共同声明的字段。旧段没有的扩展属性不参与比较，
    因此旧导出不会因为新导出多出属性列而被判成值冲突。"""
    return [name for name in previous.get("_fields", []) if name in row.get("_fields", [])]


def replay(previous, row):
    """同业务键在新旧导出中一起回放时的裁决。

    完全相同、或后来那份只是旧格式的少列副本 → duplicate（保留首条原义）；
    共同声明过的字段取值不同 → conflict（隔离并保留原值）；
    共同字段一致、仅多出已声明属性 → enrich（补记属性，核心字段不动）。
    """
    if previous.get("_raw") == row.get("_raw"):
        return "duplicate"
    shared = shared_fields(previous, row)
    if any(previous.get(name) != row.get(name) for name in shared):
        return "conflict"
    merged = merge_attributes(previous, row)
    if merged is None:
        return "conflict"
    return "enrich" if merged else "duplicate"
