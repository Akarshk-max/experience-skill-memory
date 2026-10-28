# Reference manifest

Source checkout: `sandbox/t6_A1_r1_0918-192914/autobots` on branch `master`.

Each file below was copied byte-for-byte. The path under `autobots-reference/` matches the path relative to that checkout. Copies were compared with `cmp` after the copy; every listed file matched.

These files are reference only. They are not wired into AutoBots.

## Copied files

### `pyproject.toml`

- Original: `pyproject.toml`
- Why: Records the dependency versions the interfaces were written against. Relevant pins: `motor==3.7.1`, `weaviate-client==4.22.0`, `chromadb==1.3.7`, `pinecone-client==6.0.0`, `openai[datalib]==2.54.0`, `pydantic[email]==2.13.4`. Requires Python `>=3.13,<3.14`.
- Important dependencies: none inside the repo.
- Dependencies copied: not applicable.

### `src/autobots/core/database/mongo_base.py`

- Original: `src/autobots/core/database/mongo_base.py`
- Why: Mongo connection. `get_mongo_client()` builds an `AsyncIOMotorClient` from `SettingsProvider.sget().MONGO_CONN` and appends `retryWrites=true&w=majority`. `get_mongo_db()` yields `client[MONGO_DATABASE]`.
- Important dependencies: `motor`, `pymongo`, `src.autobots.core.settings.SettingsProvider`.
- Dependencies copied: no. `settings.py` was left out on purpose (see "Intentionally not copied").

### `src/autobots/core/database/mongo_base_model.py`

- Original: `src/autobots/core/database/mongo_base_model.py`
- Why: `CollectionDocSearch` is the default search model `CRUDBase` repositories use. It requires `query` and `user_id`.
- Important dependencies: `pydantic`.
- Dependencies copied: not applicable.

### `src/autobots/core/database/mongo_base_crud.py`

- Original: `src/autobots/core/database/mongo_base_crud.py`
- Why: Repository base. `insert_one`, `find_one`, `find_page`, `find`, and `update_one`. `__indexes__` is a class attribute of `IndexModel`s. The constructor sets `vector_index_name` and then, when `vector_path` is omitted, assigns `self.search_path` again. It never assigns `self.vector_path`. No `$vectorSearch` call is present in this file.
- Important dependencies: `bson`, `fastapi`, `motor`, `pydantic`, `pymongo`.
- Dependencies copied: not applicable. Third-party only.

### `src/autobots/core/database/mongo_indexes.py`

- Original: `src/autobots/core/database/mongo_indexes.py`
- Why: Startup index registration. `declared_indexes()` walks `CRUDBase.__subclasses__()`. `ensure_indexes()` calls `create_indexes` per collection. A CRUD class that has not been imported is invisible. An empty result logs a warning.
- Important dependencies: `mongo_base_crud.CRUDBase`, Motor.
- Dependencies copied: `mongo_base_crud.py` is copied.

### `src/autobots/core/lifespan.py`

- Original: `src/autobots/core/lifespan.py`
- Why: Application startup calls `ensure_indexes` after the process that imports routers has loaded CRUD classes. The comment in the file states that this is why index setup runs here rather than in the ingestion worker.
- Important dependencies: FastAPI, Redis lifespan, `register_tools`, `ensure_data_plane_indexes`, crypto init, `SettingsProvider`, `mongo_indexes.ensure_indexes`.
- Dependencies copied: `mongo_indexes.py` only. Redis, tool registration, data-plane indexes, and crypto init were not copied.

### `src/autobots/data_model/id.py`

- Original: `src/autobots/data_model/id.py`
- Why: `ID` and `OptionalID` are the id mixins on skill find and update models. `ID.id` uses alias `"id"`.
- Important dependencies: `pydantic`.
- Dependencies copied: not applicable.

### `src/autobots/data_model/MongoId.py`

- Original: `src/autobots/data_model/MongoId.py`
- Why: `MongoID.id` is required and aliased to `_id`. `SkillDoc` and `SkillLiteDoc` extend it.
- Important dependencies: `pydantic`.
- Dependencies copied: not applicable.

### `src/autobots/data_model/user_id.py`

- Original: `src/autobots/data_model/user_id.py`
- Why: `UserId.user_id` is required on `SkillDocCreate`.
- Important dependencies: `pydantic`.
- Dependencies copied: not applicable.

