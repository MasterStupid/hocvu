"""Offline CPU benchmark; optionally compare against a saved pre-change source.

python scripts/benchmark_searcher.py --baseline-source /tmp/searcher-before.py

Uses bundled demo data only. Does not load embeddings, call providers, open
session stores, or write application data. Timings cover warmed retrieval and
evidence checks, not complete HTTP/LLM/TTS requests.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.corpus import build_corpus, build_qa
from core.generator import Generator
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation


TIMING_QUERIES = (
    "Điều kiện bảo lưu kết quả học tập?",
    "Sinh viên cần bao nhiêu tín chỉ để tốt nghiệp?",
    "diem ren luyen co anh huong den hoc bong khong?",
    "Ký túc xá có wifi không?",
)
EDGE_QUERIES = (
    "giai bong da", "điểm danh", "điểm rèn luyện", "hoc bong",
    "Wifi ở ký túc xá thế nào?", "bao luu", "", "Xin chào",
)


# Class-level helpers that the current Generator looks up on HybridSearcher.
GENERATOR_HELPERS = (
    "_chunk_features", "_raw_words", "_credit_quantity_topic", "_query_form",
    "_is_non_specific", "_question_focus", "has_specific_evidence",
)


def backfill_generator_helpers(searcher_type):
    """Let an older baseline searcher run under the current Generator.

    Only helpers the baseline lacks are borrowed (bound to the current class);
    anything the baseline defines itself is left untouched.
    """
    missing = [name for name in GENERATOR_HELPERS if not hasattr(searcher_type, name)]
    for name in missing:
        setattr(searcher_type, name, getattr(HybridSearcher, name))
    return missing


def snapshot(searcher, queries):
    # Generator imports its classmethod helpers locally from core.searcher.
    with patch("core.searcher.HybridSearcher", type(searcher)):
        generator = Generator(searcher.config)
        results = []
        for query in queries:
            hits = searcher.search(query, top_k=20, ref_date="2026-10-20")
            ranked = searcher.rerank_by_coverage(query, hits)
            answer, references = generator.generate(query, ranked)
            results.append({
                "query": query,
                "search": [(hit.chunk.cid, hit.score, hit.bm25, hit.vec) for hit in hits],
                "reranked": [hit.chunk.cid for hit in ranked],
                "coverage": searcher.lexical_coverage(query, ranked),
                "specific": searcher.has_specific_evidence(query, ranked),
                "support": [tuple(sorted(forms) for forms in searcher._evidence_support(query, hit.chunk)) for hit in ranked],
                "answer": answer, "references": [ref.to_dict() for ref in references],
            })
        return results


def measure(searcher_type, config, chunks, rounds, iterations):
    searcher = searcher_type(config)
    start = time.process_time()
    searcher.build([replace(chunk) for chunk in chunks])
    build_ms = (time.process_time() - start) * 1000

    def workload():
        for _ in range(iterations):
            for query in TIMING_QUERIES:
                hits = searcher.rerank_by_coverage(
                    query, searcher.search(query, top_k=20, ref_date="2026-10-20"),
                )
                searcher.lexical_coverage(query, hits)
                searcher.has_specific_evidence(query, hits)

    workload()
    timings = []
    for _ in range(rounds):
        start = time.process_time()
        workload()
        timings.append((time.process_time() - start) * 1000 / (iterations * len(TIMING_QUERIES)))
    return searcher, {
        "build_cpu_ms": round(build_ms, 3),
        "median_cpu_ms_per_query": round(median(timings), 3),
        "round_cpu_ms_per_query": [round(value, 3) for value in timings],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    if args.rounds < 1 or args.iterations < 1:
        parser.error("rounds and iterations must be positive")
    config = AppConfig(semantic_enabled=False)
    corpus = build_corpus(config.seed)
    chunks = [chunk for reg in corpus for chunk in split_regulation(reg, config.max_chunk_chars, config.overlap_sents)]
    queries = list(dict.fromkeys([
        *TIMING_QUERIES, *EDGE_QUERIES, *(item.question for item in build_qa(corpus, config.seed)),
    ]))
    report = {
        "corpus": "bundled demo", "chunks": len(chunks), "semantic": False,
        "rounds": args.rounds, "queries_per_round": len(TIMING_QUERIES) * args.iterations,
    }
    baseline = None
    if args.baseline_source:
        spec = importlib.util.spec_from_file_location("core._benchmark_baseline", args.baseline_source)
        if spec is None or spec.loader is None:
            parser.error("baseline source must be an importable Python file")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        borrowed = backfill_generator_helpers(module.HybridSearcher)
        if borrowed:
            report["baseline_borrowed_helpers"] = borrowed
        baseline, report["before"] = measure(module.HybridSearcher, config, chunks, args.rounds, args.iterations)
    current, report["after"] = measure(HybridSearcher, config, chunks, args.rounds, args.iterations)
    if baseline is not None:
        if snapshot(current, queries) != snapshot(baseline, queries):
            raise SystemExit("FAILED: retrieval, evidence, answer or citation parity changed")
        report["parity_queries"] = len(queries)
        report["identical_results"] = True
        report["cpu_reduction_percent"] = round(
            100 * (1 - report["after"]["median_cpu_ms_per_query"] / report["before"]["median_cpu_ms_per_query"]), 2,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
