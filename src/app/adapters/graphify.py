import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.schemas.code_graph_schema import CodeGraph, GraphEdge, GraphLocation, GraphNode
from app.schemas.layer1_schema import CodeProvenance


def stable_id(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class GraphifyAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def version(self) -> str:
        try:
            return version("graphifyy")
        except PackageNotFoundError as exc:
            raise AppError(ErrorCode.PARSER_ERROR, "Graphify is not installed") from exc

    async def build(self, repository: Path, inventory: dict[str, Any]) -> CodeGraph:
        installed_version = self.version
        if installed_version != self.settings.graphify_version:
            raise AppError(
                ErrorCode.PARSER_ERROR,
                f"Graphify version mismatch: expected {self.settings.graphify_version}, "
                f"installed {installed_version}",
            )

        output_directory = repository.parent / "graphify-result"
        arguments = [
            sys.executable,
            "-m",
            "graphify",
            "extract",
            str(repository.resolve()),
            "--code-only",
            "--out",
            str(output_directory.resolve()),
            "--no-cluster",
            "--max-workers",
            str(self.settings.graphify_max_workers),
        ]
        allowed_environment = {
            name: value
            for name in (
                "APPDATA",
                "HOME",
                "LANG",
                "LOCALAPPDATA",
                "PATH",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "WINDIR",
            )
            if (value := os.environ.get(name)) is not None
        }
        allowed_environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        try:
            return_code, detail = await asyncio.to_thread(
                self._run_cli,
                arguments,
                repository,
                allowed_environment,
                self.settings.graphify_timeout_seconds,
            )
            if return_code != 0:
                raise AppError(
                    ErrorCode.PARSER_ERROR,
                    f"Graphify extraction failed: {detail or 'unknown error'}",
                )

            graph_file = output_directory / "graphify-out" / "graph.json"
            if not graph_file.is_file():
                raise AppError(ErrorCode.PARSER_ERROR, "Graphify did not produce graph.json")
            if graph_file.stat().st_size > self.settings.parser_max_response_bytes:
                raise AppError(ErrorCode.PARSER_ERROR, "Graphify output exceeds quota")
            raw = json.loads(graph_file.read_text(encoding="utf-8"))
            graph = self.normalize(raw, installed_version)
            graph.validate_inventory(inventory["files"])
            return graph
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
            raise AppError(
                ErrorCode.PARSER_ERROR, "Could not build Graphify representation"
            ) from exc

    @staticmethod
    def _run_cli(
        arguments: list[str],
        repository: Path,
        environment: dict[str, str],
        timeout: float,
    ) -> tuple[int, str]:
        log_file = repository.parent / "graphify.log"
        with log_file.open("w+b") as stream:
            completed = subprocess.run(
                arguments,
                cwd=repository,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 2000))
            detail = stream.read().decode("utf-8", errors="replace").strip()
        return completed.returncode, detail

    @staticmethod
    def normalize(raw: dict[str, Any], version: str) -> CodeGraph:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        remap: dict[str, str] = {}
        warnings: list[str] = []
        if (
            raw.get("errors")
            or raw.get("error")
            or raw.get("failed_sources")
            or raw.get("worker_warnings")
        ):
            warnings.append("graphify_partial_parse_failure")
        methods = {edge["target"] for edge in raw["edges"] if edge.get("relation") == "method"}

        def element(item: dict[str, Any], rule: str) -> dict[str, Any]:
            location = None
            path = str(item.get("source_file") or "")
            if path.startswith("/source/"):
                path = path[len("/source/") :]
            match = re.fullmatch(r"L(\d+)(?:[-–]L?(\d+))?", str(item.get("source_location") or ""))
            if path and match:
                location = GraphLocation(
                    path=path, start_line=int(match[1]), end_line=int(match[2] or match[1])
                )
            tag = CodeProvenance(item.get("confidence", "EXTRACTED"))
            confidence = item.get(
                "confidence_score", 1.0 if tag == CodeProvenance.EXTRACTED else None
            )
            evidence = {"parser": "graphify", "version": version, "rule": rule}
            if location is None or (tag == CodeProvenance.INFERRED and confidence is None):
                tag = CodeProvenance.AMBIGUOUS
                confidence = None
                evidence["reason"] = "unresolved_source_location_or_confidence"
            elif tag == CodeProvenance.AMBIGUOUS:
                evidence["reason"] = "graphify_ambiguous_relationship"
            return {
                "location": location,
                "provenance": tag,
                "confidence": confidence,
                "evidence": evidence,
            }

        for item in raw["nodes"]:
            if item["id"] in remap:
                raise ValueError("Duplicate Graphify node ID")
            fields = element(item, "structural_entity")
            metadata = item.get("metadata") or {}
            kind = str(item.get("type") or metadata.get("kind") or metadata.get("type") or "entity")
            if kind == "entity":
                if item.get("_callable_class"):
                    kind = "class"
                elif item["id"] in methods:
                    kind = "method"
                elif item.get("_callable"):
                    kind = "function"
                elif item.get("label") == Path(str(item.get("source_file", ""))).name:
                    kind = "module"
            key = stable_id([item["id"], item.get("source_file"), item.get("source_location")])
            remap[item["id"]] = key
            nodes.append(
                GraphNode(id=key, kind=kind, name=str(item.get("label", item["id"])), **fields)
            )
        for item in raw["edges"]:
            source, target = remap.get(item["source"]), remap.get(item["target"])
            if source is None or target is None:
                warnings.append("unresolved_edge_endpoint")
                continue
            original_relation = str(item["relation"])
            relation = {"method": "declares", "imports_from": "imports"}.get(
                original_relation, original_relation
            )
            fields = element(item, original_relation)
            key = stable_id(
                [source, target, relation, item.get("source_location"), item.get("source_file")]
            )
            edge = GraphEdge(id=key, source=source, target=target, relation=relation, **fields)
            edges.append(edge)
        unique: dict[str, GraphEdge] = {}
        for edge in edges:
            if edge.id in unique and edge != unique[edge.id]:
                raise ValueError("Conflicting Graphify edge evidence")
            unique[edge.id] = edge
        if any(n.provenance == CodeProvenance.AMBIGUOUS for n in [*nodes, *edges]):
            warnings.append("unresolved_entities")
        if not nodes:
            warnings.append("no_structural_entities")
        return CodeGraph(
            nodes=sorted(nodes, key=lambda n: n.id),
            edges=sorted(unique.values(), key=lambda e: (e.source, e.relation, e.target, e.id)),
            warnings=sorted(set(warnings)),
        )
