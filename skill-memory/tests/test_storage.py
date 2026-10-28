"""In-memory, Mongo-shaped, and vector-index adapter tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import generator, make_episode, service  # noqa: E402
from storage.mongo_store import (  # noqa: E402
    BUCKET_COLLECTION,
    EPISODE_COLLECTION,
    SKILL_COLLECTION,
    InMemoryMongoCollection,
    MongoSkillMemoryStore,
)
from storage.weaviate_index import COLLECTION, WeaviateSkillIndex  # noqa: E402


class ExplodingClient:
    def __init__(self) -> None:
        self.calls = []

    def ensure_class_exists(self, *args, **kwargs):
        self.calls.append("ensure")
        raise AssertionError("live collection creation is out of scope")

    def upsert_objects(self, *args, **kwargs):
        self.calls.append("upsert")
        raise AssertionError("disabled index must not upsert")

    def search(self, *args, **kwargs):
        self.calls.append("search")
        raise AssertionError("disabled index must not search")


class FakeVectorClient:
    def __init__(self) -> None:
        self.upserts = []
        self.searches = []
        self.ensure_called = False

    def ensure_class_exists(self, *args, **kwargs):
        self.ensure_called = True
        raise AssertionError("the adapter must not create a collection")

    def upsert_objects(self, class_name, objects, vectors=None, tenant_id=None):
        self.upserts.append(
            {"class_name": class_name, "objects": objects, "vectors": vectors, "tenant_id": tenant_id}
        )
        return [obj["uuid"] for obj in objects], []

    def search(self, class_name, query_text=None, query_vector=None, limit=4, search_type="vector", **kwargs):
        self.searches.append(query_vector)
        return []


class FakeEmbedder:
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


class StorageTest(unittest.TestCase):
    def test_mongo_adapter_stores_refs_separately_from_episodes(self):
        buckets = InMemoryMongoCollection(BUCKET_COLLECTION)
        skills = InMemoryMongoCollection(SKILL_COLLECTION)
        episodes = InMemoryMongoCollection(EPISODE_COLLECTION)
        store = MongoSkillMemoryStore(buckets, skills, episodes)
        created = service(threshold=1, generator=generator(), store=store)
        result = created.ingest(make_episode("ep-1"))
        self.assertEqual(buckets.name, "SkillMemoryBuckets")
        self.assertNotEqual(buckets.name, "Skills")
        stored_bucket = buckets.docs["bkt_0001"]
        self.assertEqual(stored_bucket["_id"], "bkt_0001")
        self.assertNotIn("steps", stored_bucket)
        self.assertEqual(set(stored_bucket["episode_refs"][0]), {"episode_id", "source_run_id", "event_type", "outcome"})
        self.assertIn("steps", episodes.docs["ep-1"])
        self.assertEqual(skills.docs[result["skill"]["skill_id"]]["_id"], result["skill"]["skill_id"])
        self.assertNotIn("procedure", stored_bucket)

    def test_duplicate_mongo_id_is_rejected(self):
        buckets = InMemoryMongoCollection(BUCKET_COLLECTION)
        buckets.insert_one({"_id": "bkt_0001", "bucket_id": "bkt_0001"})
        with self.assertRaises(Exception):
            buckets.insert_one({"_id": "bkt_0001"})

    def test_disabled_index_does_not_call_the_client(self):
        client = ExplodingClient()
        index = WeaviateSkillIndex(client=client, embedder=FakeEmbedder(), enabled=False)
        created = service(threshold=1, generator=generator(), vector_index=index)
        result = created.ingest(make_episode("ep-1"))
        self.assertEqual(result["vector_index"]["status"], "disabled")
        self.assertFalse(result["vector_index"]["written"])
        self.assertEqual(client.calls, [])
        self.assertEqual(index.search("lookup")["status"], "disabled")
        self.assertEqual(client.calls, [])

    def test_enabled_index_writes_metadata_only_and_does_not_choose_a_dimension(self):
        client = FakeVectorClient()
        index = WeaviateSkillIndex(client=client, embedder=FakeEmbedder(), enabled=True)
        created = service(threshold=1, generator=generator(), vector_index=index)
        result = created.ingest(make_episode("ep-1"))
        self.assertEqual(result["vector_index"]["status"], "indexed")
        self.assertEqual(result["vector_index"]["dimension"], 2)
        self.assertFalse(client.ensure_called)
        payload = client.upserts[0]
        self.assertEqual(payload["class_name"], COLLECTION)
        self.assertNotEqual(payload["class_name"], "autobots_store")
        stored = payload["objects"][0]
        self.assertEqual(
            set(stored),
            {"uuid", "skill_id", "name", "description", "status", "bucket_id"},
        )
        found = index.search("debug api timeout")
        self.assertEqual(found["status"], "ok")
        self.assertEqual(len(client.searches), 1)

    def test_enabled_index_without_an_embedder_does_not_call_the_client(self):
        client = ExplodingClient()
        index = WeaviateSkillIndex(client=client, embedder=None, enabled=True)
        result = index.index_skill({"skill_id": "skl_bkt_0001"})
        self.assertEqual(result["reason"], "embedding_provider_unresolved")
        self.assertEqual(client.calls, [])

    def test_prototype_modules_do_not_import_providers(self):
        banned = (
            "import motor",
            "import pymongo",
            "import weaviate",
            "import autobots",
            "openai",
            "text-embedding-ada-002",
            "1536",
        )
        for path in ROOT.rglob("*.py"):
            if "autobots-reference" in path.parts or "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for term in banned:
                self.assertNotIn(term, text, f"{path.name} contains {term}")


if __name__ == "__main__":
    unittest.main()
