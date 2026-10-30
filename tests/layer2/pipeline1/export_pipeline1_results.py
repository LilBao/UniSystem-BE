"""Script truy vấn cơ sở dữ liệu và xuất toàn bộ kết quả Pipeline 1 (Rubric Scoring) ra thư mục output.

Cách chạy:
    python tests/layer2/pipeline1/export_pipeline1_results.py
hoặc chỉ định submission_id cụ thể:
    python tests/layer2/pipeline1/export_pipeline1_results.py --id <UUID_SUBMISSION>
"""

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import SessionFactory

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path("tests/layer2/pipeline1/output")


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


async def export_pipeline1(target_submission_id: str | None = None) -> None:
    print("\n" + "=" * 75)
    print("      XUẤT DỮ LIỆU KẾT QUẢ PIPELINE 1 (RUBRIC SCORING) RA JSON")
    print("=" * 75)

    async with SessionFactory() as session:
        # 1. Tìm submission_id cần xuất
        if target_submission_id:
            sid_query = text("SELECT id, status, rubric_version_id FROM submissions WHERE id = :sid")
            sub_res = await session.execute(sid_query, {"sid": target_submission_id})
            sub = sub_res.mappings().first()
            if not sub:
                print(f"[!] Không tìm thấy submission với ID: {target_submission_id}")
                return
            submission_id = sub["id"]
        else:
            sid_query = text(
                """
                SELECT s.id, s.status, s.rubric_version_id 
                FROM submissions s
                JOIN pipeline_runs pr ON pr.submission_id = s.id
                WHERE pr.pipeline = 'P1'
                ORDER BY pr.finished_at DESC NULLS LAST LIMIT 1
                """
            )
            sub_res = await session.execute(sid_query)
            sub = sub_res.mappings().first()
            if not sub:
                # Nếu chưa chạy P1, tìm submission mới nhất đã xong L1
                l1_query = text(
                    """
                    SELECT s.id, s.status, s.rubric_version_id 
                    FROM submissions s
                    JOIN pipeline_runs pr ON pr.submission_id = s.id
                    WHERE pr.pipeline = 'L1' AND pr.status = 'succeeded'
                    ORDER BY pr.finished_at DESC LIMIT 1
                    """
                )
                l1_res = await session.execute(l1_query)
                sub = l1_res.mappings().first()
                if not sub:
                    print("[!] Chưa có submission nào đã chạy trong cơ sở dữ liệu!")
                    return
                print(f"[i] Chưa tìm thấy lượt chạy P1, lấy submission mới nhất từ Layer 1: {sub['id']}")
            submission_id = sub["id"]

        print(f">> Đang xuất dữ liệu cho Submission ID: {submission_id}")

        # 2. Lấy thông tin Pipeline Run P1
        run_query = text(
            """
            SELECT * FROM pipeline_runs 
            WHERE submission_id = :sid AND pipeline = 'P1'
            ORDER BY started_at DESC LIMIT 1
            """
        )
        run_res = await session.execute(run_query, {"sid": submission_id})
        run_data = dict(run_res.mappings().first() or {})

        if not run_data:
            print(f"[!] Submission {submission_id} chưa chạy Pipeline 1! Vui lòng chạy run_test_pipeline1.py trước.")
            return

        # 3. Lấy kết quả PipelineResult tổng thể (subject_type='submission')
        overall_query = text(
            """
            SELECT id, pipeline_run_id, subject_type, subject_id, status, verdict, confidence, reason_codes, result, created_at
            FROM pipeline_results
            WHERE pipeline_run_id = :run_id AND subject_type = 'submission'
            LIMIT 1
            """
        )
        overall_res = await session.execute(overall_query, {"run_id": run_data.get("id")})
        overall_data = dict(overall_res.mappings().first() or {})
        detail_result = overall_data.get("result") or {}

        # 4. Lấy kết quả từng tiêu chí từ pipeline_results (subject_type='rubric_criterion')
        criteria_query = text(
            """
            SELECT pr.id as result_id, pr.subject_id as criterion_id, pr.status, pr.verdict, 
                   pr.confidence, pr.reason_codes, pr.result as criterion_detail,
                   rc.code as criterion_code, rc.title as criterion_title, rc.weight, rc.ordinal
            FROM pipeline_results pr
            JOIN rubric_criteria rc ON rc.id = pr.subject_id
            WHERE pr.pipeline_run_id = :run_id AND pr.subject_type = 'criterion'
            ORDER BY rc.ordinal
            """
        )
        crit_res = await session.execute(criteria_query, {"run_id": run_data.get("id")})
        criteria_results = [dict(row) for row in crit_res.mappings().all()]

        # 5. Lấy điểm chi tiết từng lượt chấm (RubricCriterionScore)
        scores_query = text(
            """
            SELECT rcs.id, rcs.pipeline_result_id, rcs.rubric_criterion_id, rc.code,
                   rcs.run_index, rcs.raw_score, rcs.normalized_score, rcs.rationale, rcs.variance
            FROM rubric_criterion_scores rcs
            JOIN rubric_criteria rc ON rc.id = rcs.rubric_criterion_id
            JOIN pipeline_results pr ON pr.id = rcs.pipeline_result_id
            WHERE pr.pipeline_run_id = :run_id
            ORDER BY rc.ordinal, rcs.run_index
            """
        )
        scores_res = await session.execute(scores_query, {"run_id": run_data.get("id")})
        score_runs = [dict(row) for row in scores_res.mappings().all()]

        # 6. Lấy Evidence Packs (Các bằng chứng trích xuất từ báo cáo/claims để phục vụ chấm điểm)
        ep_query = text(
            """
            SELECT ep.id as pack_id, ep.rubric_criterion_id, rc.code as criterion_code,
                   ep.coverage, ep.created_at,
                   ei.id as item_id, ei.source_type, ei.text_snapshot, ei.location, ei.retrieval_score
            FROM evidence_packs ep
            JOIN rubric_criteria rc ON rc.id = ep.rubric_criterion_id
            LEFT JOIN evidence_items ei ON ei.evidence_pack_id = ep.id
            WHERE ep.pipeline_run_id = :run_id
            ORDER BY rc.ordinal
            """
        )
        ep_res = await session.execute(ep_query, {"run_id": run_data.get("id")})
        evidence_rows = [dict(row) for row in ep_res.mappings().all()]

    # TỔNG HỢP VÀ GHI RA FILE JSON
    print("\n>> Đang ghi dữ liệu ra thư mục 'tests/layer2/pipeline1/output/'...")

    # File 1: summary.json (Tổng quan điểm số, phương sai, executive summary)
    summary_data = {
        "submission_id": submission_id,
        "pipeline_run": {
            "id": run_data.get("id"),
            "status": run_data.get("status"),
            "code_version": run_data.get("code_version"),
            "model_version": run_data.get("model_version"),
            "prompt_version": run_data.get("prompt_version"),
            "started_at": run_data.get("started_at"),
            "finished_at": run_data.get("finished_at"),
            "config": run_data.get("config"),
        },
        "evaluation_summary": {
            "scoring_method": detail_result.get("scoring_method"),
            "total_raw_score": detail_result.get("total_raw_score"),
            "total_max_score": detail_result.get("total_max_score", 10.0),
            "total_normalized_score": detail_result.get("total_normalized_score"),
            "mean_variance": detail_result.get("mean_variance"),
            "requires_human_review": detail_result.get("requires_human_review"),
            "status": detail_result.get("status"),
        },
        "executive_summary": detail_result.get("executive_summary"),
        "statistics": {
            "total_criteria_evaluated": len(criteria_results),
            "total_score_runs": len(score_runs),
            "total_evidence_items": len(evidence_rows),
        },
    }
    save_json(OUTPUT_DIR / "summary.json", summary_data)

    # File 2: criteria_scores.json (Chi tiết đánh giá từng tiêu chí Rubric)
    criteria_out = []
    for c in criteria_results:
        detail = c.get("criterion_detail") or {}
        criteria_out.append({
            "code": c.get("criterion_code"),
            "title": c.get("criterion_title"),
            "weight": float(c.get("weight") or 0),
            "mean_raw_score": detail.get("mean_raw_score"),
            "mean_normalized_score": detail.get("mean_normalized_score"),
            "variance": detail.get("variance"),
            "uncertainty_flag": detail.get("uncertainty_flag"),
            "verdict": c.get("verdict"),
            "consensus_rationale": detail.get("consensus_rationale"),
            "strengths": detail.get("strengths", []),
            "weaknesses": detail.get("weaknesses", []),
            "improvement_suggestions": detail.get("improvement_suggestions", []),
            "runs_count": detail.get("runs_count", 0),
        })
    save_json(OUTPUT_DIR / "criteria_scores.json", criteria_out)

    # File 3: score_runs_detail.json (Từng lượt chấm CoT của AI)
    save_json(OUTPUT_DIR / "score_runs_detail.json", score_runs)

    # File 4: evidence_packs.json (Các bằng chứng trích xuất làm căn cứ chấm điểm)
    save_json(OUTPUT_DIR / "evidence_packs.json", evidence_rows)

    print("\n" + "=" * 75)
    print(f"[HOÀN TẤT] TẤT CẢ DỮ LIỆU ĐÃ ĐƯỢC XUẤT RA: {OUTPUT_DIR.resolve()}")
    print("=" * 75)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Pipeline 1 results to JSON files")
    parser.add_argument("--id", type=str, default=None, help="Submission UUID (Mặc định lấy bài mới nhất)")
    args = parser.parse_args()

    asyncio.run(export_pipeline1(args.id))


if __name__ == "__main__":
    main()
