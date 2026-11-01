import re
import unicodedata

from app.adapters.bm25_retriever import STOP_WORDS as EN_STOP_WORDS

VI_STOP_WORDS = frozenset(
    {
        "va",
        "hoac",
        "la",
        "cua",
        "cac",
        "nhung",
        "co",
        "duoc",
        "trong",
        "cho",
        "voi",
        "de",
        "theo",
        "mot",
        "nay",
        "do",
        "khi",
        "tu",
        "ve",
        "den",
        "tai",
        "ra",
        "vao",
        "tren",
        "duoi",
        "nhu",
        "boi",
        "nen",
        "vi",
        "ma",
        "se",
        "da",
        "dang",
        "lai",
        "cung",
        "chi",
        "rat",
        "qua",
        "hon",
        "nhat",
        "moi",
        "het",
        "deu",
        "luc",
        "chuc",
        "nang",
        "he",
        "thong",
        "ung",
        "dung",
        "du",
        "an",
        "mo",
        "ta",
        "yeu",
        "cau",
        "bao",
        "cao",
        "cap",
        "thuc",
        "hien",
        "giup",
        "phep",
        "su",
    }
)

COMMON_TECH_ACRONYMS = frozenset(
    {
        "jwt",
        "api",
        "cors",
        "qr",
        "rest",
        "sql",
        "db",
        "ui",
        "ws",
        "crud",
        "dto",
        "uuid",
        "http",
        "url",
        "id",
        "otp",
        "sdk",
    }
)


def fold_diacritics(text: str) -> str:
    """Loại bỏ dấu tiếng Việt (đ->d, Đ->D, và các dấu thanh/mũ)."""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def normalize_token(token: str) -> str:
    """Chuẩn hóa một từ đơn: lowercase và loại bỏ đuôi số nhiều đơn giản."""
    t = token.lower().strip()
    if not t:
        return ""
    if t in COMMON_TECH_ACRONYMS:
        return t
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and not t.endswith(("ss", "us", "is", "rs")) and len(t) > 3:
        return t[:-1]
    return t


def split_identifier(name: str) -> list[str]:
    """Tách tên định danh PascalCase, camelCase, snake_case, và viết tắt (JWT, CORS)."""
    if not name:
        return []
    parts = re.split(r"[_\-./\\]+", name)
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        # Tách camelCase / PascalCase và khối viết tắt in hoa liền nhau
        sub_tokens = re.findall(r"[A-Z]+(?=[A-Z][a-z0-9]|\b)|[A-Z]?[a-z0-9]+|[A-Z]+", part)
        if sub_tokens:
            tokens.extend(sub_tokens)
        else:
            tokens.append(part)
    return tokens


def identifier_tokens(name: str) -> list[str]:
    """Tách định danh thành các token chữ thường đã chuẩn hóa."""
    raw_tokens = split_identifier(name)
    result: list[str] = []
    for t in raw_tokens:
        norm = normalize_token(t)
        if norm:
            result.append(norm)
    return result


def extract_claim_terms(claim_text: str) -> list[str]:
    """Bóc tách từ khóa từ nội dung claim.
    - Giữ lại các từ viết tắt kỹ thuật (JWT, CORS, API, QR, DB, UI...).
    - Loại bỏ dấu tiếng Việt để đối chiếu với code tiếng Anh/không dấu.
    - Lọc bỏ stop words tiếng Anh và tiếng Việt.
    - Tách camelCase/snake_case nếu có mã lệnh trong claim.
    """
    if not claim_text:
        return []

    # 1. Phát hiện các từ viết tắt in hoa trong nguyên bản (JWT, API, QR...)
    acronyms = set(re.findall(r"\b[A-Z]{2,}\b", claim_text))
    acronym_tokens = {normalize_token(a) for a in acronyms}

    # 2. Xóa dấu tiếng Việt và chuyển sang chữ thường
    folded = fold_diacritics(claim_text).lower()

    # 3. Tách từ
    raw_words = re.findall(r"[a-z0-9_]+", folded)
    terms: list[str] = []
    seen: set[str] = set()

    for word in raw_words:
        # Nếu từ có chứa dấu gạch dưới hoặc dạng camel, tách tiếp
        sub_words = split_identifier(word)
        for sw in sub_words:
            norm = normalize_token(sw)
            if not norm or norm in seen:
                continue

            # Quy tắc giữ lại token:
            # - Là từ viết tắt công nghệ phổ biến hoặc viết tắt hoa trong claim: giữ lại
            is_acronym = norm in acronym_tokens or norm in COMMON_TECH_ACRONYMS
            if is_acronym:
                seen.add(norm)
                terms.append(norm)
                continue

            # - Stop words
            if norm in EN_STOP_WORDS or norm in VI_STOP_WORDS:
                continue

            # - Độ dài tối thiểu cho từ thông thường
            if len(norm) < 3:
                continue

            # - Chỉ chứa chữ số thuần túy -> bỏ qua nếu không có ý nghĩa
            if norm.isdigit() and len(norm) < 3:
                continue

            seen.add(norm)
            terms.append(norm)

    return terms
