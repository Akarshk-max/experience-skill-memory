"""Future skill vector index.

Indexing is disabled unless a caller injects an embedder and sets `enabled`.
The production embedding width is unresolved, so this module does not pick a
model name or a dimension. Bucket matching does not call this index.

The reference Weaviate client is async and talks to a server. This adapter is
a synchronous boundary around an injected client object. It never constructs
that client and never calls `ensure_class_exists`.
"""

from __future__ import annotations

from typing import Any

COLLECTION = "skill_memory_skills"
METADATA_FIELDS = ("skill_id", "name", "description", "status", "bucket_id")
UNRESOLVED = "embedding_dimension_unresolved"


class DisabledSkillVectorIndex:
    def index_skill(self, skill: dict[str, Any]) -> dict[str, Any]:
        return {"status": "disabled", "reason": UNRESOLVED, "written": False}

    def search(self, query_text: str, limit: int = 4) -> dict[str, Any]:
        return {"status": "disabled", "reason": UNRESOLVED, "results": [], "written": False}


class WeaviateSkillIndex:
    def __init__(self, client: Any = None, embedder: Any = None, enabled: bool = False) -> None:
        self.client = client
        self.embedder = embedder
        self.enabled = enabled

    def index_skill(self, skill: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "disabled", "reason": UNRESOLVED, "written": False}
        if self.embedder is None or self.client is None:
            return {"status": "disabled", "reason": "embedding_provider_unresolved", "written": False}
        vector = self.embedder.embed_documents([_index_text(skill)])[0]
        if not _vector_ok(vector):
            return {"status": "error", "reason": "embedder_returned_no_vector", "written": False}
        metadata = {field: skill[field] for field in METADATA_FIELDS}
        payload = {"uuid": skill["skill_id"], **metadata}
        identifiers, failures = self.client.upsert_objects(
            COLLECTION, [payload], vectors=[list(vector)]
        )
        if failures or skill["skill_id"] not in identifiers:
            return {"status": "error", "reason": "upsert_failed", "written": False, "failures": failures}
        return {
            "status": "indexed",
            "written": True,
            "collection": COLLECTION,
            "dimension": len(vector),
            "uuid": skill["skill_id"],
        }

    def search(self, query_text: str, limit: int = 4) -> dict[str, Any]:
        if not self.enabled or self.embedder is None or self.client is None:
            reason = UNRESOLVED if not self.enabled else "embedding_provider_unresolved"
            return {"status": "disabled", "reason": reason, "results": [], "written": False}
        vector = self.embedder.embed_documents([query_text])[0]
        if not _vector_ok(vector):
            return {"status": "error", "reason": "embedder_returned_no_vector", "results": []}
        results = self.client.search(
            COLLECTION,
            query_text=None,
            query_vector=list(vector),
            limit=limit,
            search_type="vector",
        )
        return {"status": "ok", "results": results, "dimension": len(vector)}


def _index_text(skill: dict[str, Any]) -> str:
    return f"{skill['name']}\n{skill['description']}"


def _vector_ok(vector: Any) -> bool:
    return (
        isinstance(vector, list)
        and bool(vector)
        and all(not isinstance(item, bool) and isinstance(item, (int, float)) for item in vector)
    )
