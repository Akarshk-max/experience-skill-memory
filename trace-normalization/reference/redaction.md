# Redaction and secret handling

The normalizer applies the two existing Autobots helpers. It does not add a new secret list and it does not call a provider.

## Key removal

`ActionTools._SENSITIVE_AUTH_KEYS` in `llm/tools/action_tools.py` is the key set. `_filter_auth` drops a key on exact, case-sensitive match and recurses into the kept values. Datetimes become ISO strings. The normalizer uses that same set:

`access_token`, `refresh_token`, `code`, `id_token`, `basic_token`, `api_key`, `management_api_key`, `consumer_key`, `consumer_secret`, `token_secret`, `client_secret`, `password`, `private_key`, `ssl_cert_path`, `ssl_key_path`, `fb_exchange_token`, `token`, `bearer_token`, `csrf_token`, `user_token`, `app_key`, `license_key`, `secret`, `auth_code`, `service_account_json`, `incoming_webhook`, `aws_access_key_id`, `aws_secret_access_key`, `private_key_path`, `public_certificate`, `connection_string`, `credentials_info`, `link_token_hash`, `external_user_id`, `external_chat_id`, `external_username`, `telegram_user_id`, `telegram_chat_id`, `telegram_username`.

A dropped key is removed. It is not replaced with a placeholder. The names `code`, `token`, and `secret` match every field with that exact name, including fields that may not be credentials. That is the source helper's behavior.

`Access_Token` and other case variants are not in the set, so they are not removed. That is a gap in the source helper.

## Text patterns

`redact_text` in `conn/grok/grok_chat/grok_tool_executor.py` (duplicated by the Deepseek executor) replaces:

- `(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)\b\s*[:=]\s*([^\s,;]+)`
- `(?i)\b(bearer)\s+([a-z0-9\-\._=]+)`

with `{name}: ***REDACTED***`.

A JSON string such as `"access_token": "value"` does not match the first pattern, because a quote sits between the name and the colon. The normalizer covers that shape by parsing a string when the whole string is a JSON object or array, then applying the key set, then writing the JSON back. A secret inside a larger sentence is not parsed as JSON and is redacted only when a text pattern matches.

## Where redaction runs

Redaction applies to `action`, `observation`, `tool_arguments`, `tool_result`, `error`, `action_name`, `task_intent`, `task_summary`, `error_message`, human-question text and answer text, and a progress-delta `rationale` when `apply_progress_grades` stores one.

It does not apply to ids, `call_id`, `node_id`, `provenance_node_id`, `role`, `member_id`, `action_id`, `action_run_id`, statuses, timestamps, `user_id`, or `episode_id`.

## Values that are not copied

These are omitted before redaction, so they never enter the episode:

- `config`, other than reading `input_archive` and `tool_errors`
- `shared_with`, `urls`, `user_manual`
- `time_saved_per_run`, `dollar_cost_per_hour`
- human-question option descriptions, answer urls, and `answered_by`
- `reasoning` and `compaction` items, including `encrypted_content`

A `file_url` query string is removed. The path is kept so the object can still be identified. A warning records that the query was removed. The source comment on canonical file URLs says a stored `file_url` should not be a presigned URL; the normalizer does not depend on that comment being true of every document.

Warnings must not contain secret values. They name fields and node ids only.

## Known gaps

- Case-variant keys survive.
- Unlabeled secret strings with no `key: value` or `bearer` form survive.
- A JSON secret embedded in a larger string survives unless a text pattern matches.
- The broad keys `code`, `token`, and `secret` remove non-credential fields of those names.
- `user_id`, `member_id`, and `parent_action_result_id` are identifiers and are kept on purpose.
