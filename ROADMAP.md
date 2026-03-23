# Roadmap

Potential improvements to the Audio Text Backend.
Items are ordered by priority: correctness & data integrity → security → reliability & operations → user-facing features → developer productivity → technical debt.

---

## 1. SIGTERM Handling in Workers

**Current state:** `worker.py` calls `asyncio.run(_run())` with no signal handling. When Cloud Run Jobs sends SIGTERM (task timeout, manual stop, node preemption), Python's default handler raises `SystemExit` immediately, cutting the process short without:
- updating the job status to `FAILED` in the DB (leaving it stuck at `PROCESSING`)
- nacking the Pub/Sub message (so the message is re-delivered after the ack deadline, but the next retry worker finds a PROCESSING row — which the current code re-marks as PROCESSING again, hiding the failure)

**Improvements:**
- Register a SIGTERM (and SIGINT) handler in `main()` that sets a cancellation event.
- Pass the event to `_run()` and check it before/after `await process_job()`.
- If interrupted mid-processing, mark the job `FAILED` with `error_message="Worker terminated by signal"` and nack the Pub/Sub message before exiting.
- Use `asyncio`'s `loop.add_signal_handler(signal.SIGTERM, ...)` pattern so the handler integrates cleanly with the running event loop.

---

## 2. Atomic Transactions in Workers

**Current state:**
- `session_scope()` in `db.py` explicitly rolls back only on `SQLAlchemyError`. Non-SQLAlchemy exceptions raised inside a session scope (e.g., `asyncio.CancelledError`, `RuntimeError`) get no explicit `rollback()` call — the transaction is abandoned and rolled back implicitly by asyncpg when the connection returns to the pool, but this implicit path is fragile.
- The job's final state update (`COMPLETED` or `FAILED`) and the Pub/Sub status publish happen in two separate I/O calls. If the DB commit succeeds but the Pub/Sub publish fails (or vice versa), the DB and the frontend go out of sync — the job appears completed/failed in the DB but no WebSocket notification is ever sent.

**Improvements:**
- Widen the `except` clause in `session_scope()` to catch `BaseException` (not only `SQLAlchemyError`) so all paths trigger an explicit rollback:
  ```python
  except BaseException:
      await session.rollback()
      raise
  ```
- Consider a **transactional outbox** pattern for the critical COMPLETED/FAILED transition: write a pending outbox row in the same DB transaction as the status update; a background task or the same coroutine publishes the Pub/Sub message and deletes the outbox row after a confirmed publish — guaranteeing at-least-once delivery.

---

## 3. Dead-Letter Queue for Failed Jobs

**Current state:** If a Cloud Run Job fails after the maximum retry count (`--max-retries 3`), the message is dropped. The DB record stays in `PROCESSING` status forever — the user sees no error, no notification, and the Pub/Sub message is silently discarded.

**Improvements:**
- Add a dead-letter topic (`transcription-jobs-dead-letter`) to all three Pub/Sub pull subscriptions in Terraform.
- Add a subscription on the dead-letter topic that pushes to the API's `/pubsub/status` with a synthetic `FAILED` payload, or
- Add a Cloud Scheduler job that queries the DB for jobs stuck in `PROCESSING` for more than N minutes and marks them `FAILED` with an appropriate error message.

---

## 4. Job Timeout / Stuck Job Detection

**Current state:** A Cloud Run Job task timeout is set to 900 s (`--task-timeout 900`). If the job is killed by the timeout, the Pub/Sub message is nacked and retried. However, if the DB row is already in `PROCESSING` when the retry runs, the worker updates it again correctly — but edge cases exist:
- If the job crashes before reaching the `nack` path (e.g., OOM), the ack deadline expires and the message is redelivered, but the DB row remains `PROCESSING` with no error.
- A stuck WebSocket client waits indefinitely.

**Improvements:**
- Add a `started_at` / `updated_at` timestamp column to `TranscriptionJob`.
- Add a Cloud Scheduler health-check job: find rows in `PROCESSING` for more than `task_timeout + buffer`, mark them `FAILED`.
- Send a WebSocket keepalive message that includes the current DB status so the client can self-correct.

---

## 5. Security Hardening

- **Pub/Sub push authentication:** The `/api/v1/pubsub/status` endpoint currently accepts any POST request. Validate the OIDC token in the `Authorization` header that Cloud Pub/Sub sends with authenticated push subscriptions.
- **Presigned URL scope:** `get_presigned_url` returns a PUT URL without verifying the caller is authenticated. Add authentication if the API is ever exposed beyond the Load Balancer.
- **Secret rotation:** AWS credentials and DB passwords are stored in Secret Manager but referenced as `latest`. Pin to a specific version in `deploy-cloud.sh` and update the reference as part of the secret rotation procedure.
- **VPC egress:** Workers use `--vpc-egress private-ranges-only`. Verify S3 traffic routes through a NAT gateway (not the public internet via the VPC connector) — or accept that S3 calls go over the public internet and ensure credentials are scoped to the single bucket.

---

## 6. Database Migrations at Deploy Time

