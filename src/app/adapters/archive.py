import stat
import zipfile
import zlib
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError

IGNORED = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        ".venv",
        "venv",
        "__pycache__",
        "coverage",
        ".idea",
        ".vscode",
    }
)
EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
}
MANIFESTS = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "package.json": "javascript",
    "tsconfig.json": "typescript",
    "pom.xml": "java",
    "build.gradle": "java",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "Gemfile": "ruby",
    "composer.json": "php",
}


def safe_parts(name: str) -> tuple[str, ...]:
    name = name.replace("\\", "/")
    parts = tuple(name.rstrip("/").split("/"))
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }
    if (
        not name
        or name.startswith("/")
        or any(
            not part
            or part in {".", ".."}
            or part.rstrip(" .") != part
            or any(ord(c) < 32 or c in ':<>"|?*' for c in part)
            or part.split(".")[0].upper() in reserved
            for part in parts
        )
    ):
        raise AppError(ErrorCode.BAD_REQUEST, "Unsafe archive path")
    return parts


class SafeZipExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract(self, archive: Path, destination: Path) -> None:
        await run_in_threadpool(self._extract, archive, destination)

    def _extract(self, archive: Path, destination: Path) -> None:
        limits = self.settings
        seen: set[str] = set()
        declared = actual = 0
        try:
            with zipfile.ZipFile(archive) as source:
                entries = source.infolist()
                if len(entries) > limits.source_extract_max_files:
                    raise AppError(ErrorCode.PAYLOAD_TOO_LARGE, "Too many archive entries")
                for entry in entries:
                    parts = safe_parts(entry.orig_filename)
                    key = "/".join(parts).casefold()
                    mode = stat.S_IFMT(entry.external_attr >> 16)
                    if key in seen or mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise AppError(ErrorCode.BAD_REQUEST, "Duplicate or special archive entry")
                    seen.add(key)
                    declared += entry.file_size
                    if (
                        len(parts) > limits.source_extract_max_depth
                        or entry.file_size > limits.source_extract_max_file_bytes
                        or declared > limits.source_extract_max_total_bytes
                        or entry.file_size / max(entry.compress_size, 1)
                        > limits.source_extract_max_ratio
                    ):
                        raise AppError(
                            ErrorCode.PAYLOAD_TOO_LARGE, "Archive exceeds extraction quota"
                        )
                    target = destination.joinpath(*parts)
                    if not target.resolve().is_relative_to(destination.resolve()):
                        raise AppError(ErrorCode.BAD_REQUEST, "Unsafe archive path")
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    count = 0
                    with source.open(entry) as incoming, target.open("xb") as outgoing:
                        while chunk := incoming.read(64 * 1024):
                            count += len(chunk)
                            actual += len(chunk)
                            if (
                                count > min(entry.file_size, limits.source_extract_max_file_bytes)
                                or actual > limits.source_extract_max_total_bytes
                            ):
                                raise AppError(ErrorCode.PAYLOAD_TOO_LARGE)
                            outgoing.write(chunk)
                    if count != entry.file_size:
                        raise AppError(ErrorCode.BAD_REQUEST, "Invalid archive entry size")
        except (
            zipfile.BadZipFile,
            OSError,
            RuntimeError,
            NotImplementedError,
            EOFError,
            zlib.error,
        ) as exc:
            raise AppError(ErrorCode.BAD_REQUEST, "Invalid source archive") from exc


def inventory(repository: Path, settings: Settings) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    manifests: list[str] = []
    languages: set[str] = set()
    ignored = 0
    for path in sorted(repository.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(repository)
        if (
            any(part.lower() in IGNORED for part in relative.parts)
            or path.stat().st_size > settings.source_parse_max_file_bytes
            or path.name.endswith((".min.js", ".min.css", ".generated.ts"))
            or path.name == ".env"
            or path.name.startswith(".env.")
        ):
            ignored += 1
            continue
        data = path.read_bytes()
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            ignored += 1
            continue
        if "\x00" in content:
            ignored += 1
            continue
        evidence = "extension"
        language = EXTENSIONS.get(path.suffix.lower())
        if path.name in MANIFESTS:
            manifests.append(relative.as_posix())
            language = MANIFESTS[path.name]
            evidence = "manifest"
        elif not path.suffix and content.startswith("#!"):
            first_line = content.splitlines()[0]
            for executable, detected in (
                ("python", "python"),
                ("node", "javascript"),
                ("ruby", "ruby"),
            ):
                if executable in first_line:
                    language, evidence = detected, "shebang"
                    break
        if language is None:
            ignored += 1
            continue
        languages.add(language)
        files.append(
            {
                "path": relative.as_posix(),
                "language": language,
                "evidence": evidence,
                "byte_size": len(data),
                "line_count": max(1, len(content.splitlines())),
            }
        )
    return {
        "files": files,
        "languages": sorted(languages),
        "manifests": manifests,
        "ignored_path_count": ignored,
        "byte_size": sum(f["byte_size"] for f in files),
    }
