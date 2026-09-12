from collections.abc import Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.layer1_model import Claim, DocumentBlock, DocumentSection
from app.schemas.layer1_schema import ExtractedClaim, ParsedBlock, ParsedSection


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_sections(
        self, artifact_id: UUID, sections: Sequence[ParsedSection]
    ) -> dict[str, UUID]:
        section_ids = self._allocate_ids(item.external_id for item in sections)
        section_by_external_id = {item.external_id: item for item in sections}
        paths: dict[str, list[str]] = {}

        def build_path(external_id: str, visiting: set[str]) -> list[str]:
            if external_id in paths:
                return paths[external_id]
            if external_id in visiting:
                raise ValueError(f"Section parent cycle detected at {external_id!r}")
            section = section_by_external_id[external_id]
            parent_external_id = section.parent_external_id
            if parent_external_id is not None and parent_external_id not in section_ids:
                raise ValueError(f"Unknown parent section {parent_external_id!r}")
            parent_path = (
                build_path(parent_external_id, visiting | {external_id})
                if parent_external_id is not None
                else []
            )
            paths[external_id] = parent_path + ([section.title] if section.title else [])
            return paths[external_id]

        models = [
            DocumentSection(
                id=section_ids[item.external_id],
                artifact_id=artifact_id,
                parent_id=(
                    section_ids[item.parent_external_id]
                    if item.parent_external_id is not None
                    else None
                ),
                title=item.title,
                level=item.level,
                ordinal=item.ordinal,
                page_start=item.page_start,
                page_end=item.page_end,
                section_path=build_path(item.external_id, set()),
            )
            for item in sections
        ]
        self.session.add_all(models)
        await self.session.flush()
        return section_ids

    async def save_blocks(
        self,
        artifact_id: UUID,
        parser_version: str,
        blocks: Sequence[ParsedBlock],
        section_ids: dict[str, UUID],
    ) -> dict[str, UUID]:
        block_ids = self._allocate_ids(item.external_id for item in blocks)
        models: list[DocumentBlock] = []
        for item in blocks:
            section_id = None
            if item.section_external_id is not None:
                try:
                    section_id = section_ids[item.section_external_id]
                except KeyError as exc:
                    raise ValueError(
                        f"Unknown section {item.section_external_id!r} for block"
                    ) from exc
            parent_block_id = self._resolve_optional_reference(
                item.parent_block_external_id, block_ids, "parent block"
            )
            caption_block_id = self._resolve_optional_reference(
                item.caption_block_external_id, block_ids, "caption block"
            )
            models.append(
                DocumentBlock(
                    id=block_ids[item.external_id],
                    artifact_id=artifact_id,
                    section_id=section_id,
                    parent_block_id=parent_block_id,
                    caption_block_id=caption_block_id,
                    block_type=item.block_type.value,
                    page_no=item.page_no,
                    reading_order=item.reading_order,
                    text_content=item.text_content,
                    bbox=item.bbox,
                    quads=item.quads,
                    citation_marker_ids=item.citation_marker_ids,
                    confidence=item.confidence,
                    parser_version=parser_version,
                    source_locator=item.source_locator,
                )
            )
        self.session.add_all(models)
        await self.session.flush()
        return block_ids

    async def save_claims(
        self,
        submission_id: UUID,
        claims: Sequence[ExtractedClaim],
        block_ids: dict[str, UUID],
    ) -> dict[str, UUID]:
        claim_ids = self._allocate_ids(item.external_id for item in claims)
        models: list[Claim] = []
        for item in claims:
            try:
                source_block_id = block_ids[item.source_block_external_id]
                context_block_ids = [block_ids[value] for value in item.context_block_external_ids]
            except KeyError as exc:
                raise ValueError(f"Unknown block reference {exc.args[0]!r} in claim") from exc
            models.append(
                Claim(
                    id=claim_ids[item.external_id],
                    submission_id=submission_id,
                    source_block_id=source_block_id,
                    claim_type=item.claim_type.value,
                    text_content=item.text_content,
                    is_atomic=item.is_atomic,
                    is_central=False,
                    qualifiers={"citation_markers": item.citation_markers},
                    source_span=item.source_span,
                    context_block_ids=context_block_ids,
                    impact=1,
                    testability=0,
                    risk=1,
                    extractor_version=item.extractor_version,
                    confidence=item.confidence,
                )
            )
        self.session.add_all(models)
        await self.session.flush()
        return claim_ids

    @staticmethod
    def _allocate_ids(external_ids: Iterable[str]) -> dict[str, UUID]:
        result: dict[str, UUID] = {}
        for external_id in external_ids:
            if external_id in result:
                raise ValueError(f"Duplicate external_id {external_id!r}")
            result[external_id] = uuid4()
        return result

    @staticmethod
    def _resolve_optional_reference(
        external_id: str | None, ids: dict[str, UUID], label: str
    ) -> UUID | None:
        if external_id is None:
            return None
        try:
            return ids[external_id]
        except KeyError as exc:
            raise ValueError(f"Unknown {label} {external_id!r}") from exc
