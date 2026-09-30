from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.adapters.llm_citation_judge import LLMCitationJudge
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.schemas.p2_schema import AtomicClaim, CitationEvidence, CitationVerificationInput


def make_judge() -> LLMCitationJudge:
    return LLMCitationJudge(
        Settings(
            citation_llm_url="https://llm.example/v1",
            citation_llm_model="judge-model",
            citation_judge_max_atomic_claims=8,
        )
    )


def make_input() -> CitationVerificationInput:
    return CitationVerificationInput(
        claim_id=uuid4(),
        text_content="The method reduces latency and increases accuracy.",
        citation_marker="[5]",
        submission_reference_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_decompose_normalizes_atom_ids() -> None:
    judge = make_judge()
    judge.client.request = AsyncMock(
        return_value={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": (
                            '{"atomic_claims": ['
                            '{"text_content":"The method reduces latency."},'
                            '{"text_content":"The method increases accuracy."}'
                            ']}'
                        )
                    },
                }
            ]
        }
    )

    atoms = await judge.decompose(make_input())

    assert [atom.atom_id for atom in atoms] == ["atom-1", "atom-2"]
    assert [atom.text_content for atom in atoms] == [
        "The method reduces latency.",
        "The method increases accuracy.",
    ]


@pytest.mark.asyncio
async def test_judge_rejects_evidence_id_not_supplied() -> None:
    judge = make_judge()
    evidence = CitationEvidence(
        source_type="reference_passage",
        source_id=uuid4(),
        text="The paper reports lower latency.",
        access_status="full_text",
    )
    judge.client.request = AsyncMock(
        return_value={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": (
                            '{"assessments": ['
                            '{"atom_id":"atom-1","verdict":"SUPPORT",'
                            '"confidence":0.9,"rationale":"Claim is supported.",'
                            '"supporting_evidence_ids":["00000000-0000-0000-0000-000000000000"]}'
                            ']}'
                        )
                    },
                }
            ]
        }
    )

    with pytest.raises(AppError) as error:
        await judge.judge(
            make_input(),
            [AtomicClaim(atom_id="atom-1", text_content="The method reduces latency.")],
            [evidence],
        )

    assert error.value.code == ErrorCode.PARSER_ERROR