### `src/autobots/data_model/space_id.py`

- Original: `src/autobots/data_model/space_id.py`
- Why: `OptionalSpaceId.space_id` is optional. `SpaceId` is also used as a type in `shared_with`, which is declared as `List[SpaceId | str]`.
- Important dependencies: `pydantic`.
- Dependencies copied: not applicable.

### `src/autobots/data_model/created_at.py`

- Original: `src/autobots/data_model/created_at.py`
- Why: `CreatedAt.created_at` defaults through `Clock.datetime_now` and is typed as `pydantic_extra_types.pendulum_dt.DateTime`.
- Important dependencies: `src.autobots.core.clock.clock.Clock`.
- Dependencies copied: no. `clock.py` imports `SettingsProvider` for its timezone helper. The timestamp default used by this mixin is `datetime.now()` inside `Clock.datetime_now`.

### `src/autobots/data_model/updated_at.py`

- Original: `src/autobots/data_model/updated_at.py`
- Why: Same clock default for `updated_at` on skill documents.
- Important dependencies: `Clock`.
- Dependencies copied: no. Same reason as `created_at.py`.

### `src/autobots/conn/weaviate/abstract_vector_db_client.py`

- Original: `src/autobots/conn/weaviate/abstract_vector_db_client.py`
- Why: Provider-shaped vector interface already in the repo: `ensure_class_exists`, `upsert_objects` (optional precomputed `vectors`), `search` (`query_text` or `query_vector`), `get_by_ids`, `delete_by_ids`, `delete_by_filter`, `generative_search`, `close`. The docstring names Weaviate, Qdrant, and Pinecone as intended backends. Only Weaviate implements this class in the copied tree.
- Important dependencies: none inside the repo.
- Dependencies copied: not applicable.

### `src/autobots/conn/weaviate/weaviate_client.py`

- Original: `src/autobots/conn/weaviate/weaviate_client.py`
- Why: The Weaviate v4 implementation. Upsert requires each object to have `uuid`. A passed vector is sent as `batch.add_object(vector=...)`. Search uses `near_vector` when `query_vector` is set, otherwise `near_text` for `search_type="vector"`, and `hybrid` when `search_type="hybrid"`. `ensure_class_exists` creates a collection with the caller-supplied `vectorizer_config`.
- Important dependencies: `weaviate` SDK, `tenacity`, `SettingsProvider` (imported; the constructor takes `url` and `api_key` as arguments).
- Dependencies copied: `abstract_vector_db_client.py`. `settings.py` was not copied.

### `src/autobots/conn/weaviate/weaviate_store.py`

- Original: `src/autobots/conn/weaviate/weaviate_store.py`
- Why: Higher-level store. Default collection name is `autobots_store`. `DEFAULT_WEAVIATE_PROPERTIES` is a document-chunk schema (`page_content`, `user_id`, `action_run_id`, media blobs, and others). `IMultimodalEmbeddings` extends the Chroma `Embeddings` class. Tenant ids are sanitized user ids, 4 to 64 characters of `[a-zA-Z0-9_-]`.
- Important dependencies: `weaviate`, `numpy`, `src.autobots.conn.chroma.chroma.Document` and `Embeddings`, `SettingsProvider`, the two Weaviate modules above.
- Dependencies copied: `chroma.py`, `abstract_vector_db_client.py`, `weaviate_client.py`. `settings.py` was not copied.

### `src/autobots/conn/chroma/chroma.py`

- Original: `src/autobots/conn/chroma/chroma.py`
- Why: Defines `Embeddings`, the embedder base class `weaviate_store.py` imports. `embed_documents` and `embed_query` are abstract. `aembed_documents` and `aembed_query` run those methods in an executor. The same file also contains the Chroma store. It was copied whole so the reference text stays unmodified.
- Important dependencies: ChromaDB and the rest of that store. The `Embeddings` class itself depends on `abc` and the local `run_in_executor`.
- Dependencies copied: not applicable for the ABC. The rest of the Chroma client stack was not copied as separate files because it lives in this one module.

### `src/autobots/conn/pinecone/pinecone.py`

