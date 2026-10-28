# Architecture notes for Skill Memory

These notes describe the AutoBots checkout at `sandbox/t6_A1_r1_0918-192914/autobots` (`master`), as read during preparation. Reference copies live under `autobots-reference/` and are listed in `REFERENCE_MANIFEST.md`.

Verified facts below are behavior read from that checkout. The standalone prototype built later is described in `prototype-decisions.md` and does not change these notes.

## MongoDB connections and repositories

Verified:

- `mongo_base.get_mongo_client()` caches one `AsyncIOMotorClient`. The URI is `SettingsProvider.sget().MONGO_CONN` plus the literal suffix `?retryWrites=true&w=majority`.
- `get_mongo_db()` yields `client[SettingsProvider.sget().MONGO_DATABASE]`.
- A second, synchronous `MongoClient` exists for APScheduler (`get_pymongo_client`).
- `CRUDBase` is the repository. `insert_one` writes `model_dump()`, and if the payload has `id` it stores that value as `_id`. `find_one` and `find_page` are the read paths. `update_one` is the update path.
- Documents identify their collection with `__collection__` on the Pydantic model. `SkillDoc.__collection__` is `Skills`. `EventResultDoc.__collection__` is `EventResults`.
- `SkillCRUD` binds `db[SkillDoc.__collection__]` and passes `SkillDoc` and `SkillLiteDoc` to `CRUDBase`.

`settings.py` was not copied. The connection fields inspected there are `MONGO_CONN: str` and `MONGO_DATABASE: str`, with no defaults on those two lines. No live connection was opened.

## Models and index registration

Verified:

- Indexes are not a separate migration table. A CRUD class sets `__indexes__` to a list of named `pymongo.IndexModel`s.
- `SkillCRUD.__indexes__` contains one index, `sk_shared_with_idx`, on `(shared_with, space_id, updated_at)` descending on `updated_at`, `background=True`.
- `mongo_indexes.declared_indexes()` discovers indexes by walking subclasses of `CRUDBase`. The collection name comes from the first generic parameter's `__collection__`.
- `ensure_indexes()` calls `create_indexes` for each discovered collection. A failure in one collection is logged and does not stop the others. If nothing was discovered, it logs that the CRUD modules may not have been imported.
- `lifespan.py` calls `ensure_indexes` during API startup. The comment there says this process is the one that has imported the routers, and therefore the one where the CRUD classes exist. It also calls `ensure_data_plane_indexes` first. That data-plane helper was not copied.
- There is no Alembic-style migration package. `scripts/migrations/` contains one-off scripts. Those scripts were not copied.

Assumption: a new Skill Memory CRUD class would be invisible to `ensure_indexes` until some imported module loads it. That follows from the subclass walk. It is not something this checkout demonstrates with a Skill Memory class, because no such class exists.

## Weaviate create, update, and search

Verified:

- `AbstractVectorDBClient` is the interface. `upsert_objects` takes `objects`, optional `vectors`, and optional `tenant_id`. Each object must include `uuid`. The docstring says the same method accepts either data for a database-native embedding or a precomputed vector.
- `WeaviateVectorDBClient.upsert_objects` batches with `batch.fixed_size`. When `vectors[i]` is not `None`, it passes `vector` into `batch.add_object`. This is the update path as well: the client comment says the batch API upserts.
- `search` requires `query_text` or `query_vector`. `search_type="vector"` uses `near_vector` when a vector is present, and `near_text` when only text is present. `search_type="hybrid"` requires `query_text` and calls `collection.query.hybrid`. Results include `uuid`, `properties`, `vector`, and `_additional.distance` and `_additional.score`.
- `ensure_class_exists` creates a collection from `schema["properties"]`, `schema["vectorizer_config"]`, `schema["generative_config"]`, and `schema["multi_tenancy_config"]`. If the collection already exists and the schema asks for multi-tenancy, a collection that is not multi-tenant raises `RuntimeError`. Missing properties on an existing collection are added.
- `WeaviateStore` defaults the collection name to `autobots_store`. `DEFAULT_WEAVIATE_PROPERTIES` describes ingested documents: `page_content`, source locators, `user_id`, `action_run_id`, `mongo_collection`, and media blobs. `_sanitize_tenant_id` turns a user id into a Weaviate tenant name of 4–64 characters in `[a-zA-Z0-9_-]`.
- Settings fields inspected for this client are `WEAVIATE_URL: Optional[str] = None` and `WEAVIATE_API_KEY: Optional[str] = None`. The client constructor takes `url` and `api_key` as arguments rather than reading those fields itself.

