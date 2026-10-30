"""Script truy vấn cơ sở dữ liệu và xuất toàn bộ kết quả Layer 1 ra các file JSON.

Cách chạy:
    python tests/layer1/export_layer1_results.py
hoặc chỉ định submission_id cụ thể:
    python tests/layer1/export_layer1_results.py --id <UUID_SUBMISSION>
"""

import argparse
import asyncio
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import SessionFactory

OUTPUT_DIR = Path("tests/layer1/output")


def custom_json_serializer(obj: Any) -> Any:
    """Xử lý các kiểu dữ liệu đặc thù của Postgres (UUID, datetime, Decimal) sang JSON."""
    if isinstance(obj, (UUID, datetime, date)):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} is not JSON serializable")


def save_json(filepath: Path, data: Any) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=custom_json_serializer)
    print(f"  [+] Đã lưu: {filepath.relative_to(Path.cwd()) if filepath.is_relative_to(Path.cwd()) else filepath}")


async def export_layer1(target_submission_id: str | None = None) -> None:
    print("\n" + "=" * 70)
    print("      XUẤT DỮ LIỆU KẾT QUẢ LAYER 1 RA CÁC FILE JSON")
    print("=" * 70)

    async with SessionFactory() as session:
        # 1. Tìm submission_id cần xuất
        if target_submission_id:
            sid_query = text("SELECT id, status, created_at FROM submissions WHERE id = :sid")
            sub_res = await session.execute(sid_query, {"sid": target_submission_id})
            sub = sub_res.mappings().first()
            if not sub:
                print(f"[!] Không tìm thấy submission với ID: {target_submission_id}")
                return
            submission_id = sub["id"]
        else:
            sid_query = text(
                "SELECT id, status, created_at FROM submissions ORDER BY created_at DESC LIMIT 1"
            )
            sub_res = await session.execute(sid_query)
            sub = sub_res.mappings().first()
            if not sub:
                print("[!] Chưa có submission nào trong Database!")
                return
            submission_id = sub["id"]

        print(f">> Đang xuất dữ liệu cho Submission ID: {submission_id} (Trạng thái: {sub['status']})")

        # 2. Lấy thông tin Pipeline Run L1
        run_query = text(
            """
            SELECT * FROM pipeline_runs 
            WHERE submission_id = :sid AND pipeline = 'L1'
            ORDER BY started_at DESC LIMIT 1
            """
        )
        run_res = await session.execute(run_query, {"sid": submission_id})
        run_data = dict(run_res.mappings().first() or {})

        # 3. Lấy thông tin các Artifacts đã upload
        art_query = text(
            """
            SELECT id, kind, version_no, object_uri, media_type, byte_size, sha256, metadata, created_at
            FROM artifacts
            WHERE submission_id = :sid
            ORDER BY kind, version_no
            """
        )
        art_res = await session.execute(art_query, {"sid": submission_id})
        artifacts = [dict(row) for row in art_res.mappings().all()]

        # Tìm report_artifact_id
        report_artifact_id = next(
            (a["id"] for a in artifacts if a["kind"] == "report_pdf"),
            None,
        )

        # 4. Lấy Document Sections (Cây chương mục)
        sections = []
        if report_artifact_id:
            sec_query = text(
                """
                SELECT id, artifact_id, parent_id, title, level, ordinal, page_start, page_end, section_path
                FROM document_sections
                WHERE artifact_id = :art_id
                ORDER BY ordinal
                """
            )
            sec_res = await session.execute(sec_query, {"art_id": report_artifact_id})
            sections = [dict(row) for row in sec_res.mappings().all()]

        # 5. Lấy Document Blocks (Các khối văn bản, bảng, hình ảnh, citation)
        blocks = []
        if report_artifact_id:
            blk_query = text(
                """
                SELECT id, artifact_id, section_id, parent_block_id, caption_block_id,
                       block_type, page_no, reading_order, text_content, bbox,
                       citation_marker_ids, confidence, parser_version, source_locator, created_at
                FROM document_blocks
                WHERE artifact_id = :art_id
                ORDER BY page_no, reading_order
                """
            )
            blk_res = await session.execute(blk_query, {"art_id": report_artifact_id})
            blocks = [dict(row) for row in blk_res.mappings().all()]

        # 6. Lấy Claims (Luận điểm trích xuất từ LLM)
        claim_query = text(
            """
            SELECT id, submission_id, source_block_id, claim_type, text_content,
                   is_atomic, is_central, qualifiers, source_span, context_block_ids,
                   impact, testability, risk, extractor_version, confidence, created_at
            FROM claims
            WHERE submission_id = :sid
            ORDER BY created_at
            """
        )
        claim_res = await session.execute(claim_query, {"sid": submission_id})
        claims = [dict(row) for row in claim_res.mappings().all()]

        # 7. Lấy References (Tài liệu tham khảo bóc tách)
        ref_query = text(
            """
            SELECT id, submission_id, marker, raw_citation, reference_document_id,
                   resolver_status, resolver_confidence, resolver_version, metadata, created_at
            FROM submission_references
            WHERE submission_id = :sid
            ORDER BY marker
            """
        )
        ref_res = await session.execute(ref_query, {"sid": submission_id})
        references = [dict(row) for row in ref_res.mappings().all()]

        # 8. Lấy Code Graph Snapshot
        graph_query = text(
            """
            SELECT id, submission_id, source_artifact_id, graph_artifact_id,
                   source_sha256, graphify_version, schema_version,
                   node_count, edge_count, provenance_summary, created_at
            FROM code_graph_snapshots
            WHERE submission_id = :sid
            ORDER BY created_at DESC LIMIT 1
            """
        )
        graph_res = await session.execute(graph_query, {"sid": submission_id})
        graph_snapshot = dict(graph_res.mappings().first() or {})

    # TỔNG HỢP VÀ GHI RA FILE JSON
    print("\n>> Đang ghi dữ liệu ra các file JSON trong thư mục 'tests/layer1/output/'...")

    # File 1: output.json (Tổng quan kết quả xử lý của Layer 1)
    summary_data = {
        "submission_id": submission_id,
        "submission_status": sub["status"],
        "pipeline_run": {
            "id": run_data.get("id"),
            "status": run_data.get("status"),
            "pipeline": run_data.get("pipeline"),
            "started_at": run_data.get("started_at"),
            "finished_at": run_data.get("finished_at"),
            "input_fingerprint": run_data.get("input_fingerprint"),
            "output_fingerprint": run_data.get("output_fingerprint"),
        },
        "statistics": {
            "total_artifacts": len(artifacts),
            "total_document_sections": len(sections),
            "total_document_blocks": len(blocks),
            "total_extracted_claims": len(claims),
            "total_references": len(references),
            "code_graph_nodes": graph_snapshot.get("node_count"),
            "code_graph_edges": graph_snapshot.get("edge_count"),
        },
        "artifacts_registered": artifacts,
        "code_graph_summary": graph_snapshot,
    }
    save_json(OUTPUT_DIR / "output.json", summary_data)

    # File 2: sections.json (Cấu trúc đề mục văn bản)
    save_json(OUTPUT_DIR / "sections.json", sections)

    # File 3: blocks.json (Các khối nội dung, text, table, figure, bbox)
    save_json(OUTPUT_DIR / "blocks.json", blocks)

    # File 4: claims.json (Danh sách luận điểm do LLM trích xuất)
    save_json(OUTPUT_DIR / "claims.json", claims)

    # File 5: references.json (Danh sách tài liệu tham khảo [1], [2]...)
    save_json(OUTPUT_DIR / "references.json", references)

    # File 6: code_graph_snapshot.json (Metadata snapshot đồ thị mã nguồn)
    save_json(OUTPUT_DIR / "code_graph_snapshot.json", graph_snapshot)

    print("\n" + "=" * 70)
    print(f"[HOÀN TẤT] TẤT CẢ DỮ LIỆU ĐÃ ĐƯỢC XUẤT RA: {OUTPUT_DIR.resolve()}")
    print("=" * 70)
    print("Bạn có thể mở trực tiếp các file trên trong VS Code để xem và kiểm tra chi tiết!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Layer 1 results to JSON files")
    parser.add_argument("--id", type=str, default=None, help="Submission UUID (Mặc định lấy bài mới nhất)")
    args = parser.parse_args()

    asyncio.run(export_layer1(args.id))


if __name__ == "__main__":
    main()