- Original: `src/autobots/conn/pinecone/pinecone.py`
- Why: Shows that the Pinecone client is fully commented out. The commented constructor mentions index `serverless-index-1536` and `dimension = 1536`, and an OpenAI embedding client. That code does not run.
- Important dependencies: none at runtime. The file is comments.
- Dependencies copied: not applicable.

### `src/autobots/conn/pinecone/__init__.py`

- Original: `src/autobots/conn/pinecone/__init__.py`
- Why: Package marker. It contains one comment URL and does not import `pinecone.py`.
- Important dependencies: none.
- Dependencies copied: not applicable.

### `src/autobots/conn/openai/openai_embeddings/embedding_model.py`

- Original: `src/autobots/conn/openai/openai_embeddings/embedding_model.py`
- Why: Request and response models for the OpenAI embeddings call. `EmbeddingReq.model` is a `Literal["text-embedding-ada-002"]` with that default. `EmbeddingData.embedding` is `List[float]`. No dimension field is declared.
- Important dependencies: `pydantic`.
- Dependencies copied: not applicable.

### `src/autobots/conn/openai/openai_embeddings/openai_embeddings.py`

- Original: `src/autobots/conn/openai/openai_embeddings/openai_embeddings.py`
- Why: `OpenaiEmbeddings.embeddings` calls `client.embeddings.create` with `EmbeddingReq.model_dump()` and parses `EmbeddingRes`. The client is injected. This class does not choose Azure versus OpenAI by itself.
- Important dependencies: `openai` SDK, `embedding_model.py`, `tenacity`.
- Dependencies copied: `embedding_model.py`. `openai_client.py`, which builds the Azure or OpenAI client from settings, was not copied.

### `src/autobots/skills/__init__.py`

- Original: `src/autobots/skills/__init__.py`
- Why: Package marker. The body is the comment `# Skills package`.
- Important dependencies: none.
- Dependencies copied: not applicable.

### `src/autobots/skills/skill_doc_model.py`

- Original: `src/autobots/skills/skill_doc_model.py`
- Why: Product skill schema. Collection name `Skills`. Fields are `name`, `blocks: DataBlocks`, `is_published`, `shared_with`, plus user, space, and timestamps. No version, evidence, or embedding field.
- Important dependencies: `DataBlocks` and the data-model mixins.
- Dependencies copied: `id.py`, `MongoId.py`, `user_id.py`, `space_id.py`, `created_at.py`, `updated_at.py`. `common_action_models.py` (`DataBlocks`) was not copied.

### `src/autobots/skills/skill_crud.py`

- Original: `src/autobots/skills/skill_crud.py`
- Why: `SkillCRUD` subclasses `CRUDBase` and declares index `sk_shared_with_idx` on `(shared_with, space_id, updated_at)`.
- Important dependencies: `CRUDBase`, `get_mongo_db`, the skill models, `pymongo.IndexModel`.
- Dependencies copied: `mongo_base.py`, `mongo_base_crud.py`, `mongo_base_model.py`, `skill_doc_model.py`.

### `src/autobots/skills/user_skills.py`

- Original: `src/autobots/skills/user_skills.py`
- Why: Product skill service. `create` rejects a second skill with the same name for the user, and rejects more than 50 blocks. List, get, get-by-name, and update go through `SkillCRUD`.
- Important dependencies: FastAPI, Motor, `UserORM`, `SettingsProvider`, the skill models and CRUD.
- Dependencies copied: skill models and `skill_crud.py`. `user_orm_model.py` and `settings.py` were not copied.

### `src/autobots/api/v1/api_skills/api_skills.py`

- Original: `src/autobots/api/v1/api_skills/api_skills.py`
- Why: HTTP surface. Router prefix `/skills`. Handlers depend on `get_mongo_db` and call `UserSkills`.
- Important dependencies: FastAPI auth, `UserSkills`, space member lookup.
- Dependencies copied: `user_skills.py` and the skill models. Auth and space modules were not copied.

### `src/autobots/event_result/event_result_model.py`