`near_text` and `hybrid` depend on whatever vectorizer the collection was created with. The copied client does not choose that vectorizer. The caller passes `vectorizer_config`.

No Weaviate process was contacted.

## Embedding providers and dimensions

Verified:

- `Embeddings` in `conn/chroma/chroma.py` is the in-repo embedder ABC. `embed_documents(texts) -> List[List[float]]`. `embed_query(text) -> List[List[float]]` on the abstract method. `aembed_query` is annotated `List[float]`. Those two query annotations do not match. `weaviate_store.py` imports this class and comments that the Chroma location is technical debt.
- `IMultimodalEmbeddings` extends `Embeddings` and adds `aembed_images`, `aembed_audios`, and `aembed_videos`, each raising `NotImplementedError` on the base.
- `EmbeddingReq.model` is fixed to the literal `text-embedding-ada-002`, defaulting to that string. `EmbeddingData.embedding` is `List[float]`. Neither model declares a dimension.
- `OpenaiEmbeddings.embeddings` calls `client.embeddings.create(**embedding_req.model_dump())`. The OpenAI or Azure client is passed in.
- `get_azure_openai` in `openai_client.py` (not copied) passes `AZURE_OPENAI_EMBEDDINGS_BASE_URL`, `AZURE_OPENAI_EMBEDDINGS_API_KEY`, and `AZURE_OPENAI_EMBEDDINGS_API_VERSION` into `AzureOpenAIConfig`. Inspected defaults: base URL `https://kiwi-dev.openai.azure.com/`, API key `""`, API version `2024-08-01-preview`. No embedding deployment name or dimension sits next to those three fields.
- `pinecone.py` is entirely commented out. The comments mention index name `serverless-index-1536` and `dimension = 1536`. `pinecone/__init__.py` does not import that module. `pyproject.toml` still depends on `pinecone-client==6.0.0`.
- `CRUDBase` sets `self.vector_index_name` to `vector_{collection}`. The following branch assigns `self.search_path` and does not assign `self.vector_path`. This file contains no `$vectorSearch`.

Open question: which width a future embedder must produce. The active request model names `text-embedding-ada-002` and does not state a width. The commented Pinecone index name contains `1536`. Those are not the same kind of evidence, and this inspection did not call an embedding API.

## Product Skills

Verified:

- Collection `Skills`.
- `SkillCreate` requires `name` and `blocks: DataBlocks`. `is_published` defaults to false. `shared_with` defaults to an empty list of `SpaceId | str`.
- `SkillDoc` adds `user_id`, optional `space_id`, `created_at`, `updated_at`, and `_id` via `MongoID`.
- `UserSkills.create` loads an existing skill by name for that user and raises HTTP 409 if one exists. It also rejects more than 50 blocks.
- The HTTP router prefix is `/skills`. It uses `get_mongo_db` and `UserSkills`.
- The model has no version number, no evidence list, and no embedding metadata.

`DataBlocks` is defined in `src/autobots/action/action/common_action_models.py`, which was not copied. A product skill body is that type, not a plain string.

This collection is the user-authored skill product. It is a different record from an experience-derived skill memory. That distinction is a reading of the fields above, not a second schema found in the repo.

## Linking an experience trace to its source run

Verified from `event_result_model.py`:

- A run document is an `EventResultDoc` in `EventResults`.
- The id field is `id`, aliased to `_id`.
- `type` is an `EventType`: `action_run`, `action_graph_run`, `action_team_run`, `tool_run`, or `datastore_put`.
- `user_id` is required on `EventResultDocCreate`.
- `status` is an `EventResultStatus`: `success`, `processing`, `error`, `waiting`, `stuck`, `request_cancel`, `cancelled`.
- `file_url` is optional on the full document, the lite document, and the update model.
- `parent_action_result_id` is optional on `EventResultCreate`.
- This file does not declare `human_questions` or `run_kind`.

