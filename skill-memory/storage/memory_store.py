"""In-memory stand-in for the bucket, skill, and episode collections."""

from __future__ import annotations

import copy
from typing import Any

from models import episode_body
from storage.interfaces import StoreError


class MemoryStore:
    def __init__(self) -> None:
        self.episodes: dict[str, dict[str, Any]] = {}
        self.buckets: dict[str, dict[str, Any]] = {}
        self.skills: dict[str, dict[str, Any]] = {}

    def put_episode(self, episode: dict[str, Any]) -> dict[str, Any]:
        episode_id = episode["episode_id"]
        existing = self.episodes.get(episode_id)
        if existing is not None and episode_body(existing) != episode_body(episode):
            raise StoreError("episode_identity_conflict", "episode_id already stores different evidence")
        if existing is None:
            stored = copy.deepcopy(episode)
            stored["bucket_id"] = episode.get("bucket_id")
            self.episodes[episode_id] = stored
        return copy.deepcopy(self.episodes[episode_id])

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        episode = self.episodes.get(episode_id)
        return copy.deepcopy(episode) if episode else None

    def assign_episode_bucket(self, episode_id: str, bucket_id: str) -> dict[str, Any]:
        existing = self.episodes.get(episode_id)
        if existing is None:
            raise StoreError("unknown_episode", f"unknown episode {episode_id}")
        current = existing.get("bucket_id")
        if current and current != bucket_id:
            raise StoreError("episode_already_bucketed", f"{episode_id} is already in {current}")
        existing["bucket_id"] = bucket_id
        return copy.deepcopy(existing)

    def insert_bucket(self, bucket: dict[str, Any]) -> dict[str, Any]:
        bucket_id = bucket["bucket_id"]
        if bucket_id in self.buckets:
            raise StoreError("duplicate_bucket", f"bucket {bucket_id} already exists")
        self.buckets[bucket_id] = copy.deepcopy(bucket)
        return copy.deepcopy(bucket)

    def replace_bucket(self, bucket: dict[str, Any]) -> dict[str, Any]:
        bucket_id = bucket["bucket_id"]
        if bucket_id not in self.buckets:
            raise StoreError("unknown_bucket", f"unknown bucket {bucket_id}")
        self.buckets[bucket_id] = copy.deepcopy(bucket)
        return copy.deepcopy(bucket)

    def get_bucket(self, bucket_id: str) -> dict[str, Any] | None:
        bucket = self.buckets.get(bucket_id)
        return copy.deepcopy(bucket) if bucket else None

    def list_buckets(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(bucket) for bucket in self.buckets.values()]

    def insert_skill(self, skill: dict[str, Any]) -> dict[str, Any]:
        skill_id = skill["skill_id"]
        if skill_id in self.skills:
            raise StoreError("duplicate_skill", f"skill {skill_id} already exists")
        self.skills[skill_id] = copy.deepcopy(skill)
        return copy.deepcopy(skill)

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        skill = self.skills.get(skill_id)
        return copy.deepcopy(skill) if skill else None