- Original: `src/autobots/event_result/event_result_model.py`
- Why: Source-run document. Collection `EventResults`. `EventType` includes `action_run`, `action_graph_run`, `action_team_run`, `tool_run`, and `datastore_put`. `id` is aliased to `_id`. `user_id` is required on the stored document. `file_url` is optional on `EventResultDoc`, `EventResultLiteDoc`, and `EventResultUpdate`. `parent_action_result_id` is optional on `EventResultCreate`.
- Important dependencies: `TextObj`, `Clock`, `CollectionDocSearch`, space and updated-at mixins.
- Dependencies copied: `mongo_base_model.py`, `space_id.py`, `updated_at.py`. `common_action_models.py` (`TextObj`) and `clock.py` were not copied.

### `src/autobots/run_metrics/run_metrics_doc_model.py`

- Original: `src/autobots/run_metrics/run_metrics_doc_model.py`
- Why: `TERMINAL_STATUSES` is `success`, `error`, and `cancelled`. The file imports those statuses from `EventResultStatus`.
- Important dependencies: `event_result_model.py`, `UserId`, `OptionalSpaceId`.
- Dependencies copied: `event_result_model.py`, `user_id.py`, `space_id.py`. The rest of the metrics writer was not copied.

### `src/autobots/llm/tools/tool_result/tool_result_doc_model.py`

- Original: `src/autobots/llm/tools/tool_result/tool_result_doc_model.py`
- Why: `ToolRun` is `tool_name`, `tool_args`, and optional `output`. `TERMINAL_TOOL_RUN_STATUSES` adds `stuck` to the three run-level terminal statuses. `ToolResultDoc` extends `EventResultDoc`.
- Important dependencies: `event_result_model.py`.
- Dependencies copied: `event_result_model.py`.

## Intentionally not copied

| Path | Why it was left out |
| --- | --- |
| `src/autobots/core/settings.py` | Credential configuration module. It declares `MONGO_CONN`, `WEAVIATE_API_KEY`, `PINECONE_API_KEY`, `AZURE_OPENAI_EMBEDDINGS_API_KEY`, and many other secret fields. Values read in this inspection were empty defaults plus a default embeddings base URL. The file was not copied so this workspace does not carry the application's secret surface. Field names that matter are recorded in `reference/architecture-notes.md`. |
| `src/autobots/conn/openai/openai_client.py` | Builds live Azure and OpenAI clients from those settings. The embeddings wiring is three constructor arguments in `get_azure_openai` (lines 180–182). The rest of the client is unrelated. |
| `src/autobots/core/clock/clock.py` | `CreatedAt` calls `Clock.datetime_now`, which is `datetime.now()`. The module also reads `SettingsProvider` for timezones. |
| `src/autobots/action/action/common_action_models.py` | Defines `DataBlocks` and `TextObj`, and also the broader action payload models. Too wide to copy for the two type names. |
| `src/autobots/action/action_result/user_action_result.py` | Execution reader and writer. Inspected. Not copied, so this workspace does not include the run pipeline. Behavior used for trace linkage is in the architecture notes. |
| `src/autobots/action_graph/action_graph_result/user_action_graph_result.py` | Same reason. Graph fetch behavior is noted from the inspected method. |
| `src/autobots/action_team/action_team_result/user_action_team_result.py` | Same reason. Team fetch behavior is noted from the inspected method. |
| `src/autobots/llm/tools/tool_result/user_tool_result.py` | Tool fetch is short and Mongo-only. Noted from the inspected method. The model file was copied instead. |
| `src/autobots/files/user_files.py` | Object-storage prefix helper. Inspected for the key prefix. Not copied. |
| `src/autobots/experience_memory/` | Untracked work already in the checkout. Not adopted, moved, or copied. |
| `tests/experience_memory/` | Same untracked work. |
| `src/autobots/core/url_utils.py` | Staged change already in the checkout. Unrelated to Skill Memory. Not copied. |
| `tests/crud/crud_mongo_db/test_crud_mongo_db.py` | Opens a live Mongo client and drops a collection. Not copied. |
| `.env`, credentials, dumps, caches, virtual environments | Excluded by the copy rules. None were read into this folder. |

## Already in `Write Path`, not copied again

Trace-normalization episode schema and notes stay in `Write Path/trace-normalization/`. They were not duplicated into `autobots-reference/`.

- `trace-normalization/schema/episode.schema.json`
- `trace-normalization/reference/trace-formats.md`
- `trace-normalization/reference/ordering-and-fallbacks.md`
- `trace-normalization/reference/validation.md`
- `trace-normalization/normalize_trace.py`
