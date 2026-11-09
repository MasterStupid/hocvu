"""Minimal NumPy re-implementation of the SentenceTransformer API used by
core/semantic.py, for intfloat/multilingual-e5-small (BERT encoder + mean
pooling + L2 normalisation).  Weights are memory-mapped from the official
model.safetensors, so the 250k x 384 word-embedding matrix never has to be
resident in RAM.  Used only to verify the hybrid numbers on a 1.5 GB machine.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
from scipy.special import erf
from tokenizers import Tokenizer

MODEL_DIR = Path(os.environ.get("E5_DIR", "/home/runner/workspace/.work/e5"))
__version__ = "numpy-e5-shim"


def _load_safetensors(path: Path) -> dict:
    with path.open("rb") as fh:
        n = int.from_bytes(fh.read(8), "little")
        header = json.loads(fh.read(n))
    base = 8 + n
    dtypes = {"F32": np.float32, "I64": np.int64}
    out = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        start, end = meta["data_offsets"]
        dt = dtypes[meta["dtype"]]
        count = (end - start) // np.dtype(dt).itemsize
        arr = np.memmap(path, dtype=dt, mode="r", offset=base + start, shape=(count,))
        out[name] = arr.reshape(meta["shape"])
    return out


def _layer_norm(x, w, b, eps):
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return ((x - mu) / np.sqrt(var + eps)) * w + b


def _linear(x, w, b):
    return x @ w.T + b


class SentenceTransformer:
    def __init__(self, model_name_or_path=None, cache_folder=None, **kwargs):
        cfg = json.loads((MODEL_DIR / "config.json").read_text())
        self.cfg = cfg
        self.eps = cfg["layer_norm_eps"]
        self.heads = cfg["num_attention_heads"]
        self.hidden = cfg["hidden_size"]
        self.max_len = json.loads((MODEL_DIR / "sentence_bert_config.json").read_text())["max_seq_length"]
        raw = _load_safetensors(MODEL_DIR / "model.safetensors")
        self.word = raw["embeddings.word_embeddings.weight"]          # stays memory-mapped
        keep = {k: np.ascontiguousarray(v, dtype=np.float32) for k, v in raw.items()
                if k != "embeddings.word_embeddings.weight" and v.dtype == np.float32}
        self.w = keep
        self.tok = Tokenizer.from_file(str(MODEL_DIR / "tokenizer.json"))
        self.tok.no_padding()
        self.tok.enable_truncation(max_length=self.max_len)

    def get_sentence_embedding_dimension(self):
        return self.hidden

    def _forward(self, ids_batch):
        w = self.w
        L = max(len(ids) for ids in ids_batch)
        B = len(ids_batch)
        ids = np.zeros((B, L), dtype=np.int64)
        mask = np.zeros((B, L), dtype=np.float32)
        for i, seq in enumerate(ids_batch):
            ids[i, :len(seq)] = seq
            mask[i, :len(seq)] = 1.0
        x = np.asarray(self.word[ids.reshape(-1)], dtype=np.float32).reshape(B, L, -1)
        x = x + w["embeddings.position_embeddings.weight"][:L][None]
        x = x + w["embeddings.token_type_embeddings.weight"][0][None, None]
        x = _layer_norm(x, w["embeddings.LayerNorm.weight"], w["embeddings.LayerNorm.bias"], self.eps)
        H, D = self.heads, self.hidden // self.heads
        neg = (1.0 - mask)[:, None, None, :] * np.finfo(np.float32).min
        for i in range(self.cfg["num_hidden_layers"]):
            p = f"encoder.layer.{i}."
            q = _linear(x, w[p + "attention.self.query.weight"], w[p + "attention.self.query.bias"])
            k = _linear(x, w[p + "attention.self.key.weight"], w[p + "attention.self.key.bias"])
            v = _linear(x, w[p + "attention.self.value.weight"], w[p + "attention.self.value.bias"])
            q = q.reshape(B, L, H, D).transpose(0, 2, 1, 3)
            k = k.reshape(B, L, H, D).transpose(0, 2, 1, 3)
            v = v.reshape(B, L, H, D).transpose(0, 2, 1, 3)
            s = (q @ k.transpose(0, 1, 3, 2)) / np.float32(np.sqrt(D)) + neg
            s = s - s.max(-1, keepdims=True)
            e = np.exp(s)
            a = e / e.sum(-1, keepdims=True)
            c = (a @ v).transpose(0, 2, 1, 3).reshape(B, L, self.hidden)
            c = _linear(c, w[p + "attention.output.dense.weight"], w[p + "attention.output.dense.bias"])
            x = _layer_norm(c + x, w[p + "attention.output.LayerNorm.weight"], w[p + "attention.output.LayerNorm.bias"], self.eps)
            h = _linear(x, w[p + "intermediate.dense.weight"], w[p + "intermediate.dense.bias"])
            h = (0.5 * h * (1.0 + erf(h / np.float32(np.sqrt(2.0))))).astype(np.float32)
            h = _linear(h, w[p + "output.dense.weight"], w[p + "output.dense.bias"])
            x = _layer_norm(h + x, w[p + "output.LayerNorm.weight"], w[p + "output.LayerNorm.bias"], self.eps)
        m = mask[:, :, None]
        pooled = (x * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        norm = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.clip(norm, 1e-12, None)).astype(np.float32)

    def encode(self, sentences, batch_size=32, normalize_embeddings=False,
               convert_to_numpy=True, show_progress_bar=False, **kwargs):
        single = isinstance(sentences, str)
        if single:
            sentences = [sentences]
        order = np.argsort([-len(s) for s in sentences], kind="stable")
        out = np.zeros((len(sentences), self.hidden), dtype=np.float32)
        for start in range(0, len(sentences), batch_size):
            idx = order[start:start + batch_size]
            enc = [self.tok.encode(sentences[j]).ids for j in idx]
            out[idx] = self._forward(enc)
        if normalize_embeddings:
            out = out / np.clip(np.linalg.norm(out, axis=1, keepdims=True), 1e-12, None)
        return out[0] if single else out
