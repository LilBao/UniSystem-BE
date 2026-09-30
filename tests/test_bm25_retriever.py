from uuid import uuid4

from app.adapters.bm25_retriever import BM25Retriever
from app.schemas.p2_schema import CitationEvidence


def make_evidence(text: str, block_type: str = "text") -> CitationEvidence:
    return CitationEvidence(
        source_type="reference_passage",
        source_id=uuid4(),
        text=text,
        location={"block_type": block_type},
        access_status="full_text",
    )


def test_bm25_ranks_relevant_passage_highest() -> None:
    retriever = BM25Retriever()
    target = make_evidence(
        "Our model achieves a 95.4% F1 score on the biomedical named entity recognition task."
    )
    distractor_1 = make_evidence(
        "In this section we review the historical developments of relational databases."
    )
    distractor_2 = make_evidence(
        "Operating system scheduling algorithms optimize CPU utilization and throughput."
    )

    ranked = retriever.rank(
        query="The proposed approach achieves 95.4% F1 score in named entity recognition.",
        evidence=[distractor_1, distractor_2, target],
        top_k=2,
    )

    assert len(ranked) == 2
    assert ranked[0].source_id == target.source_id
    assert ranked[0].retrieval_score is not None
    assert ranked[0].retrieval_score > 0.0
    assert ranked[0].retrieval_score > (ranked[1].retrieval_score or 0.0)


def test_bm25_filters_by_block_type() -> None:
    retriever = BM25Retriever()
    text_item = make_evidence("Transformer architecture with self-attention.", block_type="text")
    table_item = make_evidence(
        "Table 1 shows accuracy across various architectures.", block_type="table"
    )

    ranked = retriever.rank(
        query="Transformer self-attention architecture",
        evidence=[text_item, table_item],
        top_k=5,
        block_types={"table"},
    )

    assert len(ranked) == 1
    assert ranked[0].source_id == table_item.source_id


def test_bm25_handles_empty_inputs_safely() -> None:
    retriever = BM25Retriever()
    item = make_evidence("Some academic content.")

    assert retriever.rank(query="", evidence=[item]) == [
        item.model_copy(update={"retrieval_score": 0.0})
    ]
    assert retriever.rank(query="anything", evidence=[]) == []
