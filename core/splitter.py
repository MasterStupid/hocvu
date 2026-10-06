from typing import List
import hashlib
from .models import Regulation, Chunk
from .nlp import sentences

def _gen_chunk_id(content: str, seq: int) -> str:
    h = hashlib.blake2b(f"{content}_{seq}".encode('utf-8'), digest_size=8).hexdigest()
    return h

def split_regulation(reg: Regulation, max_chars: int, overlap_sents: int) -> List[Chunk]:
    chunks = []
    seq = 0
    
    for article in reg.articles:
        for clause in article.clauses:
            clause_text = f"{article.heading}\n{clause.content}"
            if len(clause_text) <= max_chars:
                seq += 1
                chunks.append(Chunk(
                    cid=_gen_chunk_id(clause_text, seq),
                    rid=reg.rid,
                    reg_title=reg.title,
                    version=reg.version,
                    valid_from=reg.valid_from,
                    valid_until=reg.valid_until,
                    aid=article.aid,
                    art_heading=article.heading,
                    clause_ids=[clause.cid],
                    text=clause_text,
                    seq=seq
                ))
            else:
                sents = sentences(clause.content)
                current_text = article.heading + "\n"
                current_sents = []
                for s in sents:
                    if len(current_text) + len(s) + 1 > max_chars and current_sents:
                        seq += 1
                        chunks.append(Chunk(
                            cid=_gen_chunk_id(current_text, seq),
                            rid=reg.rid,
                            reg_title=reg.title,
                            version=reg.version,
                            valid_from=reg.valid_from,
                            valid_until=reg.valid_until,
                            aid=article.aid,
                            art_heading=article.heading,
                            clause_ids=[clause.cid],
                            text=current_text.strip(),
                            seq=seq
                        ))
                        overlap_text = " ".join(current_sents[-overlap_sents:]) if overlap_sents > 0 else ""
                        current_text = article.heading + "\n" + overlap_text + (" " if overlap_text else "") + s
                        current_sents = current_sents[-overlap_sents:] + [s] if overlap_sents > 0 else [s]
                    else:
                        current_text += (" " if current_text and not current_text.endswith("\n") else "") + s
                        current_sents.append(s)
                
                if current_text.strip() != article.heading:
                    seq += 1
                    chunks.append(Chunk(
                        cid=_gen_chunk_id(current_text, seq),
                        rid=reg.rid,
                        reg_title=reg.title,
                        version=reg.version,
                        valid_from=reg.valid_from,
                        valid_until=reg.valid_until,
                        aid=article.aid,
                        art_heading=article.heading,
                        clause_ids=[clause.cid],
                        text=current_text.strip(),
                        seq=seq
                    ))
                    
    return chunks
