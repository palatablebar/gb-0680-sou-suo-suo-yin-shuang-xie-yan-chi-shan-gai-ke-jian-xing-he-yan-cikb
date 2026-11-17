"""字段契约准入裁决（新格式分批回放）。"""
import copy
import pytest
from app.pipeline import calculate,execute
from app import schemas,store
from app.errors import DomainError

BASE = "event_id,doc_id,version,op,source_time,visible_time,side,payload,reported,note\n"
LEGACY = BASE + '0010,0001,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,旧\n'
EXTENDED = "event_id,doc_id,version,op,source_time,visible_time,side,payload,reported,note,category,tags\n" + '0010,0001,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,新,图书,促销\n'
UNKNOWN = BASE.rstrip("\n") + ",color\n" + '0010,0001,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,旧,红\n'


def run(csv, params=None):
    return calculate(csv.encode(), params)


def test_legacy_batch_is_formal_and_keeps_meaning():
    result = run(LEGACY)
    contract = result["contract"]
    assert contract["admission"] == "FORMAL"
    assert contract["used_versions"] == ["v1"]
    assert result["stages"][0]["metrics"]["accepted"] == 1
    assert result["stages"][0]["rows"][0]["_schema"] == "v1"


def test_extended_batch_only_takes_declared_fields():
    result = run(EXTENDED)
    contract = result["contract"]
    assert contract["admission"] == "FORMAL" and contract["used_versions"] == ["v2"]
    row = result["stages"][0]["rows"][0]
    assert row["category"] == "图书" and row["tags"] == "促销"
    assert result["stages"][1]["rows"][0]["attributes"] == {"category": "图书", "tags": "促销"}


def test_undeclared_field_isolates_whole_segment_and_keeps_raw_row():
    result = run(UNKNOWN)
    intake = result["stages"][0]
    assert intake["metrics"]["accepted"] == 0
    assert intake["contract"]["admission"] == "QUARANTINED"
    assert result["stages"][6]["metrics"]["ready"] is False
    quarantine = intake["quarantine"][0]
    assert quarantine["reason"] == "UNDECLARED_FIELD"
    # 原始行整行保留，不按旧定义重解。
    assert quarantine["_raw"][0] == "0010" and quarantine["_raw"][-1] == "红"


def test_mixed_old_and_new_segments_both_admitted():
    mixed = LEGACY + "event_id,doc_id,version,op,source_time,visible_time,side,payload,reported,note,category\n" + '0020,0002,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,新,图书\n'
    result = run(mixed)
    assert result["contract"]["admission"] == "FORMAL"
    assert result["contract"]["used_versions"] == ["v1", "v2"]
    assert result["stages"][0]["metrics"]["accepted"] == 2


def test_declared_v1_with_extended_header_is_isolated():
    result = run(EXTENDED, {"schema_version": "v1"})
    assert result["contract"]["admission"] == "QUARANTINED"
    assert result["stages"][0]["metrics"]["accepted"] == 0


def test_declared_v2_lets_legacy_segment_through_unchanged():
    "声明新版不能把旧段停住，旧段仍按 v1 原义读入。"
    result = run(LEGACY, {"schema_version": "v2"})
    assert result["contract"]["admission"] == "FORMAL"
    assert result["stages"][0]["rows"][0]["_schema"] == "v1"


def test_unknown_declared_version_isolates_instead_of_stalling():
    result = run(EXTENDED, {"schema_version": "v9"})
    assert result["contract"]["admission"] == "QUARANTINED"
    assert result["stages"][0]["quarantine"][0]["reason"] == "SCHEMA_VERSION_CONFLICT"


def test_columns_align_by_name_not_position():
    reordered = "doc_id,event_id,version,op,source_time,visible_time,side,payload,reported,note,category\n" + '0001,0010,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,新,图书\n'
    row = run(reordered)["stages"][0]["rows"][0]
    assert row["event_id"] == "0010" and row["doc_id"] == "0001" and row["category"] == "图书"


def test_missing_required_column_isolates():
    partial = "event_id,doc_id,version\n0010,0001,4\n"
    result = calculate(partial.encode())
    assert result["contract"]["admission"] == "QUARANTINED"
    assert {q["reason"] for q in result["stages"][0]["quarantine"]} == {"MISSING_DECLARED_FIELD"}


def test_duplicate_column_isolates():
    doubled = BASE.rstrip("\n") + ",note\n" + '0010,0001,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,旧,旧\n'
    result = run(doubled)
    assert result["stages"][0]["quarantine"][0]["reason"] == "DUPLICATE_FIELD"


def test_unrecognized_header_still_rejects_atomically():
    "完全无法识别的表头仍是入口 422，不写批次。"
    with pytest.raises(DomainError) as error:
        run("a,b,c\n1,2,3\n")
    assert error.value.code == "BAD_HEADER"


def test_schema_verdict_matches_between_page_and_diff():
    "同一批次的裁决只落一次：M1 与 M2 的 contract 完全一致。"
    result = run(EXTENDED)
    assert result["stages"][0]["contract"] == result["stages"][1]["contract"] == result["contract"]


def test_contract_is_part_of_batch_identity_when_extended():
    "扩展到 v2 的批次，身份绑定该版定义；定义一变，重跑得到新身份而不是复用旧批次。"
    v2_before = run(EXTENDED)["run_id"]
    original = copy.deepcopy(schemas.SCHEMAS["v2"])
    try:
        schemas.SCHEMAS["v2"]["fields"] = original["fields"] + ("brand",)
        schemas.SCHEMAS["v2"]["searchable"] = original["searchable"] + ("brand",)
        schemas.SEARCHABLE_ATTRIBUTES = schemas.SEARCHABLE_ATTRIBUTES + ("brand",)
        assert run(EXTENDED)["run_id"] != v2_before
    finally:
        schemas.SCHEMAS["v2"] = original
        schemas.SEARCHABLE_ATTRIBUTES = ("category", "tags")


