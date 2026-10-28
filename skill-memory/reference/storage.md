# Storage

Canonical records for this prototype are buckets, skills, and the normalized episodes those buckets cite. The vector index is not canonical.

## Collections

The Mongo-shaped adapter uses three injected collections:

| Collection | Record |
| --- | --- |
| `SkillMemoryBuckets` | Bucket document. `_id` is `bucket_id`. `episode_refs` cite episodes and do not embed steps. |
| `SkillMemorySkills` | Candidate skill document. `_id` is `skill_id`. |
| `SkillMemoryEpisodes` | Normalized Episode v2, so generation can reload evidence. |

These names are not the product `Skills` collection. The adapter follows the copied `CRUDBase` habit of storing the id as `_id`. It does not import Motor, PyMongo, or AutoBots, and it does not read `MONGO_CONN`. Tests use `InMemoryMongoCollection`. No live MongoDB client is constructed.

Index creation through `ensure_indexes` is not run. A later integration would register a CRUD class only after that wiring is approved.

## Vector index

`DisabledSkillVectorIndex` is the default. `WeaviateSkillIndex` upserts only when `enabled` is true and an embedder was injected. The stored properties are `skill_id`, `name`, `description`, `status`, and `bucket_id`, plus the `uuid`. Procedure text and raw traces are not indexed.

The collection name is `skill_memory_skills`, not `autobots_store`. The adapter does not call `ensure_class_exists` and does not open a server. The reference client is async; this adapter is a synchronous boundary around an injected object.

Embedding width is unresolved. The adapter does not choose a model name or a dimension. The dimension is whatever the injected embedder returns. Until an embedder is supplied and indexing is explicitly enabled, index calls return `embedding_dimension_unresolved` or `embedding_provider_unresolved` and write nothing.

Bucket matching does not read or write the index.
