"""Storage ports. Implementations must not open a network connection by themselves."""

from __future__ import annotations

from typing import Any, Protocol


class StoreError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SkillMemoryStore(Protocol):
    def put_episode(self, episode: dict[str, Any]) -> dict[str, Any]: ...

    def get_episode(self, episode_id: str) -> dict[str, Any] | None: ...

    def assign_episode_bucket(self, episode_id: str, bucket_id: str) -> dict[str, Any]: ...

    def insert_bucket(self, bucket: dict[str, Any]) -> dict[str, Any]: ...

    def replace_bucket(self, bucket: dict[str, Any]) -> dict[str, Any]: ...

    def get_bucket(self, bucket_id: str) -> dict[str, Any] | None: ...

    def list_buckets(self) -> list[dict[str, Any]]: ...

    def insert_skill(self, skill: dict[str, Any]) -> dict[str, Any]: ...

    def get_skill(self, skill_id: str) -> dict[str, Any] | None: ...


class SkillVectorIndex(Protocol):
    def index_skill(self, skill: dict[str, Any]) -> dict[str, Any]: ...

    def search(self, query_text: str, limit: int = 4) -> dict[str, Any]: ...
