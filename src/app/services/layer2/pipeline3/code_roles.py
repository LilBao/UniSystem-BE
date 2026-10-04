import re
from pathlib import PurePosixPath

BOILERPLATE_STEM_SUFFIXES = frozenset(
    {
        "dto",
        "request",
        "response",
        "payload",
        "vo",
        "exception",
        "error",
        "enum",
        "constant",
        "constants",
        "util",
        "utils",
        "helper",
        "properties",
        "test",
        "tests",
        "mock",
        "fixture",
        "mapper",
        "builder",
        "converter",
        "id",
        "key",
        "type",
        "status",
    }
)

BOILERPLATE_DIR_SEGMENTS = frozenset(
    {
        "dto",
        "dtos",
        "request",
        "requests",
        "response",
        "responses",
        "enums",
        "exception",
        "exceptions",
        "util",
        "utils",
        "helpers",
        "test",
        "tests",
        "mock",
        "mocks",
        "fixtures",
        "constants",
        "payload",
        "payloads",
    }
)

ROLE_SUFFIX_MAP = {
    "controller": "controller",
    "service": "service",
    "serviceimpl": "service",
    "repository": "repository",
    "dao": "repository",
    "entity": "entity",
    "model": "entity",
    "config": "infrastructure",
    "configuration": "infrastructure",
    "filter": "infrastructure",
    "interceptor": "infrastructure",
    "security": "infrastructure",
    "handler": "infrastructure",
    "listener": "infrastructure",
    "aspect": "infrastructure",
    "adapter": "component",
    "manager": "service",
}


def get_file_stem(path: str) -> str:
    """Lấy tên file không có phần mở rộng."""
    posix = PurePosixPath(path.replace("\\", "/"))
    return posix.stem


def is_boilerplate_path(path: str) -> bool:
    """Xác định xem file có phải là file bổ trợ / boilerplate hay không."""
    posix = PurePosixPath(path.replace("\\", "/"))
    parts = [p.lower() for p in posix.parts]

    # Kiểm tra xem đường dẫn có nằm trong thư mục boilerplate không
    if any(p in BOILERPLATE_DIR_SEGMENTS for p in parts):
        return True

    stem = posix.stem.lower()
    # Tên file kiểm thử
    if stem.startswith(("test", "mock", "fake")) or stem.endswith(
        ("test", "tests", "mock", "stub")
    ):
        return True

    # Kiểm tra phần kết thúc của tên file (camelCase / PascalCase)
    # Ví dụ: ApiResponse, UserRequest, SeatStatusEnum, AppException
    for suffix in BOILERPLATE_STEM_SUFFIXES:
        if stem.endswith(suffix):
            return True

    return False


def detect_file_role(path: str) -> str:
    """Nhận diện vai trò kiến trúc của file.
    (controller, service, repo, entity, infra, component, boilerplate).
    """
    if is_boilerplate_path(path):
        return "boilerplate"

    posix = PurePosixPath(path.replace("\\", "/"))
    parts = [p.lower() for p in posix.parts]
    stem = posix.stem.lower()

    # 1. Kiểm tra suffix của stem
    for suffix, role in ROLE_SUFFIX_MAP.items():
        if stem.endswith(suffix):
            return role

    # 2. Kiểm tra theo cấu trúc thư mục
    if "controller" in parts or "controllers" in parts or "api" in parts:
        return "controller"
    if "service" in parts or "services" in parts:
        return "service"
    if "repository" in parts or "repositories" in parts or "dao" in parts:
        return "repository"
    if "entity" in parts or "entities" in parts or "model" in parts or "models" in parts:
        return "entity"
    if (
        "config" in parts
        or "security" in parts
        or "jwt" in parts
        or "filter" in parts
        or "interceptor" in parts
    ):
        return "infrastructure"

    return "component"


def extract_feature_key(path: str) -> str:
    """Bóc tách tên tính năng nghiệp vụ (domain feature key) từ đường dẫn hoặc tên file.
    """
    posix = PurePosixPath(path.replace("\\", "/"))
    stem = posix.stem

    # Tách các từ trong stem (PascalCase / camelCase)
    tokens = re.findall(r"[A-Z]+(?=[A-Z][a-z0-9]|\b)|[A-Z]?[a-z0-9]+|[A-Z]+", stem)
    if not tokens:
        tokens = [stem]

    # Loại bỏ các hậu tố vai trò kiến trúc ở cuối
    strip_suffixes = {
        "controller",
        "service",
        "impl",
        "repository",
        "entity",
        "config",
        "filter",
        "handler",
        "interceptor",
        "listener",
        "manager",
        "strategy",
        "adapter",
        "component",
    }

    feature_tokens = [t for t in tokens if t.lower() not in strip_suffixes]
    if feature_tokens:
        # Nếu token đầu tiên là từ viết tắt (JWT, CORS, QR), nhóm theo token đầu
        first = feature_tokens[0].lower()
        if len(first) <= 4:
            return first
        return feature_tokens[0].lower()

    # Nếu stem chỉ toàn hậu tố, dùng thư mục cha gần nhất không generic
    generic_dirs = {
        "src",
        "main",
        "java",
        "app",
        "backend",
        "com",
        "controller",
        "controllers",
        "service",
        "services",
        "repository",
        "repositories",
        "entity",
        "entities",
        "config",
        "common",
    }
    for part in reversed(posix.parts[:-1]):
        p_lower = part.lower()
        if p_lower not in generic_dirs and len(p_lower) > 2:
            return p_lower

    return "general"