Verified from the readers, which were inspected and not copied:

- `UserActionResult` stores files with `UserFiles` and `top_level_folder=AWS_S3_ACTION_RUNS_FOLDER`. Settings sets that folder to `action_runs`. `UserFiles` builds the prefix `{folder}/{user.id}/`. `_filename` is `{action_result_id}.json`.
- `get_action_result` reads Mongo first. With an empty `file_url`, it returns that Mongo document. With a `file_url`, it loads the object bytes and, when they exist, returns `ActionResultDoc.model_validate_json(file_bytes)`. Missing bytes raise HTTP 404 `Action result payload missing in S3`. This checkout has no `_with_payload` method. The object-storage JSON replaces the returned document rather than being merged onto the Mongo document in this method.
- `get_action_graph_result` tries `{id}.json` under `AWS_S3_RUNS_FOLDER` (`runs`). Empty bytes fall back to Mongo. Any exception is logged and the method returns `None`.
- `get_action_team_result` uses the same S3-then-Mongo pattern and also returns `None` on any exception.
- `get_tool_result` reads Mongo only, filtered by `type=tool_run`.

Verified terminal sets:

- `TERMINAL_STATUSES` in `run_metrics_doc_model.py` is `success`, `error`, `cancelled`.
- `TERMINAL_TOOL_RUN_STATUSES` adds `stuck`.

Verified from the existing `Write Path/trace-normalization` package, which this task did not modify:

- A normalized episode's `episode_id` is the source run id.
- `source.collection` is `EventResults`.
- `source` also carries `source_run_id`, `event_type`, and optional `user_id` and `file_url`.

`experience_memory/` in the checkout is untracked pre-existing work. It was not copied and was not treated as the source of this note. Its `JsonEpisodeStore` writes local JSON files. That is a fact from a file header read during inspection, not a store Skill Memory should call.

Open question: the trace-normalization episode schema in `Write Path` includes `human_questions` and `run_kind`. The current checkout's `event_result_model.py` does not declare those fields. A later prototype should treat them as present only when a document actually contains them. This note does not decide which tree is newer.

## Interfaces that can be reused later

Verified surfaces a prototype can sit behind, without calling them yet:

- Mongo documents and `CRUDBase`, including `__indexes__` and `ensure_indexes`, for skill records. A new collection name is required if product `Skills` stays unchanged. No new database is required for the records.
- `AbstractVectorDBClient.upsert_objects(..., vectors=...)` and `search(..., query_vector=...)` for an index of precomputed vectors. `WeaviateVectorDBClient` already implements both.
- An injected embedder shaped like `Embeddings.embed_documents` / `aembed_query`, or like `OpenaiEmbeddings.embeddings`, so the prototype does not construct a provider client.

`autobots_store` and `DEFAULT_WEAVIATE_PROPERTIES` are the ingestion document index. Reusing that collection would mix skill rows with page chunks. That is a conclusion from the property list, not a second collection found for skills.

`generative_search` and `near_text` call provider-side behavior. They are the wrong default for a prototype that must run with no embedding provider.

## Unresolved

- Embedding width and the deployment name are not configured next to `AZURE_OPENAI_EMBEDDINGS_*`. The ada-002 literal and the commented Pinecone `1536` are the only figures seen, and the Pinecone client does not run.
- `WEAVIATE_URL` defaults to `None`. Whether every deployment has a Weaviate collection, and which `vectorizer_config` it was created with, was not verified against a server.
- Graph and team readers return `None` for both a missing row and a failed read. A skill evidence pointer cannot treat that `None` as a confirmed missing run.
- This checkout returns the action-run object-storage body as the whole document. It does not show a merge that keeps Mongo fields and replaces only `result`.
- `human_questions` and `run_kind` are in the Write Path episode schema and absent from this checkout's event model.
- `CRUDBase`'s `vector_path` argument is not stored. Mongo is not an embedding index in this code.
- Product `Skills` uniqueness is per user and name. Nothing in that model describes experience-skill versions or evidence.
- Index discovery depends on import order. A future package that is not imported at lifespan will not get its indexes created. How that import is added is an integration decision.
