# Adding a readout method

A readout method turns one activation vector into a ranked token list or into sentences. This is
for `wsbench produce`; `wsbench read` is extended differently ([fast_path.md](fast_path.md), "Adapting it").

**The class** follows the `Method` protocol in `src/wsbench/produce/methods.py`. A token lens
returns `Readout(tokens=[...], scores=[...])` where this one returns sentences:

```python
from wsbench.produce import Producer
from wsbench.produce.methods import Readout


class MyLens:
    name = "my_lens"  # written to the readouts sidecar as reader and arm
    layers = None  # or [42]: a lens trained at one layer reads there, whatever the plan lists

    def bind(self, backend):  # once, after the model is loaded
        self.backend = backend  # .model, .tokenizer, .device, .unembed, .final_norm

    def read(self, h, layer):  # h: one residual vector, 32-bit floats, on the CPU
        return Readout(samples=["a sentence about what the vector holds"])


p = Producer.load("Qwen/Qwen3.6-27B", MyLens())  # an instance goes where a bundled name would
p.run_family("poetry", "outputs/readouts/my_lens/poetry.jsonl", limit=10)
```

**From the shell**, `method=` takes the names in the `METHODS` table of `methods.py`.
Add `"my_lens": MyLens` there, then
`uv run wsbench produce family=poetry method=my_lens limit=10 out=outputs/readouts/my_lens/poetry.jsonl`.

**The sampling label.** The sidecar of a readouts file declares how it was sampled: `tokens10`,
`prose1`, or `bullet4` for four separate one-bullet readouts per cell. `sampling_of` in
`methods.py` decides it from the method, and a class it does not know gets `tokens10`. For a
method that writes sentences, check what `sampling_of(MyLens())` returns and make it return
`prose1` or `bullet4`: a wrong label tells the judge that sentences are a token list.

**Check it** after the ten-question run: `sampling` in `poetry.jsonl.meta.json`, then
`uv run wsbench check readouts_contract readouts=outputs/readouts/my_lens/poetry.jsonl family=poetry`.
