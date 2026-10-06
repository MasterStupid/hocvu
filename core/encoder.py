import hashlib
import math
from typing import List, Union
from .nlp import tokenize, content_tokens, ngrams, normalize

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
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.api_url = api_url or "https://api.openai.com/v1/embeddings"
        
    def encode(self, text: str) -> List[float]:
        return self.encode_batch([text])[0]
        
    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        try:
            import urllib.request
            import json
            req = urllib.request.Request(self.api_url, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {self.api_key}")
            data = json.dumps({"input": texts, "model": self.model}).encode("utf-8")
            with urllib.request.urlopen(req, data=data) as response:
                res = json.loads(response.read().decode("utf-8"))
                return [item["embedding"] for item in res["data"]]
        except Exception:
            return [[0.0] * self.dim for _ in texts]

def build_encoder(config) -> Union[SimHashEncoder, OpenAIEncoder]:
    if config.llm_backend == "openai" and getattr(config, 'openai_key', None):
        return OpenAIEncoder(
            api_key=config.openai_key, 
            model=getattr(config, 'openai_embed', "text-embedding-3-small"),
            dim=getattr(config, 'embed_dim', 1536),
            api_url=getattr(config, 'openai_url', None)
        )
    return SimHashEncoder(dim=getattr(config, 'embed_dim', 256))