**Current state:** The migration run in `start-api.sh` is commented out. Alembic migrations must be run manually or are skipped (`AUDIO_TEXT_DB_SKIP_MIGRATION_ENV=false` is set but the code path is unclear).

**Improvements:**
- Uncomment and enable the Alembic migration step in `start-api.sh`.
- Add a migration-only Cloud Run Job (`audio-migrate`) that runs `alembic upgrade head` as a pre-deploy step in `deploy-cloud.sh`, before the new API revision receives traffic — prevents schema/code mismatch during rolling deploys.

---

## 7. WebSocket Architecture — Multi-Instance Problem

**Current state:** `JobUpdateManager` is an in-memory singleton. WebSocket connections are registered on the instance that accepted the TCP connection. Pub/Sub push messages are delivered to a random API instance. With `--workers 1` and `--session-affinity` on Cloud Run, the same instance handles both — but this is fragile: a new instance spin-up, a rolling deploy, or a cold-start breaks the guarantee.

**Options (in order of complexity):**

### Option A — DB polling fallback (no infrastructure changes)
The frontend polls `GET /job/status/{job_id}` every few seconds as a fallback when no WebSocket update is received within a timeout. The DB is always the source of truth. Zero backend changes, resilient to any routing mismatch.

### Option B — Redis Pub/Sub fan-out (recommended for production scale)
```
Worker → transcription-status topic
       → Pub/Sub push → any API instance → UPDATE db
                                         → PUBLISH to Redis channel "job:{job_id}"
       All API instances subscribe to Redis channel
       → Each instance checks its own JobUpdateManager
       → Instance with the live WS calls send_json()
```
- Add a Redis instance (Cloud Memorystore or a small self-hosted container).
- `update_job_status()` publishes to Redis after the DB write.
- A background task per API instance subscribes to Redis and calls `manager.broadcast()`.
- Removes the single-worker and session-affinity constraints entirely.

### Option C — Server-Sent Events instead of WebSockets
Replace WebSockets with SSE (`GET /job/stream/{job_id}`). SSE is HTTP/1.1, works through any load balancer without sticky sessions, and is simpler to implement. The same Redis fan-out or DB polling approach applies, but the client side is simpler.

---

## 8. S3 Cleanup Reliability

**Current state:** `run_transcription()` deletes the S3 file in its `finally` block with a best-effort warning on failure. If cleanup fails (network hiccup, permissions issue), the audio file persists indefinitely on S3 at cost.

**Improvements:**
- Add an S3 object lifecycle rule (e.g., `Expiration: 1 day`) as a safety net — objects are automatically deleted even if the cleanup call fails.
- Log cleanup failures to a separate Cloud Logging metric so they can be alerted on.

---

## 9. Replace SendGrid with a Generic SMTP Email Handler

**Current state:** `action/email.py` is tightly coupled to the `sendgrid` SDK (`SendGridAPIClient`, `Mail`). The `Email` config dataclass exposes a `sendgrid_api_key` field, and `sendgrid==6.11.0` is a hard dependency in `pyproject.toml`. SendGrid's free tier is limited and the paid plan is an active cost.

**What needs to change (full implementation path):**
1. **`action/email.py`** — Replace `EmailService` with an abstract base + a concrete `SMTPEmailService`:
   ```python
   class AbstractEmailService(ABC):
       @abstractmethod
       def send_transcription(self, job: TranscriptionJob, recipient_email: str) -> bool: ...

   class SMTPEmailService(AbstractEmailService):
       # uses aiosmtplib (async) or smtplib (sync) with STARTTLS
   ```
2. **`config.py`** — Replace `sendgrid_api_key: str` in `Email` with generic SMTP fields:
   ```python
   @dataclass
   class Email:
       smtp_host: str
       smtp_port: int
       smtp_user: str
       smtp_password: str
       from_address: str
       from_name: str
   ```
3. **`config.ini`** — Replace `sendgrid_api_key = AUDIO_TEXT_SENDGRID_API_KEY_ENV` with the new SMTP env var mappings.
4. **`pyproject.toml`** — Remove `sendgrid==6.11.0`; add `aiosmtplib` (async SMTP, no extra dependencies).
5. **`scripts/deploy-cloud.sh`** — Update Secret Manager references from `SENDGRID_API_KEY` to the new SMTP credentials.
6. **Provider compatibility** — SMTP works with any provider: AWS SES (`email-smtp.{region}.amazonaws.com:587`), Brevo, Postmark, Mailgun, or self-hosted Postfix — no vendor lock-in.

---

## 10. Cancel Job from Frontend

**Current state:**
- The frontend `cancelTranscription()` hook only disconnects the WebSocket and resets local UI state — it makes **no API call** to the backend.
- There is no cancel endpoint on the backend (`POST /job/{job_id}/cancel` does not exist).
- `JobStatus` has no `CANCELLED` value; there is no mechanism to interrupt an in-flight Cloud Run Job worker.

