from typing import Iterator, List
import hashlib
import json
from .models import Regulation, Chunk
from .nlp import sentences

def _gen_chunk_id(rid: str, aid: str, content: str, seq: int) -> str:
    identity = json.dumps([rid, aid, content, seq], ensure_ascii=False, separators=(",", ":"))
    return hashlib.blake2b(identity.encode("utf-8"), digest_size=16).hexdigest()


def _bounded_sentences(text: str, budget: int) -> Iterator[str]:
    """Prefer word boundaries, but split long tokens rather than dropping text."""
    for sentence in sentences(text):
        while len(sentence) > budget:
            end = sentence.rfind(" ", 0, budget + 1)
            if end <= 0:
                end = budget
            yield sentence[:end]
            sentence = sentence[end:].lstrip()
        if sentence:
            yield sentence

def split_regulation(reg: Regulation, max_chars: int, overlap_sents: int) -> List[Chunk]:
    if max_chars <= 0:
        raise ValueError("max_chars phải lớn hơn 0.")
    if overlap_sents < 0:
        raise ValueError("overlap_sents phải lớn hơn hoặc bằng 0.")
    chunks = []
    seq = 0

    for article in reg.articles:
        for clause in article.clauses:
            clause_text = f"{article.heading}\n{clause.content}"
            if len(clause_text) <= max_chars:
                texts = [clause_text]
            else:
                prefix = article.heading + "\n"
                # A very long heading stays intact in metadata. Never let it
                # consume the body budget or force an oversized chunk.
                if len(prefix) >= max_chars:
                    prefix = ""
                budget = max_chars - len(prefix)
                texts, current = [], []
                for part in _bounded_sentences(clause.content, budget):
                    if current and len(" ".join(current + [part])) > budget:
                        texts.append(prefix + " ".join(current))
                        overlap = current[-overlap_sents:] if overlap_sents else []
                        while overlap and len(" ".join(overlap + [part])) > budget:
                            overlap.pop(0)
                        current = overlap + [part]
                    else:
                        current.append(part)
                if current:
                    texts.append(prefix + " ".join(current))
            for text in texts:
                seq += 1
                chunks.append(Chunk(
                    cid=_gen_chunk_id(reg.rid, article.aid, text, seq),
                    rid=reg.rid,
                    reg_title=reg.title,
                    version=reg.version,
                    valid_from=reg.valid_from,
                    valid_until=reg.valid_until,
                    aid=article.aid,
                    art_heading=article.heading,
                    clause_ids=[clause.cid],
                    text=text,
                    seq=seq,
                ))
    return chunks
