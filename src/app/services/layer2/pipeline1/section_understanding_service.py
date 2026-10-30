import re
from typing import Any
from uuid import UUID

from app.models.layer1_model import Claim, DocumentBlock, DocumentSection
from app.models.rubric_model import RubricCriterion
from app.schemas.p1_schema import CriterionEvidenceItem, CriterionEvidencePack


class SectionUnderstandingService:
    """Service chịu trách nhiệm hiểu cấu trúc văn bản và tổng hợp Evidence Pack cho từng tiêu chí Rubric."""

    def __init__(self, max_evidence_items: int = 15) -> None:
        self.max_evidence_items = max_evidence_items

    def build_evidence_packs(
        self,
        criteria: list[RubricCriterion],
        blocks: list[DocumentBlock],
        sections: list[DocumentSection],
        claims: list[Claim],
    ) -> list[CriterionEvidencePack]:
        """Tạo Evidence Pack cho toàn bộ danh sách tiêu chí Rubric."""
        section_map: dict[UUID, DocumentSection] = {s.id: s for s in sections}
        
        packs: list[CriterionEvidencePack] = []
        for criterion in criteria:
            pack = self.build_single_pack(criterion, blocks, section_map, claims)
            packs.append(pack)
        return packs

    def build_single_pack(
        self,
        criterion: RubricCriterion,
        blocks: list[DocumentBlock],
        section_map: dict[UUID, DocumentSection],
        claims: list[Claim],
    ) -> CriterionEvidencePack:
        """Thu thập và xếp hạng evidence liên quan nhất cho một tiêu chí cụ thể."""
        criterion_keywords = self._extract_keywords(
            f"{criterion.title} {criterion.description} {criterion.code} {self._format_rules(criterion.grading_rules)}"
        )

        scored_items: list[tuple[float, CriterionEvidenceItem]] = []

        # 1. Quét Document Blocks từ Layer 1
        for block in blocks:
            if not block.text_content or len(block.text_content.strip()) < 15:
                continue

            section = section_map.get(block.section_id) if block.section_id else None
            section_title = section.title if section else None

            # Tính điểm liên quan (keyword overlap + section bias)
            score = self._compute_relevance(
                criterion_keywords,
                block.text_content,
                section_title,
                block.block_type,
            )

            if score > 0.1:
                item = CriterionEvidenceItem(
                    block_id=block.id,
                    claim_id=None,
                    text=block.text_content.strip(),
                    section_title=section_title,
                    page_no=block.page_no,
                    block_type=block.block_type or "text",
                    relevance_score=round(score, 4),
                )
                scored_items.append((score, item))

        # 2. Quét Claims từ Layer 1
        for claim in claims:
            if not claim.text_content or len(claim.text_content.strip()) < 10:
                continue

            claim_score = self._compute_relevance(
                criterion_keywords,
                claim.text_content,
                claim.claim_type,
                "claim",
            )

            if claim_score > 0.15:
                item = CriterionEvidenceItem(
                    block_id=claim.source_block_id,
                    claim_id=claim.id,
                    text=f"[Claim: {claim.claim_type}] {claim.text_content.strip()}",
                    section_title=f"Layer 1 Claim ({claim.claim_type})",
                    page_no=None,
                    block_type="claim",
                    relevance_score=round(claim_score, 4),
                )
                scored_items.append((claim_score, item))

        # Sắp xếp theo độ liên quan giảm dần
        scored_items.sort(key=lambda x: x[0], reverse=True)
        top_items = [item for _, item in scored_items[: self.max_evidence_items]]

        # Nếu không có item nào vượt ngưỡng điểm, lấy các block đầu bài (Abstract / Intro) làm ngữ cảnh
        if not top_items and blocks:
            for block in blocks[: min(5, len(blocks))]:
                if block.text_content:
                    section = section_map.get(block.section_id) if block.section_id else None
                    top_items.append(
                        CriterionEvidenceItem(
                            block_id=block.id,
                            claim_id=None,
                            text=block.text_content.strip(),
                            section_title=section.title if section else None,
                            page_no=block.page_no,
                            block_type=block.block_type or "text",
                            relevance_score=0.1,
                        )
                    )

        # Tổng hợp context thành chuỗi hoàn chỉnh
        synthesized_parts: list[str] = []
        for item in top_items:
            loc = f"Trang {item.page_no}" if item.page_no else "Claim"
            sec = f" | Mục: {item.section_title}" if item.section_title else ""
            synthesized_parts.append(
                f"--- BẰNG CHỨNG [{item.block_type.upper()}] ({loc}{sec}) ---\n{item.text}"
            )

        synthesized_context = "\n\n".join(synthesized_parts)

        return CriterionEvidencePack(
            criterion_id=criterion.id,
            criterion_code=criterion.code,
            criterion_title=criterion.title,
            criterion_description=criterion.description,
            grading_rules=criterion.grading_rules or {},
            min_score=float(criterion.min_score),
            max_score=float(criterion.max_score),
            weight=float(criterion.weight),
            evidence_items=top_items,
            synthesized_context=synthesized_context,
        )

    def _compute_relevance(
        self,
        keywords: set[str],
        content: str,
        section_title: str | None,
        block_type: str,
    ) -> float:
        if not keywords:
            return 0.2

        content_lower = content.lower()
        matches = sum(1 for kw in keywords if kw in content_lower)
        overlap_ratio = matches / len(keywords)

        boost = 0.0
        if section_title:
            sec_lower = section_title.lower()
            if any(kw in sec_lower for kw in keywords):
                boost += 0.25

        if block_type in ("table", "figure", "equation"):
            boost += 0.1

        return min(1.0, overlap_ratio + boost)

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        words = re.findall(r"\b[\w\u00C0-\u1EF9]{3,}\b", text.lower())
        stopwords = {
            "các", "những", "cho", "của", "với", "trong", "được", "nghiệm", "phần",
            "theo", "bằng", "hoặc", "và", "the", "and", "for", "with", "that", "this",
            "from", "score", "điểm", "tiêu", "chí", "báo", "cáo", "sinh", "viên"
        }
        return {w for w in words if w not in stopwords}

    @staticmethod
    def _format_rules(rules: dict[str, Any] | None) -> str:
        if not rules:
            return ""
        return " ".join(f"{k}: {v}" for k, v in rules.items())
