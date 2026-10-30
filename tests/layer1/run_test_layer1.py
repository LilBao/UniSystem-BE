"""Script chạy kiểm thử tích hợp (End-to-End) cho Layer 1.

Cách chạy:
    python tests/layer1/run_test_layer1.py
hoặc:
    python tests/layer1/run_test_layer1.py --dir "D:/HT/HK-261-2027/DACN/tailieu"
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "http://localhost:8000"
DEFAULT_DATA_DIR = Path(r"D:\HT\HK-261-2027\DACN\tailieu")

# Dữ liệu hạt giống mặc định khớp với seed_local.sql
DEFAULT_PROJECT_ID = "00000000-0000-4000-8000-000000000003"
DEFAULT_GROUP_ID = "00000000-0000-4000-8000-000000000004"
DEFAULT_USER_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_RUBRIC_ID = "00000000-0000-4000-8000-000000000005"


def print_step(title: str) -> None:
    print(f"\n{'='*70}\n[BƯỚC] {title}\n{'='*70}")


def print_success(msg: str) -> None:
    print(f"[OK] {msg}")


def print_error(msg: str) -> None:
    print(f"[LỖI] {msg}", file=sys.stderr)


def find_test_files(target_dir: Path) -> tuple[Path, Path]:
    if not target_dir.exists():
        raise FileNotFoundError(f"Thư mục '{target_dir}' không tồn tại trên máy tính!")

    pdfs = list(target_dir.glob("*.pdf"))
    zips = list(target_dir.glob("*.zip"))

    if not pdfs:
        raise FileNotFoundError(f"Không tìm thấy file .pdf nào trong thư mục '{target_dir}'")
    if not zips:
        raise FileNotFoundError(f"Không tìm thấy file .zip nào trong thư mục '{target_dir}'")

    pdf_file = pdfs[0]
    zip_file = zips[0]
    print_success(f"Tìm thấy PDF: {pdf_file.name} ({pdf_file.stat().st_size / 1024 / 1024:.2f} MB)")
    print_success(f"Tìm thấy ZIP: {zip_file.name} ({zip_file.stat().st_size / 1024 / 1024:.2f} MB)")
    return pdf_file, zip_file


def create_submission(session: requests.Session, attempt_no: int) -> str:
    print_step(f"1. Khởi tạo Submission (attempt_no={attempt_no})")
    url = f"{BASE_URL}/api/v1/submissions"
    payload = {
        "project_id": DEFAULT_PROJECT_ID,
        "group_id": DEFAULT_GROUP_ID,
        "submitted_by_user_id": DEFAULT_USER_ID,
        "rubric_version_id": DEFAULT_RUBRIC_ID,
        "attempt_no": attempt_no,
    }

    resp = session.post(url, json=payload, timeout=30)
    if resp.status_code == 409:
        print(f"(!) attempt_no={attempt_no} đã tồn tại, thử lại với attempt_no={attempt_no + 1}...")
        return create_submission(session, attempt_no + 1)

    resp.raise_for_status()
    data = resp.json()
    submission_id = data["id"]
    print_success(f"Tạo thành công submission_id: {submission_id}")
    return submission_id


def upload_file(
    session: requests.Session,
    submission_id: str,
    file_path: Path,
    kind: str,
    mime_type: str,
) -> dict[str, Any]:
    print_step(f"2. Upload tệp '{file_path.name}' ({kind}) lên Cloudinary")
    url = f"{BASE_URL}/api/v1/submissions/{submission_id}/files"

    with file_path.open("rb") as f:
        files = {"file": (file_path.name, f, mime_type)}
        data = {"kind": kind}
        resp = session.post(url, files=files, data=data, timeout=300)

    resp.raise_for_status()
    upload_data = resp.json()
    print_success(f"Upload thành công {kind}!")
    print(f"    - object_uri: {upload_data['object_uri']}")
    print(f"    - sha256    : {upload_data['sha256']}")
    print(f"    - byte_size : {upload_data['byte_size']} bytes")
    return upload_data


def register_artifact(
    session: requests.Session,
    submission_id: str,
    upload_data: dict[str, Any],
) -> None:
    kind = upload_data["kind"]
    print(f">> Đang đăng ký artifact ({kind}) vào Database...")
    url = f"{BASE_URL}/api/v1/submissions/{submission_id}/artifacts"
    payload = {
        "kind": kind,
        "version_no": 1,
        "object_uri": upload_data["object_uri"],
        "media_type": upload_data["media_type"],
        "byte_size": upload_data["byte_size"],
        "sha256": upload_data["sha256"],
        "metadata": {},
    }

    resp = session.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    print_success(f"Đăng ký artifact '{kind}' vào DB thành công!")


def trigger_layer1(session: requests.Session, submission_id: str) -> dict[str, Any]:
    print_step("3. Kích hoạt Layer 1 xử lý (POST /submit)")
    print(">> Đang chạy đồng thời OCR tài liệu (Baidu) và Phân tích mã nguồn (Graphify)...")
    print(">> Quá trình này có thể mất từ 30s đến vài phút. Vui lòng đợi...")

    start_time = time.time()
    url = f"{BASE_URL}/api/v1/submissions/{submission_id}/submit"
    resp = session.post(url, timeout=3600)  # timeout 30 phút
    resp.raise_for_status()

    elapsed = time.time() - start_time
    result = resp.json()
    print_success(f"Layer 1 HOÀN TẤT trong {elapsed:.1f} giây!")
    print("\n[KẾT QUẢ RUN]:")
    print(f"    - Run ID        : {result.get('id')}")
    print(f"    - Trạng thái    : {result.get('status')}")
    print(f"    - Pipeline      : {result.get('pipeline')}")
    print(f"    - Fingerprint   : {result.get('input_fingerprint')}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Layer 1 End-to-End Runner")
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Thư mục chứa file test PDF và ZIP",
    )
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("   CHƯƠNG TRÌNH KIỂM THỬ TÍCH HỢP LAYER 1 (UNISYSTEM BE)   ")
    print("=" * 70)

    try:
        pdf_file, zip_file = find_test_files(args.dir)
    except Exception as exc:
        print_error(str(exc))
        sys.exit(1)

    with requests.Session() as session:
        # Kiểm tra backend health
        try:
            health = session.get(f"{BASE_URL}/health", timeout=5)
            health.raise_for_status()
            print_success(f"Kết nối tới Backend thành công ({BASE_URL})")
        except Exception as exc:
            print_error(f"Không thể kết nối tới {BASE_URL}. Hãy chắc chắn Uvicorn đang chạy! Lỗi: {exc}")
            sys.exit(1)

        try:
            # 1. Tạo submission
            submission_id = create_submission(session, attempt_no=1)

            # 2. Upload & đăng ký PDF
            pdf_data = upload_file(session, submission_id, pdf_file, "report_pdf", "application/pdf")
            register_artifact(session, submission_id, pdf_data)

            # 3. Upload & đăng ký ZIP
            zip_data = upload_file(session, submission_id, zip_file, "source_archive", "application/zip")
            register_artifact(session, submission_id, zip_data)

            # 4. Kích hoạt Layer 1
            trigger_layer1(session, submission_id)

            print("\n" + "=" * 70)
            print("[HOÀN TẤT] LAYER 1 ĐÃ CHẠY THÀNH CÔNG VÀ LƯU DỮ LIỆU ĐẦY ĐỦ VÀO DATABASE!")
            print("=" * 70)

        except requests.HTTPError as exc:
            print_error(f"HTTP Error: {exc.response.status_code} - {exc.response.text}")
            sys.exit(1)
        except Exception as exc:
            print_error(f"Lỗi không mong muốn: {exc}")
            sys.exit(1)


if __name__ == "__main__":
    main()
