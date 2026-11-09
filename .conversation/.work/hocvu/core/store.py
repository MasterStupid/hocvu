import json
from pathlib import Path
from typing import List, Tuple, Dict
from .encoder import dot

class VecStore:
    def __init__(self, dim: int):
        self.dim = dim
        self.items: List[Dict] = []
        
    def add(self, item_id: str, vector: List[float], meta: dict):
        if len(vector) != self.dim:
            raise ValueError(f"Vector dimension mismatch: expected {self.dim}, got {len(vector)}")
        self.items.append({
            "id": item_id,
            "vec": vector,
            "meta": meta
        })
        
    def search(self, query_vec: List[float], k: int) -> List[Tuple[str, float, dict]]:
        if not self.items:
            return []
            
        results = []
        for item in self.items:
            score = dot(query_vec, item["vec"])
            results.append((item["id"], score, item["meta"]))
            
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]
        
    def save(self, path: Path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({
                "dim": self.dim,
                "items": self.items
            }, f, ensure_ascii=False)
            
    def load(self, path: Path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.dim = data["dim"]
            self.items = data["items"]
            
    def __len__(self) -> int:
        return len(self.items)
