import hashlib
import math
from typing import List, Union
from urllib.parse import urlsplit, urlunsplit
from .nlp import tokenize, content_tokens, ngrams, normalize
from .settings import clean_api_key

def l2_norm(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]

def dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))

class SimHashEncoder:
    def __init__(self, dim: int):
        self.dim = dim

    def encode(self, text: str) -> List[float]:
        text = normalize(text).lower()
        tokens = tokenize(text)
        
        features = []
        features.extend(tokens)
        features.extend(ngrams(tokens, 2))
        
        for i in range(len(text) - 2):
            features.append(text[i:i+3])
            
        for t in tokens:
            if len(t) > 4:
                for i in range(len(t) - 3):
                    features.append(t[i:i+4])
                    
        vec = [0.0] * self.dim
        for feature in set(features):
            h = hashlib.blake2b(feature.encode('utf-8'), digest_size=4).digest()
            val = int.from_bytes(h, byteorder='big')
            idx = val % self.dim
            sign = 1 if (val & (1 << 31)) else -1
            vec[idx] += sign
            
        return l2_norm(vec)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.encode(t) for t in texts]

class OpenAIEncoder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dim: int = 1536, api_url: str = None):
        self.api_key = clean_api_key(api_key)
        if not self.api_key:
            raise ValueError("OpenAI API key is missing or is an example placeholder.")
        self.model = model
        self.dim = dim
        parsed = urlsplit(api_url or "https://api.openai.com/v1")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OpenAI base URL must be a full HTTP(S) URL.")
        path = parsed.path.rstrip("/")
        if not path.endswith("/embeddings"):
            path += "/embeddings"
        self.api_url = urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
        
    def encode(self, text: str) -> List[float]:
        return self.encode_batch([text])[0]
        
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            import urllib.request
            import json
            req = urllib.request.Request(self.api_url, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            payload = {"input": texts, "model": self.model}
            if self.model.startswith("text-embedding-3-"):
                payload["dimensions"] = self.dim
            data = json.dumps(payload).encode("utf-8")
            with urllib.request.urlopen(req, data=data, timeout=35) as response:
                res = json.loads(response.read().decode("utf-8"))
                items = sorted(res["data"], key=lambda item: item["index"])
                if [item["index"] for item in items] != list(range(len(texts))):
                    raise ValueError("Incomplete or duplicate embedding indices.")
                vectors = [item["embedding"] for item in items]
                for vector in vectors:
                    if (len(vector) != self.dim
                            or any(isinstance(value, bool) or not isinstance(value, (float, int))
                                   or not math.isfinite(value) for value in vector)
                            or not any(vector)):
                        raise ValueError("Invalid embedding vector.")
                return vectors
        except Exception as exc:
            raise RuntimeError("OpenAI embedding request failed; no vectors were generated.") from exc

def build_encoder(config) -> Union[SimHashEncoder, OpenAIEncoder]:
    if config.llm_backend == "openai" and clean_api_key(getattr(config, 'openai_key', "")):
        return OpenAIEncoder(
            api_key=config.openai_key, 
            model=getattr(config, 'openai_embed', "text-embedding-3-small"),
            dim=getattr(config, 'embed_dim', 1536),
            api_url=getattr(config, 'openai_url', None)
        )
    return SimHashEncoder(dim=getattr(config, 'embed_dim', 256))
