"""Mongo-shaped adapter over injected collections.

This module does not import Motor, PyMongo, or the AutoBots package, and it
does not read credentials. Tests pass `InMemoryMongoCollection`. A later
integration can pass `db["SkillMemoryBuckets"]` and the sibling collections.
Those names are separate from the product `Skills` collection.

Documents follow the copied CRUDBase shape: the record id is stored as `_id`.
"""

from __future__ import annotations

import copy
from typing import Any

from models import episode_body
from storage.interfaces import StoreError

BUCKET_COLLECTION = "SkillMemoryBuckets"
SKILL_COLLECTION = "SkillMemorySkills"
EPISODE_COLLECTION = "SkillMemoryEpisodes"


class InMemoryMongoCollection:
    """Collection port with insert_one, find_one, replace_one, and find. No network."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.docs: dict[str, dict[str, Any]] = {}

    def insert_one(self, document: dict[str, Any]) -> dict[str, Any]:
        doc_id = document.get("_id")
        if not isinstance(doc_id, str) or not doc_id:
            raise StoreError("missing_id", "document needs a string _id")
        if doc_id in self.docs:
            raise StoreError("duplicate", f"{self.name} already has {doc_id}")
        self.docs[doc_id] = copy.deepcopy(document)
        return {"inserted_id": doc_id}

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        doc_id = query.get("_id")
        if doc_id is not None:
            found = self.docs.get(doc_id)
            return copy.deepcopy(found) if found else None
        for document in self.docs.values():
            if all(document.get(key) == value for key, value in query.items()):
                return copy.deepcopy(document)
        return None

    def replace_one(self, query: dict[str, Any], document: dict[str, Any]) -> dict[str, int]:
        doc_id = query.get("_id")
        if doc_id not in self.docs:
            return {"matched_count": 0}
        self.docs[doc_id] = copy.deepcopy(document)
        return {"matched_count": 1}

    def find(self, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        query = query or {}
        found = []
        for document in self.docs.values():
            if all(document.get(key) == value for key, value in query.items()):
                found.append(copy.deepcopy(document))
        return found


class MongoSkillMemoryStore:
    def __init__(self, buckets: Any, skills: Any, episodes: Any) -> None:
        self.buckets = buckets
        self.skills = skills
        self.episodes = episodes

    def put_episode(self, episode: dict[str, Any]) -> dict[str, Any]:
        episode_id = episode["episode_id"]
        existing = self.get_episode(episode_id)
        if existing is not None and episode_body(existing) != episode_body(episode):
            raise StoreError("episode_identity_conflict", "episode_id already stores different evidence")
        if existing is None:
            self.episodes.insert_one(_with_id(episode, episode_id))
        return self.get_episode(episode_id)  # type: ignore[return-value]

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        return _without_id(self.episodes.find_one({"_id": episode_id}))

    def assign_episode_bucket(self, episode_id: str, bucket_id: str) -> dict[str, Any]:
        existing = self.get_episode(episode_id)
        if existing is None:
            raise StoreError("unknown_episode", f"unknown episode {episode_id}")
        current = existing.get("bucket_id")
        if current and current != bucket_id:
            raise StoreError("episode_already_bucketed", f"{episode_id} is already in {current}")
        existing["bucket_id"] = bucket_id
        result = self.episodes.replace_one({"_id": episode_id}, _with_id(existing, episode_id))
        if result["matched_count"] != 1:
            raise StoreError("unknown_episode", f"unknown episode {episode_id}")
        return existing

    def insert_bucket(self, bucket: dict[str, Any]) -> dict[str, Any]:
        self.buckets.insert_one(_with_id(bucket, bucket["bucket_id"]))
        return copy.deepcopy(bucket)

    def replace_bucket(self, bucket: dict[str, Any]) -> dict[str, Any]:
        result = self.buckets.replace_one({"_id": bucket["bucket_id"]}, _with_id(bucket, bucket["bucket_id"]))
        if result["matched_count"] != 1:
            raise StoreError("unknown_bucket", f"unknown bucket {bucket['bucket_id']}")
        return copy.deepcopy(bucket)

    def get_bucket(self, bucket_id: str) -> dict[str, Any] | None:
        return _without_id(self.buckets.find_one({"_id": bucket_id}))

    def list_buckets(self) -> list[dict[str, Any]]:
        return [item for item in (_without_id(doc) for doc in self.buckets.find({})) if item]

    def insert_skill(self, skill: dict[str, Any]) -> dict[str, Any]:
        self.skills.insert_one(_with_id(skill, skill["skill_id"]))
        return copy.deepcopy(skill)

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        return _without_id(self.skills.find_one({"_id": skill_id}))


def _with_id(record: dict[str, Any], record_id: str) -> dict[str, Any]:
    stored = copy.deepcopy(record)
    stored["_id"] = record_id
    return stored


def _without_id(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    record = copy.deepcopy(document)
    record.pop("_id", None)
    return record
