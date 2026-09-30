# UniSystem Backend

> FastAPI backend cho pipeline tự động đánh giá đồ án (capstone project).
> **Layer 1 (L1)** nhận báo cáo PDF + source ZIP, trả về cấu trúc tài liệu, danh sách claims và code graph.

---

## Mục lục

- [Tổng quan](#tổng-quan)
- [Kiến trúc](#kiến-trúc)
- [Yêu cầu](#yêu-cầu)
- [Quick Start](#quick-start)
- [Cấu hình](#cấu-hình)
- [Chạy đầy đủ Layer 1](#chạy-đầy-đủ-layer-1)
- [Seed dữ liệu test](#seed-dữ-liệu-test)
- [Test API](#test-api)
- [Layer 1 — Luồng xử lý](#layer-1--luồng-xử-lý)
- [Xử lý lỗi](#xử-lý-lỗi)
- [Kiểm tra & Linting](#kiểm-tra--linting)
- [Quy ước phát triển](#quy-ước-phát-triển)

---

## Tổng quan

UniSystem Backend cung cấp REST API để:

1. Nhận submission (PDF báo cáo + ZIP source code) từ sinh viên.
2. Chạy **Layer 1 pipeline** — OCR → phân tích tài liệu → trích xuất claims → phân tích code graph.
3. Chạy **Pipeline 2** — resolve reference → tách atomic claim → đánh giá evidence bằng LLM → lưu verdict.
4. Lưu kết quả vào PostgreSQL và Cloudinary để các layer sau tiêu thụ.

Pipeline hiện chạy **đồng bộ trong HTTP request** (chưa có queue). Xem [Layer 1 — Luồng xử lý](#layer-1--luồng-xử-lý) để biết chi tiết.

---

## Kiến trúc

### Cấu trúc thư mục

```
Backend/
├── db/migrations/
│   └── 001_initial_schema.sql   # DDL PostgreSQL (33 bảng)
├── src/app/
│   ├── main.py                  # FastAPI app, routers, health check
│   ├── dependencies.py          # Composition root — nối service/repo/adapter
│   ├── controllers/             # HTTP routes & request/response
│   ├── services/                # Business logic & Pipeline orchestrators
│   │   ├── common/              # Submission, upload, cache lifecycle
│   │   ├── layer1/              # L1: OCR layout, claims LLM, code graph, references
│   │   ├── layer2/              # L2: 4 pipelines phân tích độc lập
│   │   │   ├── pipeline1/       # P1: Chấm điểm Rubric & G-EVAL
│   │   │   ├── pipeline2/       # P2: Thẩm định trích dẫn (Citation Verification)
│   │   │   ├── pipeline3/       # P3: Đối soát Code - Báo cáo (Graphify + CASCADE)
│   │   │   └── pipeline4/       # P4: Tín hiệu văn bản AI (Binoculars/VietBinoculars)
│   │   └── layer3/              # L3: Tổng hợp evidence, rule & collaborative judge
│   ├── adapters/                # PaddleOCR-VL, LLM HTTP, ZIP, Graphify CLI
│   ├── repositories/            # ORM + Cloudinary storage
│   ├── models/                  # SQLAlchemy ORM models
│   ├── schemas/                 # Pydantic DTOs
│   ├── core/                    # Settings, DB session, error codes
│   └── workers/                 # (chưa có queue consumer)
├── tests/
├── .env.example
├── docker-compose.yml           # Redis, Qdrant, API container
├── Dockerfile
├── requirements.txt
├── requirements-ocr.txt         # PaddleOCR (cài riêng)
└── pyproject.toml
```

### Luồng phụ thuộc

```
HTTP → Controller → Service → Repository → PostgreSQL / Cloudinary
                        └──→ Adapter   → PaddleOCR-VL (local) / LLM / ZIP / Graphify
```

### Trách nhiệm các tầng

| Tầng | Trách nhiệm |
|------|-------------|
| **Controller** | Parse request, validate schema, gọi service, trả HTTP response |
| **Service** | Business logic, kiểm tra tiền điều kiện, điều phối thứ tự xử lý |
| **Repository** | Đọc/ghi ORM; upload/download Cloudinary |
| **Adapter** | Bọc công cụ ngoài (OCR, LLM, Docker, ZIP) — dễ swap khi test |
| **Model** | SQLAlchemy mapping; phải khớp migration SQL |
| **Schema** | Pydantic DTO cho HTTP I/O và dữ liệu nội bộ L1 |
| **dependencies.py** | Khởi tạo toàn bộ dependency — controller không tự `new` |

> **Tại sao có Adapter?** Service không chứa chi tiết HTTP, Docker hay SDK. Swap công cụ hoặc dùng fake adapter trong test mà không ảnh hưởng business logic.

### Thứ tự đọc code

1. [`main.py`](src/app/main.py) → [`submission_controller.py`](src/app/controllers/submission_controller.py)
2. [`dependencies.py`](src/app/dependencies.py)
3. [`layer1_service.py`](src/app/services/layer1_service.py)
4. Ba service con: report preprocessing, claim extraction, source code preprocessing
5. Các adapter tương ứng → schemas → repositories

---

## Yêu cầu

| Công cụ | Phiên bản |
|---------|-----------|
| Python | 3.12+ |
| Docker Desktop (Linux containers) | mới nhất |
| Docker Compose | V2+ |
| PostgreSQL | 16 (local hoặc container) |
| curl.exe | hỗ trợ `--fail-with-body` |

---

## Quick Start

> **Shell**: PowerShell, chạy tại thư mục `Backend/`.

### 1. Tạo môi trường

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps

# Tạo .env từ template (chỉ lần đầu)
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

> Gọi trực tiếp Python trong `.venv` — không cần `activate` hay đổi `ExecutionPolicy`.

### 2. Khởi chạy API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir src --reload
```

### 3. Kiểm tra health

```powershell
curl.exe -i http://localhost:8000/health
# Kỳ vọng: HTTP 200  {"status": "ok"}
```

| URL | Mô tả |
|-----|-------|
| `http://localhost:8000/health` | Health check |
| `http://localhost:8000/docs` | Swagger UI |
| `http://localhost:8000/openapi.json` | OpenAPI schema |

> Health check chỉ xác nhận app đang chạy, **không** ping DB, Cloudinary, OCR hay Docker.
> Sau khi sửa `.env`, phải restart API vì `Settings` được cache.

---

## Cấu hình

Nguồn gốc các biến: [`config.py`](src/app/core/config.py). Điền vào `.env` (không trùng tên biến):

```dotenv
# ── Cloudinary ──────────────────────────────────────────
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
CLOUDINARY_FOLDER=dacn
CLOUDINARY_DELIVERY_TYPE=authenticated

# ── PaddleOCR Official API ──────────────────────────────
OCR_PROVIDER=paddle_official
PADDLEOCR_UPLOAD_MODE=file
PADDLEOCR_ACCESS_TOKEN=your_ai_studio_access_token
PADDLEOCR_MODEL=PaddleOCR-VL-1.6
PADDLEOCR_JOB_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLEOCR_CONNECT_TIMEOUT_SECONDS=30
PADDLEOCR_REQUEST_TIMEOUT_SECONDS=300
PADDLEOCR_UPLOAD_TIMEOUT_SECONDS=60
PADDLEOCR_POLL_TIMEOUT_SECONDS=1800
PADDLEOCR_POLL_INTERVAL_SECONDS=5
PADDLEOCR_RETRY_ATTEMPTS=4
PADDLEOCR_RETRY_BACKOFF_SECONDS=2
PADDLEOCR_PAGE_CONCURRENCY=3
OCR_MAX_OUTPUT_BYTES=33554432

# ── LLM (claim extraction) ──────────────────────────────
CLAIM_LLM_URL=https://your-provider.example/v1/
CLAIM_LLM_API_KEY=your_llm_key
CLAIM_LLM_MODEL=your_model_name
CLAIM_MAX_INPUT_CHARS=24000

# ── LLM (Pipeline 2 citation verification) ─────────────
# Nếu bỏ trống, P2 tái sử dụng CLAIM_LLM_URL/API_KEY/MODEL.
CITATION_LLM_URL=https://your-provider.example/v1/
CITATION_LLM_API_KEY=your_llm_key
CITATION_LLM_MODEL=your_model_name
CITATION_JUDGE_MAX_INPUT_CHARS=24000
CITATION_JUDGE_MAX_EVIDENCE_ITEMS=12
CITATION_JUDGE_MAX_ATOMIC_CLAIMS=8
CITATION_JUDGE_CONFIDENCE_THRESHOLD=0.8

# ── Graphify local CLI ──────────────────────────────────
GRAPHIFY_VERSION=0.9.55
GRAPHIFY_TIMEOUT_SECONDS=1800
GRAPHIFY_MAX_WORKERS=4
```

### Contract của từng dependency

| Dependency | Yêu cầu |
|------------|---------|
| **Cloudinary** | Upload/download raw asset `authenticated`; lưu `object_uri`; verify SHA-256 & kích thước khi tải |
| **OCR (official API)** | `POST /api/v2/ocr/jobs` bằng multipart, sau đó poll `GET /jobs/{jobId}` mỗi 5 giây |
| **OCR output** | Tải JSONL từ `resultUrl.jsonUrl`; lấy `layoutParsingResults[].prunedResult.parsing_res_list` |
| **LLM** | Base URL + `chat/completions`; `response_format=json_object`; model cấu hình qua env |
| **LLM output** | `choices[0].finish_reason == "stop"`; `message.content` là JSON theo `ExtractedClaim` schema |
| **Citation LLM** | Cùng OpenAI-compatible contract; tách atomic claim và trả verdict cho từng atom, chỉ dùng evidence được cung cấp |
| **Graphify CLI** | Chạy `python -m graphify extract <source> --code-only --out <output>`; đọc `graphify-out/graph.json` |

> PDF được gửi lên dịch vụ PaddleOCR của Baidu. Không dùng cách này cho tài liệu không được phép đưa ra dịch vụ bên ngoài.

#### Biến đã lỗi thời (có thể xóa khỏi `.env`)

`PARSER_URL`, `PARSER_API_KEY`, `PARSER_VERSION`, `PADDLEOCR_VERSION` — không còn dùng cho OCR.
`PARSER_MAX_RESPONSE_BYTES` giới hạn kích thước `graph.json`; Graphify dùng timeout riêng.

---

## Chạy đầy đủ Layer 1

### Cấu hình PaddleOCR Official API

Luồng submit kiểm tra checksum PDF rồi gửi `fileUrl` là link Cloudinary có chữ ký,
có thời hạn bằng tổng timeout request + timeout poll + 5 phút. Nếu PaddleOCR trả
HTTP 408 khi tải URL, backend upload nguyên PDF bằng multipart theo mẫu chính thức.
Chỉ khi upload nguyên file vẫn lỗi sau các lần retry, backend mới tách PDF thành từng
trang, upload lần lượt và ghép kết quả theo thứ tự ban đầu. Không ghi link có chữ ký
vào log. Giới hạn từ nhà cung cấp: PDF tối đa 200 MB/1000 trang; một ảnh tối đa 10 MB.

Đặt `PADDLEOCR_UPLOAD_MODE=pages` để bỏ qua hai bước thử URL/nguyên PDF và chạy
thẳng fallback nhiều trang song song. Cấu hình này phù hợp với mạng đã xác nhận hai
cách gửi nguyên tài liệu đều thất bại.

1. Đăng nhập AI Studio và lấy token tại [Access Token](https://aistudio.baidu.com/account/accessToken).
2. Dán token vào `PADDLEOCR_ACCESS_TOKEN` trong `.env`. Không commit `.env` hoặc gửi token lên Git.
3. Cài dependency thông thường bằng `pip install -r requirements.txt`, sau đó restart API.

Backend dùng `requests.Session` đúng theo mẫu chính thức và chạy toàn bộ upload/poll trong threadpool để không chặn event loop của FastAPI. Request multipart gửi `model=PaddleOCR-VL-1.6` và `optionalPayload` giống mẫu. Máy local không tải model và không cần cài `paddleocr` hay `paddlepaddle`; tốc độ phụ thuộc kích thước PDF, hàng đợi và quota của dịch vụ.

#### Tùy chọn chạy local

Nếu cần giữ tài liệu hoàn toàn trên máy, đặt `OCR_PROVIDER=local`, cài `pip install -r requirements-ocr.txt`, rồi cấu hình `OCR_DEVICE=cpu` hoặc `gpu:0`. Lần đầu local vẫn phải tải model và CPU có thể rất chậm.

### Chuẩn bị Graphify CLI

```powershell
# Đã được khai báo trong requirements.txt
pip install -r requirements.txt
python -m graphify --version
```

Backend tải ZIP vào thư mục tạm, giải nén an toàn, chỉ sao chép các file source được
hỗ trợ sang thư mục lọc, rồi chạy Graphify với `--code-only`. Kết quả được đọc từ
`graphify-out/graph.json`; backend không thực thi chương trình của sinh viên.

---

## Seed dữ liệu test

Database mới chỉ có schema, chưa có seed. API tạo submission cần: project `open`, rubric `published`, user thuộc group.

> Chạy **một lần** trên database local dev. Chạy lại an toàn (`ON CONFLICT DO NOTHING`).

```powershell
$psql   = "psql"          # hoặc đường dẫn đầy đủ tới psql.exe
$dbUser = "postgres"      # thay theo cấu hình local
$dbName = "unisystem"     # thay theo DATABASE_URL

@'
BEGIN;
INSERT INTO users (id, email, display_name)
VALUES ('00000000-0000-4000-8000-000000000001', 'local-test@example.test', 'Local Test')
ON CONFLICT DO NOTHING;

INSERT INTO courses (id, code, name, term, created_by)
VALUES ('00000000-0000-4000-8000-000000000002', 'DACN-LOCAL', 'Local course', 'HK261',
        '00000000-0000-4000-8000-000000000001')
ON CONFLICT DO NOTHING;

INSERT INTO course_memberships (course_id, user_id, role)
VALUES ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001', 'student')
ON CONFLICT DO NOTHING;

INSERT INTO projects (id, course_id, title, status, created_by)
VALUES ('00000000-0000-4000-8000-000000000003', '00000000-0000-4000-8000-000000000002',
        'Local project', 'open', '00000000-0000-4000-8000-000000000001')
ON CONFLICT DO NOTHING;

INSERT INTO project_groups (id, project_id, name)
VALUES ('00000000-0000-4000-8000-000000000004', '00000000-0000-4000-8000-000000000003', 'Local group')
ON CONFLICT DO NOTHING;

INSERT INTO group_members (group_id, project_id, user_id)
VALUES ('00000000-0000-4000-8000-000000000004', '00000000-0000-4000-8000-000000000003',
        '00000000-0000-4000-8000-000000000001')
ON CONFLICT DO NOTHING;

INSERT INTO rubric_versions (id, project_id, version_no, status, policy_version, published_at, created_by)
VALUES ('00000000-0000-4000-8000-000000000005', '00000000-0000-4000-8000-000000000003',
        1, 'published', '1.0', now(), '00000000-0000-4000-8000-000000000001')
ON CONFLICT DO NOTHING;
COMMIT;
'@ | & $psql -h localhost -p 5432 -U $dbUser -d $dbName -W -v ON_ERROR_STOP=1
```

---

## Test API

> Dùng `curl.exe` (không phải alias `curl` của PowerShell). Cần `curl.exe --version` hỗ trợ `--fail-with-body`.
> Giữ cùng terminal để dùng lại biến `$sid`.

### Bước 1 — Tạo submission

```powershell
$base = 'http://localhost:8000'
$body = @{
    project_id           = '00000000-0000-4000-8000-000000000003'
    group_id             = '00000000-0000-4000-8000-000000000004'
    submitted_by_user_id = '00000000-0000-4000-8000-000000000001'
    rubric_version_id    = '00000000-0000-4000-8000-000000000005'
    attempt_no           = 1
} | ConvertTo-Json -Compress

$result = $body | curl.exe -sS --fail-with-body -X POST "$base/api/v1/submissions" `
    -H 'Content-Type: application/json' --data-binary '@-'
if ($LASTEXITCODE -ne 0) { throw $result }

$submission = $result | ConvertFrom-Json
$sid        = $submission.id
$submission
```

Kỳ vọng: **HTTP 201**, `status=uploaded`. Mỗi bộ `(project, group, attempt_no)` là duy nhất — tăng `attempt_no` cho lần test tiếp.

> Endpoint hỗ trợ `Idempotency-Key` header: cùng key + body → trả submission cũ.

### Bước 2 — Upload & đăng ký artifact

> Giới hạn: PDF 50 MiB, ZIP 200 MiB (+ quota giải nén).

```powershell
$files = @(
    @{ kind = 'report_pdf';     path = 'E:/path/to/report.pdf'; mime = 'application/pdf' },
    @{ kind = 'source_archive'; path = 'E:/path/to/source.zip'; mime = 'application/zip' }
)

foreach ($item in $files) {
    # 1. Upload file lên Cloudinary
    $result = curl.exe -sS --fail-with-body -X POST "$base/api/v1/submissions/$sid/files" `
        -F "kind=$($item.kind)" -F "file=@$($item.path);type=$($item.mime)"
    if ($LASTEXITCODE -ne 0) { throw $result }
    $upload = $result | ConvertFrom-Json

    # 2. Đăng ký artifact vào DB (bắt buộc — L1 tìm file qua DB)
    $artifact = @{
        kind       = $upload.kind
        version_no = 1
        object_uri = $upload.object_uri   # giữ nguyên, không thay bằng secure_url
        media_type = $upload.media_type
        byte_size  = $upload.byte_size
        sha256     = $upload.sha256
        metadata   = @{}
    } | ConvertTo-Json -Compress

    $result = $artifact | curl.exe -sS --fail-with-body -X POST "$base/api/v1/submissions/$sid/artifacts" `
        -H 'Content-Type: application/json' --data-binary '@-'
    if ($LASTEXITCODE -ne 0) { throw $result }
    $result
}
```

> Upload và đăng ký artifact là **hai bước riêng**. Quên bước 2 → L1 báo `artifact_not_found`.
> Để cập nhật file: tăng `version_no`; L1 luôn dùng `version_no` lớn nhất.

### Bước 3 — Trigger Layer 1

```powershell
curl.exe -i --max-time 1800 -X POST "$base/api/v1/submissions/$sid/submit"
```

Kỳ vọng: **HTTP 200**, `pipeline=L1`, `status=succeeded`, kèm metadata run. Response không chứa toàn bộ claims/graph.

#### Kiểm tra kết quả trong DB

```powershell
& $psql -h localhost -p 5432 -U $dbUser -d $dbName -W -c `
    'SELECT id, submission_id, pipeline, status, finished_at FROM pipeline_runs ORDER BY started_at DESC LIMIT 5;'

& $psql -h localhost -p 5432 -U $dbUser -d $dbName -W -c `
    'SELECT submission_id, count(*) FROM claims GROUP BY submission_id;'

& $psql -h localhost -p 5432 -U $dbUser -d $dbName -W -c `
    'SELECT * FROM code_graph_snapshots LIMIT 5;'
```

> Claims có thể rỗng nếu báo cáo không có claim phù hợp.
> Graph có thể ở trạng thái `partial` — `L1 succeeded` không đảm bảo mọi quan hệ code đã được giải quyết.

---

## Layer 1 — Luồng xử lý

```
POST /submissions
  └─ Kiểm tra project=open, rubric=published, user thuộc group
  └─ Tạo submission (status: uploaded)

POST /submissions/{id}/files  +  /artifacts  (mỗi file)
  └─ Upload Cloudinary → lưu metadata vào DB

POST /submissions/{id}/submit
  ├─ Lock submission (yêu cầu status=uploaded)
  ├─ Lấy PDF/ZIP phiên bản mới nhất → tính input fingerprint
  ├─ Tạo pipeline_run (L1=running, submission=processing)
  │
  ├─ [PDF]   Tải từ Cloudinary → verify checksum/size/signature
  ├─ [OCR]   PaddleOCR Official API(PDF) → sections, blocks (text/table/figure/equation/citation)
  ├─ [LLM]   Gom text theo section → trích xuất claims → kiểm tra span/context/citation
  │
  ├─ [ZIP]   Tải từ Cloudinary → verify checksum/size → giải nén an toàn → inventory
  ├─ [Graph] Graphify CLI local → chuẩn hóa nodes/edges + provenance
  ├─ [Store] graph.json → Cloudinary
  │
  ├─ Lưu sections, blocks, claims, graph_snapshot vào DB
  ├─ Tính output fingerprint → run=succeeded
  └─ Commit DB → trả pipeline_run
```

**Provenance code:** `EXTRACTED` | `INFERRED` | `AMBIGUOUS`

## Pipeline 2 — Kiểm tra trích dẫn

Sau khi Layer 1 thành công, chạy Phase 1 của Pipeline 2 bằng một endpoint:

```powershell
curl.exe -i --max-time 1800 -X POST `
    "$base/api/v1/submissions/$sid/pipelines/p2"
```

Pipeline 2 hiện thực hiện tuần tự các bước sau:

1. Resolve các tài liệu tham khảo chưa được xử lý qua Crossref.
2. Ghép từng claim với citation marker và tài liệu tham khảo tương ứng.
3. Lấy bằng chứng local/abstract có sẵn.
4. Lưu evidence pack, evidence item và pipeline result để Phase 2 sử dụng sau.
5. Trả `requires_review` cùng reason code `PHASE1_EVIDENCE_READY` hoặc
   `NO_LOCAL_OR_ABSTRACT_EVIDENCE`.

`CitationVerificationResult` là contract thống nhất của Pipeline 2. Code hiện tại
chỉ hiện thực Phase 1. Claim decomposition và LLM citation judge của Phase 2 chỉ
được giữ dưới dạng stub `TODO Phase 2` để làm sau và chưa được nối vào runtime.

Crossref cần `CROSSREF_MAILTO` hợp lệ.

### Giới hạn hiện tại

| Vấn đề | Chi tiết |
|---------|----------|
| Submission sau L1 | Vẫn ở `processing` — submit lại báo `invalid_state_transition`. Tạo attempt mới để chạy lại. |
| Fingerprint | Được tính và lưu, chưa dùng để skip run trùng input. |
| Lỗi giữa chừng | DB rollback; chưa gọi `mark_failed` để lưu run thất bại. |
| Cloudinary orphan | File đã upload không rollback cùng DB khi bước sau lỗi. |
| Auth | Chưa có middleware xác thực token. `submitted_by_user_id` do client gửi — membership check chưa thay thế auth thật. |
| GET endpoints | Chưa có GET cho claims/graph/run — dùng DB trực tiếp để kiểm tra. |

---

## Xử lý lỗi

Error response có dạng:

```json
{"errorCode": 40300, "code": "forbidden", "message": "Forbidden"}
```

Validation error có thêm trường `details`. Exception không có handler → HTTP 500, xem log API. Mapping đầy đủ: [`error_codes.py`](src/app/core/error_codes.py).

### Bảng lỗi thường gặp

| Triệu chứng | Nguyên nhân & Cách xử lý |
|-------------|---------------------------|
| `ModuleNotFoundError: app` | Chạy `pip install -e . --no-deps` hoặc thêm `--app-dir src` vào lệnh uvicorn |
| `DB connection refused` | Kiểm tra PostgreSQL đang chạy, port 5432, `DATABASE_URL` trong `.env` |
| `relation does not exist` | Chạy migration (`001_initial_schema.sql`) trên đúng DB — API không tự tạo bảng |
| `409` Project không mở / Rubric chưa publish | Chạy seed hoặc kiểm tra status trong DB |
| `403` User không thuộc group | Kiểm tra `group_members` và `submitted_by_user_id` |
| `409 duplicate_resource` | `attempt_no` hoặc `version_no` đã tồn tại — tăng lên |
| `404 artifact_not_found` | Thiếu bước đăng ký `/artifacts` sau khi upload |
| `503` Cloudinary credentials | Điền đủ Cloudinary env và restart API |
| `503` Claim LLM endpoint/model | Kiểm tra `CLAIM_LLM_URL` và `CLAIM_LLM_MODEL` |
| `503` PaddleOCR access token is not configured | Điền `PADDLEOCR_ACCESS_TOKEN` trong `.env`, sau đó restart API |
| Log PaddleOCR báo `401/403` (API trả `502 parser_error`) | Token sai, hết hạn hoặc tài khoản không có quyền/quota; tạo lại token trong AI Studio |
| OCR timeout | Tăng `PADDLEOCR_POLL_TIMEOUT_SECONDS` hoặc kiểm tra trạng thái dịch vụ và kích thước PDF |
| `503` Local OCR dependencies | Chỉ áp dụng khi `OCR_PROVIDER=local`; cài `requirements-ocr.txt` trong đúng `.venv` |
| `502 parser_error` | Lỗi inference OCR, LLM JSON/model, quota, hoặc Graphify CLI/version — xem log |
| `502 storage_error` | Kiểm tra Cloudinary, quyền `raw authenticated`, `object_uri` |
| `413 payload_too_large` | File vượt giới hạn upload hoặc quota giải nén |
| `409` sau submit thành công | Submission đang `processing` — tạo attempt mới |
| Sửa `.env` không có tác dụng (Docker) | `docker compose up -d --force-recreate api`; kiểm tra `DOCKER_DATABASE_URL` |

---

## Kiểm tra & Linting

```powershell
# Unit tests
.\.venv\Scripts\python.exe -m pytest

# Linting
.\.venv\Scripts\python.exe -m ruff check src tests

# Type checking
.\.venv\Scripts\python.exe -m mypy src
```

> Test bao gồm: cấu trúc, ORM, upload, adapter OCR/service với fake/mock.
> **Pass test ≠ pipeline end-to-end hoạt động.** Cần chạy [Test API](#test-api) với OCR, LLM, Graphify thật để xác nhận tích hợp.

---

## Quy ước phát triển

- **Business logic** → `services/`; **ORM queries** → `repositories/`; **tích hợp công cụ** → `adapters/`
- Thay schema DB → viết migration SQL mới + cập nhật ORM model tương ứng
- Thay config hoặc contract tích hợp → cập nhật `README.md` và `.env.example`
- **Không commit** `.env`, `.venv`, `__pycache__`, cache Python — `.gitignore` đã bỏ qua
- `__pycache__` có thể xóa tự do; Python tạo lại khi import. Không xóa file `.py` nguồn
- DB session tạo theo request trong [`database.py`](src/app/core/database.py): commit khi thành công, rollback khi exception
- Migration SQL là nguồn tạo schema duy nhất — API không tự tạo bảng
