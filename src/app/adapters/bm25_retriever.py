import math
import re
import unicodedata
from collections import Counter

from app.schemas.p2_schema import CitationEvidence

STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "above",
        "after",
        "again",
        "against",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "by",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "down",
        "during",
        "each",
        "few",
        "for",
        "from",
        "further",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "itself",
        "just",
        "me",
        "more",
        "most",
        "my",
        "myself",
        "no",
        "nor",
        "not",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "other",
        "ought",
        "our",
        "ours",
        "ourselves",
        "out",
        "over",
        "own",
        "same",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "theirs",
        "them",
        "themselves",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "too",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "with",
        "would",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
    }
)


class BM25Retriever:
    """Okapi BM25 implementation for ranking reference passages against query claims."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        normalized = unicodedata.normalize("NFKC", text).lower()
        tokens = re.findall(r"\b[a-zA-Z0-9_\u00C0-\u024F\u1EA0-\u1EF9]+\b", normalized)
        return [token for token in tokens if token not in STOP_WORDS and len(token) > 1]

    def rank(
        self,
        query: str,
        evidence: list[CitationEvidence],
        top_k: int = 12,
        *,
        block_types: set[str] | None = None,
        min_score: float = 0.0,
    ) -> list[CitationEvidence]:
        """Rank candidate passages using BM25 relevance to the query.

        Returns evidence items with `retrieval_score` populated, sorted descending.
        """
        if not evidence:
            return []

        candidates = evidence
        if block_types is not None:
            candidates = [
                item
                for item in evidence
                if str(item.location.get("block_type", "")).lower() in block_types
            ]
        if not candidates:
            return []

        query_tokens = self.tokenize(query)
        if not query_tokens:
            # Fallback if query has no tokens: preserve existing candidate order
            return [
                item.model_copy(update={"retrieval_score": 0.0})
                for item in candidates[:top_k]
            ]

        corpus_tokens = [self.tokenize(item.text) for item in candidates]
        num_docs = len(candidates)
        doc_lengths = [len(tokens) for tokens in corpus_tokens]
        avg_doc_len = sum(doc_lengths) / num_docs if num_docs > 0 else 1.0

        # Calculate document frequencies for query tokens
        doc_freqs: Counter[str] = Counter()
        for tokens in corpus_tokens:
            unique_terms = set(tokens)
            for term in query_tokens:
                if term in unique_terms:
                    doc_freqs[term] += 1

        # Calculate IDF for each query token (Okapi BM25 IDF formula)
        idfs: dict[str, float] = {}
        for term in set(query_tokens):
            df = doc_freqs[term]
            idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
            idfs[term] = max(0.0, idf)

        query_term_freqs = Counter(query_tokens)
        scored: list[tuple[CitationEvidence, float]] = []

        for idx, item in enumerate(candidates):
            tokens = corpus_tokens[idx]
            doc_len = doc_lengths[idx]
            tf_counter = Counter(tokens)
            score = 0.0

            for term, _q_tf in query_term_freqs.items():
                if term not in tf_counter:
                    continue
                d_tf = tf_counter[term]
                idf = idfs.get(term, 0.0)
                numerator = d_tf * (self.k1 + 1.0)
                denominator = d_tf + self.k1 * (1.0 - self.b + self.b * (doc_len / avg_doc_len))
                score += idf * (numerator / denominator)

            if score >= min_score or not query_tokens:
                scored.append((item, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            item.model_copy(update={"retrieval_score": round(score, 4)})
            for item, score in scored[:top_k]
        ]