**What is missing (full implementation path):**
1. **Backend — DB model:** Add `CANCELLED = "cancelled"` to `JobStatus` and create an Alembic migration to update the `ENUM` type in Postgres.
2. **Backend — API endpoint:** `POST /job/{job_id}/cancel` — validates job is in `PENDING` or `PROCESSING` state and marks it `CANCELLED`.
3. **Backend — Worker guard:** `process_job()` should check job status at the start and re-check it after the long `run_transcription()` call; if the DB status is already `CANCELLED`, skip the final update and ack the message cleanly (no error, no retry).
4. **Backend — PENDING fast path:** If the job is still `PENDING` (worker not yet started), the cancel endpoint can also nack the Pub/Sub message immediately so the Cloud Run Job is never triggered — requires storing the Pub/Sub message ID alongside the job row.
5. **Frontend:** `cancelTranscription()` should call `POST /job/{job_id}/cancel` before disconnecting the WebSocket.

---

## 11. CI/CD Pipeline

**Current state:** Deployment is manual (`./scripts/deploy-cloud.sh`). There is no automated test run, no image build gate, and no rollback mechanism.

**Improvements:**
- Add a GitHub Actions (or Cloud Build) workflow:
  1. On PR: run linting (`ruff`), type checking (`mypy`), and unit tests.
  2. On merge to `main`: build Docker images, push to GCR, deploy API and workers via the deploy script.
- Add a `--no-traffic` deploy step + smoke test before shifting traffic (Cloud Run supports traffic splitting).
- Tag images with the Git SHA instead of `latest` so rollback is a single `gcloud run deploy --image` command.

---

## 12. Testing

**Current state:** No test suite exists (`dev/test.py` is a scratch file).

**Improvements:**
- Unit tests for `action/` layer using `pytest` + `pytest-asyncio`, mocking DB and Pub/Sub.
- Integration tests for the API using `httpx.AsyncClient` + `TestClient` against an in-memory SQLite DB and the Pub/Sub emulator.
- Worker integration test: publish a message to the emulator, assert `process_job` is called with the correct `JobPayload`.
- Add test coverage reporting to CI.

---

## 13. Observability

**Current state:** Logging is the only observability mechanism. There are no metrics, no tracing, and no structured log format (logs are plain text).

**Improvements:**
- Switch to structured JSON logging (`python-json-logger`) so Cloud Logging can index and filter on fields like `job_id`, `status`, `model`, `processing_time`.
- Add Cloud Monitoring custom metrics:
  - Jobs enqueued / completed / failed per tier.
  - Transcription processing time (histogram).
  - Pull subscription message backlog (already available as a GCP metric).
- Add OpenTelemetry tracing across the API → Pub/Sub → Worker path using `opentelemetry-sdk` + Cloud Trace exporter.
- Add a `/metrics` endpoint (Prometheus format) for local development monitoring.

---

## 14. Rate Limiting

**Current state:** `RateLimitMiddleware` uses in-memory `defaultdict` per IP. Works correctly with `--workers 1` on a single instance, but:
- Memory grows unboundedly if cleanup is not triggered (cleanup only runs on the next request from the same IP).
- State is lost on container restart.
- Does not scale across multiple Cloud Run instances (each has its own counters).
- Cloud Armor already enforces a coarser rate limit (100 req/min) at the load balancer level.

**Improvements:**
- Move rate limiting to Cloud Armor entirely (already configured) and remove the in-process middleware, or
- Replace the in-memory store with Redis (`redis-py` with a sliding-window Lua script) to get accurate distributed rate limiting, or
- At minimum, add a background cleanup task that periodically prunes stale entries from `minute_requests` / `hour_requests` to prevent unbounded memory growth.

---

## 15. Pub/Sub Message Schema Validation

**Current state:** The job payload is a raw `dict` passed through `JobPayload(**json.loads(...))`. If `publish_job` signature changes (e.g., a field is added or renamed), deserialization silently fails at the worker side with a confusing `TypeError`.

**Improvements:**
- Use Pydantic for `JobPayload` instead of `@dataclass` — free validation + clear error messages on schema mismatch.
- Version the message schema (e.g., add a `schema_version: int = 1` field) so future breaking changes can be handled gracefully with a migration path.

---

## 16. Configuration Refactoring

**Current state:** A single `Config` object loads all sections (`Middleware`, `Database`, `AWS`, `Whisper`, `PubSub`, `Email`, `Worker`, `File`) at startup regardless of which component is running. The Cloud Run Job worker loads CORS origins, email config, and middleware settings it never uses; the API loads Whisper and worker-tier settings it never uses.

**Improvements:**

- Split into two focused config classes:
  - `ApiConfig` — `Middleware`, `Database`, `AWS`, `PubSub` (topics + status sub + push endpoint), `Email`, `File`
  - `WorkerConfig` — `Database`, `AWS`, `PubSub` (jobs subs + status topic), `Whisper`, `Worker`
- Each entrypoint (`api.py`, `worker.py`, `local_worker.py`) imports only its own config class.
- Fail fast with clear error messages if a required env var is missing for the specific component — instead of silently loading empty strings.
- Remove `Auto-load on import` at the bottom of `config.py`; each entrypoint calls `bootstrap_configuration()` explicitly (already done in workers, inconsistent in the API).
