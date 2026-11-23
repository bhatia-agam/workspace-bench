"""The model-continuation baseline: prompts cut after each read position, plain generation from
a fake server, rows at one layer number, and `wsbench read method=model_continuation`."""

import json

import pytest
from test_residual_store import REV, Tok, spec

from wsbench import cli, readouts
from wsbench.produce import read

EOT = 99
A = [spec("a1", family="alpha"), spec("a2", family="alpha", ids=(20, 21, 22, 23), positions=(2,))]


POSTS: list = []  # every request body the fake client received


class Client:
    """A fake HTTP client: each prompt is continued with its last id + 1, EOT, then a tail."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json):
        POSTS.append(json)
        rows = [{"output_ids": [ids[-1] + 1, EOT, 7]} for ids in json["input_ids"]]

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return rows

        return Response()


class ModelTok(Tok):
    def convert_tokens_to_ids(self, token):
        return EOT if token == "<|endoftext|>" else super().convert_tokens_to_ids(token)

    def decode(self, ids, skip_special_tokens=False):
        return " ".join(f"t{i}" for i in ids) if skip_special_tokens else f" t{ids[0]}"


@pytest.fixture
def cont(monkeypatch):
    from wsbench.produce.served import continuation
    from wsbench.produce.served import engine as engine_mod

    started = []
    monkeypatch.setattr(engine_mod, "load_tokenizer", lambda path: ModelTok())
    monkeypatch.setattr(engine_mod, "http_client", Client)
    monkeypatch.setattr(engine_mod, "processor", lambda hf_order: f"processor(hf={hf_order})")
    monkeypatch.setattr(
        continuation, "start_server", lambda model, log, **kw: (started.append(kw) or "proc", "u")
    )
    monkeypatch.setattr(continuation, "stop_server", lambda proc: started.append("stopped"))
    POSTS.clear()
    return continuation, started


def test_prompts_are_the_render_cut_after_each_read_position(cont):
    continuation, _ = cont
    prompts = continuation.prompts_of(A, Tok())
    assert [(p.id, p.pos, p.token, p.ids) for p in prompts] == [
        ("a1", 1, " t11", [10, 11]),
        ("a1", 3, " t13", [10, 11, 12, 13]),
        ("a2", 2, " t22", [20, 21, 22]),
    ]
    assert continuation.cut([5, 6, EOT, 7], [EOT]) == [5, 6]
    assert continuation.cut([5, 6], [EOT]) == [5, 6]


def test_the_engine_generates_from_token_ids_and_cuts_at_end_of_text(cont, tmp_path):
    continuation, started = cont
    engine = continuation.ContinuationEngine(tmp_path, work=tmp_path / "w", post_rows=2, top_k=5)
    texts = engine.decode([[10, 11], [20, 21, 22], [30]])
    assert texts == ["t12", "t23", "t31"] and engine.tokens == [[12], [23], [31]]
    assert [p["input_ids"] for p in POSTS] == [[[10, 11], [20, 21, 22]], [[30]]]
    sent = POSTS[0]
    assert sent["custom_logit_processor"] == "processor(hf=True)"
    params = sent["sampling_params"]
    assert params["ignore_eos"] is True and params["max_new_tokens"] == 256
    assert params["custom_params"] == {"hf_top_k": 5, "hf_top_p": 0.95}
    assert (params["top_k"], params["top_p"], params["temperature"]) == (1 << 30, 1.0, 1.0)
    assert started[0]["extra"][0] == "--enable-custom-logit-processor" and started[-1] == "stopped"
    assert engine.decode([]) == [] and len(started) == 2  # no server for nothing to read
    with pytest.raises(ValueError, match="temperature 1"):
        continuation.ContinuationEngine(tmp_path, temperature=0.7)


def test_rows_carry_one_layer_number_and_the_sidecar_declares_it(cont, tmp_path):
    continuation, started = cont
    engine = continuation.ContinuationEngine(tmp_path, work=tmp_path / "w")
    jobs = [read.Job("alpha", list(A), "sha-alpha")]
    out = tmp_path / "out"
    done = read.read_continuations(jobs, engine, out, reader=continuation.NAME, layer=44)
    assert [(d["family"], d["status"], d["cells"]) for d in done] == [("alpha", "read", 3)]
    rows = [json.loads(x) for x in (out / "alpha.jsonl").read_text().splitlines()]
    assert rows == [
        {"id": "a1", "layer": 44, "pos": 1, "token": " t11", "samples": ["t12"]},
        {"id": "a1", "layer": 44, "pos": 3, "token": " t13", "samples": ["t14"]},
        {"id": "a2", "layer": 44, "pos": 2, "token": " t22", "samples": ["t23"]},
    ]
    side = readouts.read_sidecar(out / "alpha.jsonl")
    assert side["layers"] == [44] and side["sampling"] == "prose1"
    assert side["reader"] == "model_continuation" and side["plan_sha"] == "sha-alpha"
    again = read.read_continuations(jobs, engine, out, reader=continuation.NAME, layer=44)
    assert again[0]["status"] == "exists" and started.count("stopped") == 1


def test_the_command_keys_and_usage_errors(capsys):
    assert {"method", "model_dir", "layer"} <= set(cli.Read().to_dict())
    base = ["read", "out=o", "families=multihop"]
    for argv, message in [
        (["method=guess", "lens=l"], "method is lens or model_continuation"),
        (["method=model_continuation"], "needs model_dir="),
        (["method=model_continuation", "model_dir=m", "lens=l"], "no lens="),
        (["method=model_continuation", "model_dir=m", "greedy=True"], "takes no greedy="),
        (["model_dir=m", "lens=l"], "method=lens needs lens="),
        ([], "method=lens needs lens="),
    ]:
        assert cli.main([*base, *argv]) == cli.EXIT_USAGE
        assert message in capsys.readouterr().err
    assert cli.main([*base, "method=model_continuation", "model_dir=m", "nope=1"]) == 2


def test_the_command_reads_continuations_and_judges_one_layer(cont, tmp_path, monkeypatch, capsys):
    plan = tmp_path / "plan.jsonl"
    plan.write_text("\n".join(json.dumps(s.row()) for s in A) + "\n")
    out = tmp_path / "out"
    argv = [
        "read", "method=model_continuation", f"model_dir={tmp_path}", f"plan={plan}",
        f"out={out}", "model=m", f"revision={REV}", "layer=36",
    ]  # fmt: skip
    assert cli.main(argv) == 0
    assert f"alpha: 3 continuations read -> {out / 'alpha.jsonl'}" in capsys.readouterr().out
    assert json.loads((out / "alpha.jsonl").read_text().splitlines()[0])["layer"] == 36
    # judge=True hands the files to `run` with the one layer to judge
    seen = {}
    monkeypatch.setattr(
        cli, "_run_command", lambda kind, args: seen.update(kind=kind, args=args) or 0
    )
    monkeypatch.setattr(cli.Read, "plans", lambda self: {"alpha": list(A)})
    monkeypatch.setattr(read, "job", lambda f, specs, **kw: read.Job(f, list(specs), "sha"))
    judged = [
        "read", "method=model_continuation", f"model_dir={tmp_path}", "families=alpha",
        f"out={tmp_path / 'out2'}", "judge=True",
    ]  # fmt: skip
    assert cli.main(judged) == 0
    assert seen["kind"] is cli.RunFamilies and "layers=44" in seen["args"]
    assert f"readouts_root={tmp_path / 'out2'}" in seen["args"] and "families=alpha" in seen["args"]