def test_field_removed_from_definition_isolates_conflicting_batch():
    "字段定义撤回后，带该列的批次整批隔离，而不是按新定义静默丢弃。"
    original = copy.deepcopy(schemas.SCHEMAS["v2"])
    try:
        schemas.SCHEMAS["v2"] = {**original, "fields": original["fields"][:-1], "searchable": original["searchable"][:-1]}
        schemas.SEARCHABLE_ATTRIBUTES = ("category",)
        result = run(EXTENDED)
        assert result["contract"]["admission"] == "QUARANTINED"
        assert result["stages"][0]["quarantine"][0]["reason"] == "UNDECLARED_FIELD"
    finally:
        schemas.SCHEMAS["v2"] = original
        schemas.SEARCHABLE_ATTRIBUTES = ("category", "tags")


def test_legacy_identity_unaffected_by_registry_growth():
    "只含原始列的旧导出，身份不随新属性登记而变化。"
    before = run(LEGACY)["run_id"]
    original = copy.deepcopy(schemas.SCHEMAS["v2"])
    try:
        schemas.SCHEMAS["v2"]["fields"] = original["fields"] + ("brand",)
        assert run(LEGACY)["run_id"] == before
    finally:
        schemas.SCHEMAS["v2"] = original


def test_rerun_same_batch_adds_no_record_and_keeps_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    first = execute(EXTENDED.encode())
    reviewd = store.review(first["run_id"], 1, "已复核")
    second = execute(EXTENDED.encode())
    assert second["run_id"] == first["run_id"]
    assert second["decision"] == reviewd["decision"] == "已复核"
    assert second["version"] == reviewd["version"]
    assert len(store.history()) == 1
    assert second["contract"] == first["contract"]


def test_rerun_quarantined_batch_keeps_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    first = execute(UNKNOWN.encode())
    second = execute(UNKNOWN.encode())
    assert second["run_id"] == first["run_id"]
    assert second["contract"] == first["contract"]
    assert len(store.history()) == 1


def test_replayed_duplicate_does_not_conflict_over_new_attribute():
    "旧导出没有扩展属性，不算与带属性的同键行取值冲突。"
    mixed = LEGACY + "event_id,doc_id,version,op,source_time,visible_time,side,payload,reported,note,category\n" + '0010,0001,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,旧,图书\n'
    result = run(mixed)
    assert not any(q["reason"] == "DUPLICATE_CONFLICT" for q in result["stages"][0]["quarantine"])
    assert result["stages"][0]["metrics"]["accepted"] == 1


def test_replayed_duplicate_same_shared_fields_is_duplicate():
    duplicated = LEGACY + '0010,0001,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,旧\n'
    result = run(duplicated)
    assert result["stages"][0]["metrics"]["duplicate"] == 1
    assert result["stages"][0]["metrics"]["accepted"] == 1


def test_replayed_duplicate_shared_field_conflict_is_isolated():
    conflict = LEGACY + '0010,0001,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,不同说明\n'
    result = run(conflict)
    assert result["stages"][0]["quarantine"][0]["reason"] == "DUPLICATE_CONFLICT"
    assert result["stages"][0]["rows"][0]["note"] == "旧"


def test_schema_endpoint_exposes_registry(client):
    body = client.get("/api/schema").get_json()
    assert body["registry"]["fingerprint"] == schemas.registry_fingerprint()
    ids = [item["id"] for item in body["registry"]["versions"]]
    assert ids == ["v1", "v2"]
    assert "category" in body["registry"]["declared_attributes"]


def test_archive_carries_schema_conflict_rows(monkeypatch, tmp_path):
    import csv, io
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    from app.main import create_app
    client = create_app().test_client()
    run_id = client.post("/api/runs", json={"csv": UNKNOWN}).get_json()["run_id"]
    rows = list(csv.reader(io.StringIO(client.get(f"/api/runs/{run_id}/archive").data.decode("utf-8-sig"))))
    assert rows[0][7] == "schema"
    assert any(row[3] == "schema_conflict" and row[5] == "UNDECLARED_FIELD" for row in rows[1:])
    assert any(row[3] == "quarantine" and "0010" in row[6] for row in rows[1:])


def test_partial_batch_keeps_admitted_rows_and_adds_no_extra_record(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    from app.main import create_app
    client = create_app().test_client()
    partial = LEGACY + "event_id,doc_id,version,op,source_time,visible_time,side,payload,reported,note,color\n" + '0020,0002,4,upsert,2026-11-16T10:00:00Z,-,source,"{}",1,坏,红\n'
    first = client.post("/api/runs", json={"csv": partial}).get_json()
    assert first["contract"]["admission"] == "PARTIAL"
    assert first["stages"][0]["metrics"]["accepted"] == 1
    assert first["stages"][6]["metrics"]["ready"] is True
    second = client.post("/api/runs", json={"csv": partial}).get_json()
    assert second["run_id"] == first["run_id"]
    assert len(client.get("/api/runs").get_json()["runs"]) == 1


def test_upload_accepts_declared_schema_version(monkeypatch, tmp_path):
    import io
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    from app.main import create_app
    client = create_app().test_client()
    ok = client.post("/api/upload", data={"file": (io.BytesIO(EXTENDED.encode()), "events.csv"), "schema_version": "v2"})
    assert ok.get_json()["contract"]["admission"] == "FORMAL"
    bad = client.post("/api/upload", data={"file": (io.BytesIO(EXTENDED.encode()), "events.csv"), "schema_version": "v1"})
    assert bad.get_json()["contract"]["admission"] == "QUARANTINED"
