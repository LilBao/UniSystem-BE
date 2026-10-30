"""Script chạy kiểm thử tích hợp (End-to-End) cho Pipeline 1: Rubric-based Scoring & Summarization.

Cách chạy:
    python tests/layer2/pipeline1/run_test_pipeline1.py --submission-id <UUID>
hoặc:
    python tests/layer2/pipeline1/run_test_pipeline1.py
"""

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import UUID

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BASE_URL = "http://localhost:8000"


def print_step(title: str) -> None:
    print(f"\n{'='*75}\n[BƯỚC] {title}\n{'='*75}")


def print_success(msg: str) -> None:
    print(f"[OK] {msg}")


def print_error(msg: str) -> None:
    print(f"[LỖI] {msg}", file=sys.stderr)


def get_latest_submission_id() -> str | None:
    """Truy vấn database local để lấy submission_id mới nhất đã chạy xong Layer 1."""
    try:
        import asyncio
        from sqlalchemy import text
        from app.core.database import get_session
        from app.core.config import get_settings

        async def _query():
            from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
            settings = get_settings()
            engine = create_async_engine(settings.database_url)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)
            async with session_factory() as session:
                stmt = text(
                    "SELECT submission_id FROM pipeline_runs WHERE pipeline = 'L1' AND status = 'succeeded' "
                    "ORDER BY finished_at DESC LIMIT 1"
                )
                res = await session.execute(stmt)
                row = res.fetchone()
                return str(row[0]) if row else None

        return asyncio.run(_query())
    except Exception as e:
        return None


def run_pipeline1(session: requests.Session, submission_id: str, method: str = "geval", runs: int = 3) -> dict:
    print_step(f"1. Gửi lệnh thực thi Pipeline 1 (submission_id={submission_id})")
    url = f"{BASE_URL}/api/v1/submissions/{submission_id}/pipelines/p1"
    payload = {
        "scoring_method": method,
        "num_runs": runs,
        "variance_threshold": 0.15,
        "temperature": 0.3,
    }
    resp = session.post(url, json=payload, timeout=300)
    if resp.status_code != 200:
        print_error(f"Gửi lệnh thất bại HTTP {resp.status_code}: {resp.text}")
        sys.exit(1)

    data = resp.json()
    print_success(f"Khởi chạy thành công! Pipeline Run ID: {data['id']}")
    print_success(f"Trạng thái hoàn thành: {data['status']}")
    print_success(f"Metrics sơ bộ: {data.get('metrics', {})}")
    return data


def get_pipeline1_results(session: requests.Session, submission_id: str) -> dict:
    print_step("2. Truy vấn chi tiết Báo cáo Đánh giá Rubric & Tóm tắt (Results)")
    url = f"{BASE_URL}/api/v1/submissions/{submission_id}/pipelines/p1/results"
    resp = session.get(url, timeout=30)
    if resp.status_code != 200:
        print_error(f"Truy vấn kết quả thất bại HTTP {resp.status_code}: {resp.text}")
        sys.exit(1)

    result = resp.json()
    if not result:
        print_error("Chưa có kết quả đánh giá cho submission này.")
        sys.exit(1)

    print("\n" + "=" * 75)
    print("                     BÁO CÁO ĐÁNH GIÁ ĐỀ ÁN (PIPELINE 1)")
    print("=" * 75)
    print(f"Submission ID:          {result['submission_id']}")
    print(f"Phương pháp chấm:       {result['scoring_method'].upper()}")
    print(f"Tổng điểm (Raw):        {result['total_raw_score']:.2f} / {result['total_max_score']}")
    print(f"Điểm chuẩn hoá (Norm):  {result['total_normalized_score'] * 100:.1f}%")
    print(f"Phương sai TB:          {result['mean_variance']:.4f}")
    print(f"Yêu cầu GV xem lại:     {'CÓ (Requires Review)' if result['requires_human_review'] else 'KHÔNG (Passed)'}")
    print("-" * 75)
    print("TỔNG QUAN HỌC THUẬT (EXECUTIVE SUMMARY):")
    print(result.get("executive_summary", "N/A"))
    print("-" * 75)

    print("BẢNG TỔNG HỢP ĐIỂM TIÊU CHÍ RUBRIC:")
    print(f"{'Mã':<8} {'Tiêu chí':<42} {'Trọng số':<10} {'Điểm':<12} {'Phương sai':<12}")
    print("-" * 88)
    for crit in result.get("criteria_results", []):
        code = crit["criterion_code"]
        title = crit["criterion_title"][:40]
        score = f"{crit['mean_raw_score']:.2f}/10"
        weight = f"{crit['weight']*100:.0f}%"
        var = f"{crit['variance']:.3f}"
        if crit.get("uncertainty_flag"):
            var += " (!)"
        print(f"{code:<8} {title:<42} {weight:<10} {score:<12} {var:<12}")
    print("=" * 88)

    # 1. Lưu output.json trực tiếp từ response
    output_dir = Path("tests/layer2/pipeline1/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "output.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 2. Tự động chạy export_pipeline1_results để lấy đầy đủ chi tiết từ DB
    try:
        import asyncio
        try:
            from tests.layer2.pipeline1.export_pipeline1_results import export_pipeline1
        except ImportError:
            from export_pipeline1_results import export_pipeline1
        asyncio.run(export_pipeline1(submission_id))
    except Exception as exc:
        print_success(f"Đã lưu kết quả tóm tắt ra: {out_file.resolve()} (Export DB error: {exc})")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy kiểm thử Pipeline 1 (Rubric-based Scoring)")
    parser.add_argument("--submission-id", type=str, help="UUID của submission cần đánh giá")
    parser.add_argument("--method", type=str, default="geval", choices=["geval", "zero_shot", "few_shot"], help="Phương pháp chấm")
    parser.add_argument("--runs", type=int, default=3, help="Số lần chạy Self-Consistency cho G-EVAL")
    args = parser.parse_args()

    sub_id = args.submission_id
    if not sub_id:
        print("[INFO] Không truyền --submission-id, đang tìm submission mới nhất đã hoàn thành Layer 1...")
        sub_id = get_latest_submission_id()
        if not sub_id:
            print_error("Không tìm thấy submission nào đã hoàn thành Layer 1 trong cơ sở dữ liệu local!")
            print_error("Vui lòng chạy Layer 1 trước (python tests/layer1/run_test_layer1.py) hoặc truyền --submission-id <UUID>")
            sys.exit(1)
        print_success(f"Tìm thấy submission_id gần nhất: {sub_id}")

    session = requests.Session()
    run_pipeline1(session, sub_id, method=args.method, runs=args.runs)
    get_pipeline1_results(session, sub_id)


if __name__ == "__main__":
    main()
