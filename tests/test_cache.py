import json

import pytest

from wsbench.cache import Cache, fingerprint


def test_fingerprint_stable_and_order_sensitive():
    a = fingerprint("m", "v1", {"x": 1, "y": 2})
    assert a == fingerprint("m", "v1", {"y": 2, "x": 1})
    assert len(a) == 16
    assert a != fingerprint("m", "v2", {"x": 1, "y": 2})


def test_put_get_round_trip(tmp_path):
    c = Cache(tmp_path / "cache.jsonl")
    assert len(c) == 0
    c.put("k1", "fp", {"result": {"label": "ok"}, "extra": 1})
    assert len(c) == 1
    row = c.get("k1", "fp")
    assert row is not None and row["result"] == {"label": "ok"} and row["extra"] == 1
    assert row["key"] == "k1" and row["fp"] == "fp" and "ts" in row
    assert c.get("k1", "other") is None
    assert c.get("nope", "fp") is None
    c.close()


def test_reserved_keys_rejected(tmp_path):
    c = Cache(tmp_path / "c.jsonl")
    for bad in ({"key": 1}, {"fp": 1}, {"ts": 1}):
        with pytest.raises(ValueError):
            c.put("k", "fp", {"result": 1, **bad})
    c.close()


def test_failed_rows_skipped_unless_included(tmp_path):
    c = Cache(tmp_path / "c.jsonl")
    c.put("k", "fp", {"result": {"a": 1}})
    c.put("k", "fp", {"result": None})
    c.put("k", "fp", {"note": "no result key"})
    got = c.get("k", "fp")
    assert got is not None and got["result"] == {"a": 1}
    got = c.get("k", "fp", include_failed=True)
    assert got is not None and got.get("note") == "no result key"
    # newest good row wins
    c.put("k", "fp", {"result": {"a": 2}})
    assert c.get("k", "fp")["result"] == {"a": 2}
    c.close()


def test_torn_last_line_and_foreign_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text(
        json.dumps({"key": "k", "fp": "fp", "ts": 0, "result": {"a": 1}})
        + "\n"
        + "not json\n"
        + json.dumps({"no_key": True})
        + "\n"
        + '{"key": "k", "fp": "fp", "ts": 1, "result": {"a": 2'  # torn
    )
    c = Cache(p)
    assert len(c) == 1
    assert c.get("k", "fp")["result"] == {"a": 1}
    c.put("k2", "fp", {"result": 3})
    c.close()
    lines = p.read_text().splitlines()
    assert json.loads(lines[-1])["key"] == "k2"
    # the torn line was terminated, so the new row is on its own line
    assert lines[-2].startswith('{"key": "k", "fp": "fp", "ts": 1')


def test_resume_across_instances(tmp_path):
    p = tmp_path / "c.jsonl"
    c = Cache(p)
    c.put("a", "fp1", {"result": 1})
    c.put("a", "fp2", {"result": 2})
    c.close()
    c2 = Cache(p)
    assert len(c2) == 2
    assert c2.get("a", "fp1")["result"] == 1
    assert c2.get("a", "fp2")["result"] == 2
    c2.put("b", "fp1", {"result": 3})
    assert len(c2) == 3
    c2.close()
    assert len(p.read_text().splitlines()) == 3


def test_creates_parent_dir(tmp_path):
    c = Cache(tmp_path / "deep" / "dir" / "c.jsonl")
    c.put("k", "fp", {"result": 1})
    c.close()
    assert (tmp_path / "deep" / "dir" / "c.jsonl").exists()


def test_put_survives_a_lone_surrogate(tmp_path):
    # a model can emit half an emoji's UTF-16 pair ("\ud83e"), which json.loads accepts; writing
    # it used to raise UnicodeEncodeError and fail the whole run. Normal rows stay byte-identical.
    p = tmp_path / "c.jsonl"
    c = Cache(p)
    bad = json.loads('"smile \\ud83e here"')
    c.put("k1", "fp", {"result": {"text": bad}})
    c.put("k2", "fp", {"result": {"text": "é plain"}})
    assert c.get("k1", "fp")["result"]["text"] == bad
    lines = p.read_text(encoding="utf-8").splitlines()
    assert "\\ud83e" in lines[0] and "é plain" in lines[1]  # ASCII-escaped only when needed
    assert Cache(p).get("k1", "fp")["result"]["text"] == bad  # reads back the same string


def test_shared_log_survives_a_lone_surrogate(tmp_path):
    from wsbench.cache import SharedLog

    bad = json.loads('"half \\ud83e"')
    log = SharedLog(tmp_path / "s.jsonl")
    log.put("k1", "fp", {"result": bad})
    log.put("k2", "fp", {"result": "é plain"})
    raw = (tmp_path / "s.jsonl").read_bytes()
    assert b"\\ud83e" in raw and "é plain".encode() in raw
    assert SharedLog(tmp_path / "s.jsonl").get("k1", "fp")["result"] == bad


def test_fingerprint_survives_a_lone_surrogate_and_moves_no_valid_one():
    import hashlib

    def old(*parts):  # the rule before the fix, verbatim
        blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    valid = [
        ("pv", "claude-opus-5-5", None, 0.0, "system", "user"),
        ("é ü 漢字 \U0001f9e0 emoji", {"b": [1, 2.5, None, True], "a": "x\ny"}),
        ("", [], {}, "\x00served_by", json.loads('"\\ud83e\\udde0"')),  # a full pair: one character
    ]
    for parts in valid:
        assert fingerprint(*parts) == old(*parts)
    bad = json.loads('"half \\ud83e"')
    with pytest.raises(UnicodeEncodeError):
        old("pv", bad)
    fp = fingerprint("pv", bad)
    assert len(fp) == 16 and fp == fingerprint("pv", bad)  # stable
    assert fp != fingerprint("pv", "half ") and fp != fingerprint(
        "pv", json.loads('"half \\ud83d"')
    )
