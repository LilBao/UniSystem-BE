import hashlib
import re
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference_model import ReferencePassage
from app.schemas.p2_schema import CitationEvidence

DEFAULT_CHUNKER_VERSION = "p2-chunker-1"


class ReferencePassageService:
    """Service to chunk, ingest, and manage ReferencePassages for full-text RAG."""

    def __init__(
        self,
        session: AsyncSession,
        chunker_version: str = DEFAULT_CHUNKER_VERSION,
    ) -> None:
        self.session = session
        self.chunker_version = chunker_version

    async def ingest_passages(
        self,
        reference_document_id: UUID,
        passages_data: list[dict[str, object]],
    ) -> list[ReferencePassage]:
        """Ingest pre-structured passages for a reference document."""
        models: list[ReferencePassage] = []
        for ordinal, p in enumerate(passages_data):
            content = str(p.get("content", "")).strip()
            if not content:
                continue

            raw_section = p.get("section_path")
            section_path: list[str] = (
                [str(x) for x in raw_section] if isinstance(raw_section, list) else []
            )
            raw_page_start = p.get("page_start")
            page_start = raw_page_start if isinstance(raw_page_start, int) else None
            raw_page_end = p.get("page_end")
            page_end = raw_page_end if isinstance(raw_page_end, int) else (page_start or 1)
            block_type = str(p.get("block_type", "text")).lower()
            access_level = str(p.get("access_level", "full_text")).lower()
            raw_tokens = p.get("token_count")
            token_count = raw_tokens if isinstance(raw_tokens, int) else len(content.split())
            sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

            model = ReferencePassage(
                id=uuid4(),
                reference_document_id=reference_document_id,
                ordinal=ordinal,
                content=content,
                token_count=token_count,
                section_path=section_path,
                page_start=page_start if isinstance(page_start, int) else None,
                page_end=page_end,
                block_type=block_type,
                access_level=access_level,
                content_sha256=sha256,
                chunker_version=self.chunker_version,
                is_active=True,
            )
            models.append(model)

        if models:
            self.session.add_all(models)
            await self.session.flush()

        return models

    def chunk_markdown_text(
        self,
        reference_document_id: UUID,
        text: str,
        *,
        max_words_per_chunk: int = 250,
        access_level: str = "full_text",
    ) -> list[ReferencePassage]:
        """Chunk markdown text containing section headings into ReferencePassage models."""
        lines = text.splitlines()
        passages: list[ReferencePassage] = []
        current_section: list[str] = []
        current_buffer: list[str] = []
        current_word_count = 0
        ordinal = 0

        def flush_buffer() -> None:
            nonlocal current_buffer, current_word_count, ordinal
            if not current_buffer:
                return
            content = " ".join(current_buffer).strip()
            if content:
                sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
                passages.append(
                    ReferencePassage(
                        id=uuid4(),
                        reference_document_id=reference_document_id,
                        ordinal=ordinal,
                        content=content,
                        token_count=current_word_count,
                        section_path=list(current_section),
                        page_start=1,
                        page_end=1,
                        block_type="text",
                        access_level=access_level,
                        content_sha256=sha256,
                        chunker_version=self.chunker_version,
                        is_active=True,
                    )
                )
                ordinal += 1
            current_buffer = []
            current_word_count = 0

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            heading_match = heading_pattern.match(line_str)
            if heading_match:
                flush_buffer()
                title = heading_match.group(2).strip()
                level = len(heading_match.group(1))
                if level == 1:
                    current_section = [title]
                else:
                    current_section = current_section[: level - 1] + [title]
                continue

            words = line_str.split()
            word_count = len(words)

            if current_word_count + word_count > max_words_per_chunk and current_buffer:
                flush_buffer()

            current_buffer.append(line_str)
            current_word_count += word_count

        flush_buffer()
        return passages

    @staticmethod
    def passages_to_evidence(passages: list[ReferencePassage]) -> list[CitationEvidence]:
        """Convert ReferencePassage models into CitationEvidence DTOs."""
        return [
            CitationEvidence(
                source_type="reference_passage",
                source_id=passage.id,
                text=passage.content,
                location={
                    "page_start": passage.page_start,
                    "page_end": passage.page_end,
                    "section_path": passage.section_path,
                    "block_type": passage.block_type,
                    "ordinal": passage.ordinal,
                },
                access_status=passage.access_level,
                content_sha256=passage.content_sha256,
            )
            for passage in passages
        ]

    async def list_passages_for_document(
        self,
        reference_document_id: UUID,
    ) -> list[ReferencePassage]:
        statement = (
            select(ReferencePassage)
            .where(
                ReferencePassage.reference_document_id == reference_document_id,
                ReferencePassage.is_active.is_(True),
            )
            .order_by(ReferencePassage.ordinal)
        )
        return list((await self.session.scalars(statement)).all())
