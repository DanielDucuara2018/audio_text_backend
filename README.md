# Audio Text Backend

A scalable FastAPI backend service for converting audio files to text using **faster-whisper** (CTranslate2) with asynchronous processing, S3 storage, and real-time WebSocket updates.

> **⚡ Now 75-80% faster and 60% cheaper** with faster-whisper integration!

## Architecture Overview

```mermaid
graph TB
   Client[Client Application] -- "1. Request presigned url" --> API[FastAPI API Server<br/>:3203]
   Client -- "2. Upload file" --> S3[AWS S3 Storage<br/>eu-west-3]

   Client -- "3.1 Request Transcription" --> API
   API -- "3.2 Add job entry" --> DB[(PostgreSQL Database<br/>:5432)]
   API -- "3.3 Route to queue by model size" --> Redis[(Redis Cache/Queue<br/>:6379)]

   Redis -- "4.1 Small models" --> WorkerSmall[Celery Worker Small<br/>audio_small queue<br/>concurrency=4]
   Redis -- "4.1 Medium models" --> WorkerMedium[Celery Worker Medium<br/>audio_medium queue<br/>concurrency=2]
   Redis -- "4.1 Large models" --> WorkerLarge[Celery Worker Large<br/>audio_large queue<br/>concurrency=1]

   WorkerSmall -- "4.2 Download & transcribe" --> S3
   WorkerMedium -- "4.2 Download & transcribe" --> S3
   WorkerLarge -- "4.2 Download & transcribe" --> S3

   WorkerSmall -- "4.3 Publish updates" --> Redis
   WorkerMedium -- "4.3 Publish updates" --> Redis
   WorkerLarge -- "4.3 Publish updates" --> Redis

   Client -- "5.1 Connect to WS" --> API
   API -- "5.2 Subscribe to job_updates pubsub channel" --> Redis
   API -- "5.3 Send updates" --> Client

   subgraph "Docker Network: 169.254.9.0/24"
      API_CONTAINER[app: 169.254.9.2]
      DB_CONTAINER[postgres: 169.254.9.3]
      REDIS_CONTAINER[redis: 169.254.9.4]
      WORKER_CONTAINER[celery-worker: 169.254.9.5]
   end
```

### Component Interaction Flow

1. **File Upload**: Client uploads audio file via REST API
2. **Job Creation**: API creates job record in PostgreSQL
3. **Storage**: File uploaded to S3 with presigned URL
4. **Smart Queue Routing**: API routes job to appropriate queue based on model size
   - Small models (tiny/base/small) → `audio_small` queue (high concurrency)
   - Medium models → `audio_medium` queue (moderate concurrency)
   - Large models (v2/v3) → `audio_large` queue (low concurrency)
5. **Transcription**: Dedicated workers process tasks with optimal resource allocation
6. **Real-time Updates**: Progress updates sent via Redis pub/sub to WebSocket
7. **Completion**: Results stored in database, client notified

## Features

- **High Performance**: 75-80% faster transcription with faster-whisper (CTranslate2)
- **Cost Efficient**: 60-70% reduction in compute costs with int8 quantization
- **Multi-Queue System**: Smart task routing by model size for optimal resource usage
- **Async Processing**: Non-blocking audio processing using Celery with advanced configuration
- **S3 Storage**: Scalable file storage with S3-compatible services
- **Real-time Updates**: WebSocket support for live progress updates with singleton pattern
- **Job Management**: Track processing status and history
- **Multiple Formats**: Support for MP3, WAV, M4A, FLAC, OGG, AAC, OPUS
- **Advanced Features**: Word-level timestamps, language detection, VAD filtering
- **Microservices Architecture**: Containerized services with Docker
- **Database Migrations**: Alembic for schema management
- **Resource Management**: Context managers with reference counting for safe cleanup
- **Configuration Management**: Separated API and Worker configs for minimal resource loading

## Project Structure

```
audio_text_backend/
├── README.md                           # This documentation file
├── config.ini                         # Unified application configuration
├── docker-compose.yml                 # Docker services orchestration
├── Dockerfile                         # Application container definition
├── pyproject.toml                     # Python project configuration
├── setup.py                          # Python package setup
├── supervisord.conf                   # Process supervision config
├── alembic/                           # Database migration files
│   ├── versions/                      # Migration versions
│   └── alembic.ini                    # Alembic configuration
├── pgsql/
│   └── init.d/                        # PostgreSQL initialization scripts
└── audio_text_backend/                # Main application package
    ├── __init__.py
    ├── config.py                      # Unified configuration management
    ├── db.py                          # Database connection & management
    ├── debuger.py                     # Development server runner
    ├── errors.py                      # Custom exception classes
    ├── typing.py                      # Custom type definitions
    ├── utils.py                       # Utility functions
    ├── model/                         # SQLAlchemy models
    │   ├── __init__.py
    │   ├── base.py                    # Base model with CRUD operations
    │   ├── resource.py                # Resource mixin (timestamps)
    │   └── transcription_job.py       # Job model definition
    ├── schema/                        # Pydantic schemas
    │   ├── audio.py                   # Audio-related schemas
    │   └── job.py                     # Job-related schemas
    ├── action/                        # Business logic layer
            ├── __init__.py
            ├── audio.py                   # Audio file handling & S3 operations
            ├── job.py                     # Job management & Redis pub/sub (singleton pattern)
            └── tasks.py                   # Celery task definitions
    ├── celery/                        # Celery configuration
    │   └── app.py                     # Celery application setup
    └── api/                           # FastAPI routers
        ├── __init__.py
        ├── api.py                     # Main FastAPI application
        └── routers/
            ├── audio.py               # Audio upload endpoints
            └── job.py                 # Job status & WebSocket lifecycle management
```

## Configuration

The application uses a unified `config.ini` file for all configuration management. Both API and Worker services load from the same configuration file, with all configuration values sourced from environment variables defined in `.env` file.

### Middleware Configuration

```ini
[middleware]
cors_origins = AUDIO_TEXT_CORS_ORIGINS_ENV
rate_limit_per_minute = AUDIO_TEXT_RATE_LIMIT_PER_MINUTE_ENV
rate_limit_per_hour = AUDIO_TEXT_RATE_LIMIT_PER_HOUR_ENV
```

### Database Configuration

```ini
[database]
database = AUDIO_TEXT_DB_NAME_ENV
host = AUDIO_TEXT_DB_HOST_ENV
password = AUDIO_TEXT_DB_PASSWORD_ENV
port = AUDIO_TEXT_DB_PORT_ENV
user = AUDIO_TEXT_DB_USER_ENV
ref_table = AUDIO_TEXT_DB_REF_TABLE_ENV
```

### Redis Configuration

```ini
[redis]
host = AUDIO_TEXT_REDIS_HOST_ENV
port = AUDIO_TEXT_REDIS_PORT_ENV
pub_sub_channel = AUDIO_TEXT_REDIS_PUB_SUB_CHANNEL_ENV
```

### AWS S3 Configuration

```ini
[aws]
bucket_name = AUDIO_TEXT_AWS_BUCKET_NAME_ENV
access_key = AUDIO_TEXT_AWS_ACCESS_KEY_ENV
secret_key = AUDIO_TEXT_AWS_SECRET_KEY_ENV
region = AUDIO_TEXT_AWS_REGION_ENV
```

### File Upload Configuration

```ini
[file]
max_size_mb = AUDIO_TEXT_MAX_FILE_SIZE_MB_ENV
allowed_audio_extensions = AUDIO_TEXT_ALLOWED_AUDIO_EXTENSIONS_ENV
```

### Whisper Model Configuration

```ini
[whisper]
device = AUDIO_TEXT_WHISPER_DEVICE_ENV
compute_type = AUDIO_TEXT_WHISPER_COMPUTE_TYPE_ENV
cpu_threads = AUDIO_TEXT_WHISPER_CPU_THREADS_ENV
beam_size = AUDIO_TEXT_WHISPER_BEAM_SIZE_ENV
vad_filter = AUDIO_TEXT_WHISPER_VAD_FILTER_ENV
vad_min_silence_duration_ms = AUDIO_TEXT_WHISPER_VAD_MIN_SILENCE_MS_ENV
```

### Celery Worker Configuration

```ini
[celery]
serialization_format = json
timezone = UTC
task_acks_late = true
worker_prefetch_multiplier = 1
worker_max_tasks_per_child = 1000
task_soft_time_limit = 3600
task_time_limit = 3900
```

### Queue Routing Configuration

```ini
[celery:queues:tiny]
queue_name = AUDIO_TEXT_QUEUE_SMALL_ENV

[celery:queues:base]
queue_name = AUDIO_TEXT_QUEUE_SMALL_ENV

[celery:queues:small]
queue_name = AUDIO_TEXT_QUEUE_SMALL_ENV

[celery:queues:medium]
queue_name = AUDIO_TEXT_QUEUE_MEDIUM_ENV

[celery:queues:large-v2]
queue_name = AUDIO_TEXT_QUEUE_LARGE_ENV
retry_policy_max_retries = AUDIO_TEXT_QUEUE_LARGE_RETRY_MAX_ENV
retry_policy_interval_start = AUDIO_TEXT_QUEUE_LARGE_RETRY_START_ENV
retry_policy_interval_step = AUDIO_TEXT_QUEUE_LARGE_RETRY_STEP_ENV
retry_policy_interval_max = AUDIO_TEXT_QUEUE_LARGE_RETRY_MAX_INTERVAL_ENV

[celery:queues:large-v3]
queue_name = AUDIO_TEXT_QUEUE_LARGE_ENV
retry_policy_max_retries = AUDIO_TEXT_QUEUE_LARGE_RETRY_MAX_ENV
retry_policy_interval_start = AUDIO_TEXT_QUEUE_LARGE_RETRY_START_ENV
retry_policy_interval_step = AUDIO_TEXT_QUEUE_LARGE_RETRY_STEP_ENV
retry_policy_interval_max = AUDIO_TEXT_QUEUE_LARGE_RETRY_MAX_INTERVAL_ENV

[celery:queues:default]
queue_name = AUDIO_TEXT_QUEUE_DEFAULT_ENV
```

**Queue Routing Strategy:**

- **audio_small**: Tiny/base/small models (concurrency=4, max=10 instances)
- **audio_medium**: Medium models (concurrency=2, max=5 instances)
- **audio_large**: Large v2/v3 models (concurrency=1, max=3 instances)
- **audio_processing**: Fallback for unknown models

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for local development)
- Git

### 1. Clone and Setup

```bash
git clone <repository-url>
cd audio_text_backend

# Copy and configure environment
cp .env.template .env
# Edit .env with your AWS credentials and settings
```

### 2. Docker Setup (Recommended)

#### Worker Deployment Modes

The application supports two Celery worker deployment modes:

**1. Default Single Worker (Recommended for Development/Small Scale)**

- Single worker listens to **ALL queues** (audio_small, audio_medium, audio_large, audio_processing)
- Simpler setup with lower resource usage
- Suitable for development and small-scale deployments
- Concurrency: 2 workers

**2. Multi-Queue Workers (Advanced Testing)**

- **Three dedicated workers**, each optimized for specific model sizes:
  - `celery-worker-small`: Handles tiny/base/small models (concurrency=4)
  - `celery-worker-medium`: Handles medium models (concurrency=2)
  - `celery-worker-large`: Handles large-v2/large-v3 models (concurrency=1)
- Better resource isolation and performance testing
- Higher resource usage (3 containers)
- Mimics production scaling behavior

**⚠️ Important:** You must run **ONE mode at a time** - either default or multi-queue, not both.

#### Fast Development Start (Optimized)

```bash
# Quick start with DEFAULT SINGLE WORKER (listens to all queues)
./scripts/start-dev.sh

# Or with MULTI-QUEUE WORKERS for testing (small/medium/large)
./scripts/start-dev.sh --multi-queue
```

This enables Docker BuildKit for faster builds and provides:

- ✅ **60-85% faster builds** through advanced layer caching
- ✅ **Parallel processing** with BuildKit
- ✅ **Smart dependency management** (rebuilds only when needed)
- ✅ **Optimized volume mounting** for development
- ✅ **Multi-queue testing** option with `--multi-queue` flag

#### Standard Docker Setup

```bash
# Start with DEFAULT SINGLE WORKER
docker-compose --profile default up -d --build

# OR start with MULTI-QUEUE WORKERS
docker-compose --profile multi-queue up -d --build

# View logs (default worker)
docker-compose logs -f celery-worker

# View logs (multi-queue workers)
docker-compose --profile multi-queue logs -f celery-worker-small celery-worker-medium celery-worker-large

# Check service status
docker-compose ps
```

Both methods start:

- **FastAPI app** on `localhost:3203`
- **PostgreSQL** on `localhost:5432`
- **Redis** on `localhost:6379`
- **Celery worker(s)** for background processing (default or multi-queue)

#### Build Performance Optimizations

The Docker setup includes several optimizations:

- **Layer caching**: Dependencies installed before source code copy
- **Selective mounting**: Only development files are mounted as volumes
- **BuildKit features**: Parallel builds and advanced caching
- **Environment optimization**: Python bytecode and output buffering disabled

### 3. Local Development Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev,test]"

# Start individual services (requires Docker for Redis/PostgreSQL)
docker-compose up -d postgres redis

# Run database migrations
alembic upgrade head

# Start API server
uvicorn audio_text_backend.api.api:app --reload --host 0.0.0.0 --port 3203

# Start Celery worker (separate terminal)
celery -A audio_text_backend.celery.app worker --loglevel=info -Q audio_processing
```

### 4. Network Configuration (if using Docker hostnames)

```bash
# Add to /etc/hosts for hostname resolution
echo "169.254.9.2 audio-text" | sudo tee -a /etc/hosts

# SSH port forwarding (for remote access)
ssh -L 127.0.0.1:3203:audio-text:3203 username@server_ip
```

## API Documentation

### Core Endpoints

| Method | Endpoint                      | Description                     |
| ------ | ----------------------------- | ------------------------------- |
| `POST` | `/api/v1/job/transcribe`      | Launch the transcription        |
| `GET`  | `/api/v1/job/status/{job_id}` | Get job status and results      |
| `GET`  | `/api/v1/job/read`            | List recent jobs                |
| `WS`   | `/api/v1/job/ws/{job_id}`     | WebSocket for real-time updates |
| `GET`  | `/api/v1`                     | Health check endpoint           |
| `POST` | `/api/v1/audio/presigned-url` | Generate S3 upload URL          |

### Interactive API Documentation

- **Swagger UI**: `http://localhost:3203/docs`
- **ReDoc**: `http://localhost:3203/redoc`

## Usage Examples

### cURL Examples

```bash
# Check job status
curl "http://localhost:3203/api/v1/job/status/{job_id}"

# List all jobs
curl "http://localhost:3203/api/v1/job/read"

# Health check
curl "http://localhost:3203/api/v1"
```

### WebSocket Architecture

The WebSocket implementation follows a clean separation of concerns:

#### FastAPI Router Layer (`api/routers/job.py`)

- Manages WebSocket connection lifecycle (accept, close, error handling)
- Handles transport layer concerns
- Automatic connection cleanup on disconnect/error

#### Action Layer (`action/job.py`)

- **JobUpdateManager**: Singleton pattern with async context manager
- Handles Redis pub/sub subscription and message routing
- Connection tracking with reference counting for multi-context safety
- Business logic separation from transport concerns

#### Connection Flow

1. FastAPI accepts WebSocket connection
2. Action layer manages Redis pub/sub and connection tracking
3. Real-time updates flow: Celery → Redis pub/sub → WebSocket clients
4. On disconnect: FastAPI closes connection, action layer cleans tracking

## Architecture Components

### 1. FastAPI Application (`api/api.py`)

- **Purpose**: REST API server and WebSocket lifecycle management
- **Port**: 3203
- **Features**: CORS middleware, automatic OpenAPI documentation
- **WebSocket Responsibilities**: Connection accept/close, error handling, lifecycle management
- **Dependencies**: PostgreSQL, Redis

### 2. Celery Workers (`action/tasks.py`)

- **Purpose**: Asynchronous audio processing with multi-queue optimization
- **Queues**:
  - `audio_small`: Tiny/base/small models (concurrency=4)
  - `audio_medium`: Medium models (concurrency=2)
  - `audio_large`: Large v2/v3 models (concurrency=1)
  - `audio_processing`: Fallback queue
- **Tasks**: Download from S3, Whisper transcription, cleanup
- **Configuration**: Per-queue retry policies, optimized concurrency settings

### 3. PostgreSQL Database

- **Purpose**: Job metadata and results storage
- **Port**: 5432
- **Tables**:
  - `transcription_job`: Job status, results, metadata
- **Migrations**: Managed with Alembic

### 4. Redis Cache/Queue

- **Purpose**: Celery broker, result backend, pub/sub for WebSocket
- **Port**: 6379
- **Usage**:
  - Queue: `audio_processing` with custom routing
  - Pub/Sub: `job_updates` channel for real-time updates
  - Results: Celery task results with configurable backend

### 5. AWS S3 Storage

- **Purpose**: Audio file storage with presigned URLs
- **Features**: Automatic bucket creation, file cleanup
- **Security**: Temporary URLs for secure uploads

### 6. Configuration Management (`config.py`)

- **Purpose**: Unified configuration for both API and Worker services
- **Structure**: Single `config.py` module with all dataclasses
  - `Config`: Main config class containing all components
  - `Middleware`: CORS and rate limiting settings
  - `Database`: PostgreSQL connection details
  - `Redis`: Broker, backend, and pub/sub configuration
  - `AWS`: S3 storage settings
  - `File`: Upload validation rules
  - `Whisper`: Model execution settings
  - `Celery`: Worker configuration and queue routing
- **Benefits**: Simplified architecture, single source of truth, easier maintenance

### 7. WebSocket Manager (`action/job.py`)

- **Purpose**: Real-time progress updates via Redis pub/sub
- **Architecture**: Singleton pattern with async context manager
- **Features**:
  - Reference counting for multi-context safety
  - Automatic Redis resource cleanup
  - Connection tracking and lifecycle management
  - Separation of concerns: FastAPI handles WebSocket lifecycle, manager handles business logic

## Database Schema

### transcription_job Table

```sql
CREATE TABLE transcription_job (
    id VARCHAR PRIMARY KEY,                    -- Unique job identifier
    filename VARCHAR NOT NULL,                 -- Original filename
    url VARCHAR NOT NULL,                      -- S3 storage URL
    status job_status DEFAULT 'pending',       -- Job status enum
    result_text TEXT,                          -- Transcribed text
    error_message TEXT,                        -- Error details if failed
    processing_time_seconds INTEGER,           -- Processing duration
    description VARCHAR,                       -- Optional description
    creation_date TIMESTAMP WITH TIME ZONE,   -- Job creation time
    update_date TIMESTAMP WITH TIME ZONE      -- Last update time
);
```

## Monitoring and Debugging

### Service Health Checks

```bash
# Check all services
docker-compose ps

# View specific service logs
docker-compose logs -f app
docker-compose logs -f celery-worker
docker-compose logs -f postgres
docker-compose logs -f redis

# Database connection test
docker-compose exec postgres psql -U postgres -d audiotext -c "SELECT 1;"

# Redis connection test
docker-compose exec redis redis-cli ping
```

### Celery Monitoring

```bash
# View active tasks
celery -A audio_text_backend.celery.app inspect active

# View registered tasks
celery -A audio_text_backend.celery.app inspect registered

# View worker configuration
celery -A audio_text_backend.celery.app inspect conf

# View queue information
celery -A audio_text_backend.celery.app inspect active_queues

# Flower monitoring (if enabled)
# Visit http://localhost:5555
```

### Multi-Queue Celery Features

The Celery configuration includes advanced multi-queue optimization:

- **Smart Queue Routing**: Tasks automatically routed to appropriate queue by model size
- **Optimized Concurrency**: Each queue has concurrency tuned for model resource needs
- **Per-Queue Retry Policies**: Large models have more conservative retry settings
- **Resource Isolation**: Small models don't block large models and vice versa
- **Horizontal Scaling**: Each queue can scale independently (small: 0-10, medium: 0-5, large: 0-3)
- **Prefetch Control**: Single task prefetch prevents memory issues
- **Reliability**: Late acknowledgment and worker recycling prevent task loss

## Development

### Running Tests

```bash
# Install test dependencies
pip install -e ".[test]"

# Run tests
pytest

# Run with coverage
pytest --cov=audio_text_backend
```

### Database Migrations

The project includes a helper script that automatically loads environment variables and handles Alembic commands. This script works both inside the Docker container and on the host machine.

**Inside Docker Container (Recommended):**

```bash
# Create new migration
docker exec audio_text_backend-app-1 bash -c "cd /app && ./scripts/alembic-revision.sh 'Add new field'"

# Apply all pending migrations (upgrade to head)
docker exec audio_text_backend-app-1 bash -c "cd /app && ./scripts/alembic-revision.sh upgrade"

# Upgrade one revision forward
docker exec audio_text_backend-app-1 bash -c "cd /app && ./scripts/alembic-revision.sh upgrade +1"

# Downgrade one revision
docker exec audio_text_backend-app-1 bash -c "cd /app && ./scripts/alembic-revision.sh downgrade -1"

# Downgrade to base (removes all migrations)
docker exec audio_text_backend-app-1 bash -c "cd /app && ./scripts/alembic-revision.sh downgrade base"
```

**On Host Machine (Local Development):**

```bash
# Create new migration
./scripts/alembic-revision.sh "Add new field"

# Apply migrations
./scripts/alembic-revision.sh upgrade

# Downgrade one revision
./scripts/alembic-revision.sh downgrade -1
```

**Manual Alembic Commands (Alternative):**

If you need to run Alembic commands manually, ensure environment variables are loaded:

```bash
# Inside container
cd /app/alembic
env $(cat /app/.env | grep -v '^#' | xargs) PYTHONPATH=/app alembic upgrade head

# On host machine (with virtual environment activated)
cd alembic
alembic upgrade head
```

**Common Migration Workflow:**

1. Modify your SQLAlchemy models in `audio_text_backend/model/`
2. Create migration: `./scripts/alembic-revision.sh "Description of changes"`
3. Review generated migration file in `alembic/versions/`
4. Apply migration: `./scripts/alembic-revision.sh upgrade`
5. Commit both model changes and migration file to git

## Deployment

### Google Cloud Platform (Manual Deployment)

Deploy both services or individually with a simple script:

```bash
# Deploy both API and Worker services
./scripts/deploy-cloud.sh -p your-project-id

# Deploy only API service
./scripts/deploy-cloud.sh -p your-project-id -s api

# Deploy to different region
./scripts/deploy-cloud.sh -p your-project-id -r europe-west1
```

**Options:**

- `-p, --project`: GCP project ID (required)
- `-r, --region`: GCP region (default: us-central1)
- `-s, --service`: Deploy `api`, `worker`, or `all` (default: all)

**Default Configuration:**

- **API**: 1GB RAM, 1 CPU, scales 0-10 instances, public access
- **Workers**: 2GB RAM, 2 CPU per worker, private access
  - Small models: min=1, max=10 instances
  - Medium models: min=1, max=5 instances
  - Large models: min=0, max=3 instances (on-demand)
  - Fallback: min=1, max=5 instances

### CI/CD Deployment (Automated)

The project includes a Cloud Build configuration for automated deployments:

```bash
# Trigger deployment via Cloud Build
gcloud builds submit --config ci/deployment.yaml

# Or set up automatic deployments from GitHub
gcloud builds triggers create github \
  --repo-name=audio-text-backend \
  --repo-owner=your-org \
  --branch-pattern="^main$" \
  --build-config=ci/deployment.yaml
```

### Cloudflare Worker Setup (Custom Domain)

To use a custom domain (e.g., `api.voiceia.danobhub.com`) with Cloud Run:

**1. Deploy the Worker:**

- Go to Cloudflare Dashboard → Workers & Pages
- Create Worker named `voiceia-api-proxy`
- Copy code from `cloudflare-worker.js`
- Deploy

**2. Set Environment Variable:**

- Worker Settings → Variables
- Add: `CLOUD_RUN_URL` = `https://audio-api-XXXXX.run.app` (your Cloud Run URL)
- Get URL: `gcloud run services describe audio-api --format='value(status.url)'`

**3. Add Route:**

- Your domain → Workers Routes → Add Route
- Route: `api.voiceia.danobhub.com/*`
- Worker: `voiceia-api-proxy`

**4. Configure DNS:**

- DNS → Records → Add
- Type: `CNAME`, Name: `api.voiceia`, Content: `192.0.2.1`, Proxied: ON

**5. SSL/TLS Settings:**

- SSL/TLS → Overview → Set mode to **Full** (not Full strict)

**Why?** The worker proxies requests to Cloud Run while keeping your custom domain visible and handling SSL/TLS properly.

### Production Considerations

1. **Environment Variables**: Use environment variables instead of config.ini
2. **SSL/TLS**: Add HTTPS termination with reverse proxy
3. **Scaling**: Scale Celery workers based on load
4. **Monitoring**: Add Prometheus metrics, health checks
5. **Security**: Restrict S3 bucket access, use IAM roles
6. **Resource Allocation**: Adjust Cloud Run memory/CPU based on actual usage
7. **Costs**: Worker service runs at min 1 instance (always warm) - consider costs

## Security & Access Control

The application supports multiple layers of security to protect API endpoints and documentation:

### Option 1: Cloudflare Worker Access Control (Recommended)

**✅ Advantages:**

- No backend code changes needed
- Instant updates without redeployment
- Edge-level security (requests blocked before reaching backend)
- Minimal latency impact

**Implementation:** The `cloudflare-worker.js` includes built-in access control:

```javascript
// Blocks public access to /docs, /redoc, /openapi.json
// Validates Origin/Referer headers for API endpoints
// Allows health check endpoints to remain public
```

**Setup:**

1. Deploy updated worker (already includes security)
2. Set `ALLOWED_ORIGINS` environment variable in Cloudflare:
   ```
   ALLOWED_ORIGINS=https://voiceia.danobhub.com,http://localhost:3202
   ```
3. **No backend redeployment needed!**

**What it does:**

- ❌ Blocks `/docs`, `/redoc`, `/openapi.json` from public access
- ✅ Allows `/` health check for monitoring
- ✅ Validates Origin/Referer headers for all API endpoints
- ✅ Only requests from your frontend can access the API

### Option 2: FastAPI Middleware (Backend Layer)

**✅ Advantages:**

- More granular control
- Can integrate with authentication systems
- Logged access attempts

**⚠️ Disadvantages:**

- Requires backend redeployment
- Requests reach backend before being blocked

**Implementation:** Add the middleware to `api/api.py`:

```python
from audio_text_backend.middleware import AccessControlMiddleware

# Add before CORS middleware
app.add_middleware(AccessControlMiddleware)
```

**Features:**

- Blocks API documentation endpoints
- Validates Origin/Referer headers
- Logs unauthorized access attempts
- Returns detailed error messages for debugging

### Option 3: Combined Approach (Most Secure)

Use **both** Cloudflare Worker and FastAPI middleware for defense in depth:

1. **Cloudflare Worker**: Blocks most unauthorized requests at the edge
2. **FastAPI Middleware**: Catches any requests that bypass Cloudflare
3. **CORS**: Already configured to limit allowed origins

**Implementation:**

```python
# In api/api.py, add both middlewares:
from audio_text_backend.middleware import AccessControlMiddleware, RateLimitMiddleware

app.add_middleware(AccessControlMiddleware)
# app.add_middleware(RateLimitMiddleware)  # Optional: Add rate limiting
app.add_middleware(CORSMiddleware, ...)
```

### Security Comparison

| Feature                    | Cloudflare Worker | FastAPI Middleware | Combined |
| -------------------------- | ----------------- | ------------------ | -------- |
| Block /docs publicly       | ✅                | ✅                 | ✅       |
| Validate Origin/Referer    | ✅                | ✅                 | ✅       |
| No backend redeployment    | ✅                | ❌                 | ❌       |
| Edge-level protection      | ✅                | ❌                 | ✅       |
| Detailed logging           | ❌                | ✅                 | ✅       |
| Authentication integration | ❌                | ✅                 | ✅       |
| Defense in depth           | ❌                | ❌                 | ✅       |

### Testing Access Control

```bash
# Test 1: Try accessing /docs directly (should be blocked)
curl https://api.voiceia.danobhub.com/docs
# Expected: 403 Forbidden

# Test 2: Try API without Origin header (should be blocked)
curl https://api.voiceia.danobhub.com/api/v1/job/read
# Expected: 403 Forbidden

# Test 3: Health check should work (public)
curl https://api.voiceia.danobhub.com/
# Expected: 200 OK

# Test 4: API with valid Origin (should work)
curl -H "Origin: https://voiceia.danobhub.com" https://api.voiceia.danobhub.com/api/v1/job/read
# Expected: 200 OK
```

### Recommended Configuration

**For Production:** Use **Option 3** (Combined Approach)

1. **Deploy Cloudflare Worker** with updated code (already done)
2. **Add middleware** to backend:
   ```python
   app.add_middleware(AccessControlMiddleware)
   ```
3. **Set environment variables** in Cloudflare:
   ```
   ALLOWED_ORIGINS=https://voiceia.danobhub.com
   ```
4. **Redeploy backend** with middleware enabled

**For Development:** Use **Option 1** (Cloudflare Worker only)

- No code changes needed
- Easy to update allowed origins
- Good enough for most use cases

### Docker Swarm/Kubernetes

The application is designed for container orchestration with:

- Stateless API servers (horizontal scaling)
- Shared Redis/PostgreSQL instances
- S3 for persistent storage
- Multi-stage Docker builds optimized for size (API: ~250MB, Worker: ~1.8GB with faster-whisper)

## Performance & Benchmarks

### faster-whisper vs openai-whisper

| Metric                                     | openai-whisper | faster-whisper | Improvement     |
| ------------------------------------------ | -------------- | -------------- | --------------- |
| Processing Speed (2min audio, base model)  | ~100s          | ~20s           | **80% faster**  |
| Memory Usage                               | ~4GB           | ~1.5GB         | **63% less**    |
| Docker Image Size                          | ~3.5GB         | ~1.8GB         | **49% smaller** |
| Cloud Run Cost (1000 transcriptions/month) | ~$120          | ~$35           | **71% cheaper** |

### Model Performance (faster-whisper, CPU, int8)

| Model    | Speed (per min of audio) | Memory | Quality   | Use Case                |
| -------- | ------------------------ | ------ | --------- | ----------------------- |
| tiny     | ~5s                      | ~1GB   | Basic     | Quick drafts            |
| base     | ~10s                     | ~1.5GB | Very Good | **Recommended default** |
| small    | ~30s                     | ~2GB   | Excellent | High accuracy needs     |
| medium   | ~60s                     | ~5GB   | Superior  | Professional quality    |
| large-v3 | ~120s                    | ~10GB  | Best      | Maximum accuracy        |

### New Features with faster-whisper

- ✨ **Word-level timestamps** - Precise timing for each word (±0.1s accuracy)
- 🌍 **Language detection** - Automatic detection with confidence scores (98%+ accuracy)
- 🎤 **VAD filtering** - Voice Activity Detection removes silence/noise
- 📊 **Segment metadata** - Quality scores and confidence per segment
- ⚡ **int8 quantization** - 75% faster with <1% accuracy loss

## Troubleshooting

### Common Issues

1. **Connection Refused Errors**

   ```bash
   # Check if services are running
   docker-compose ps

   # Restart services
   docker-compose restart
   ```

2. **Database Migration Errors**

   ```bash
   # Reset database (WARNING: destroys data)
   docker-compose down -v
   docker-compose up -d
   ```

3. **Celery Worker Not Processing**

   ```bash
   # Check worker logs (DEFAULT single worker)
   docker-compose --profile default logs -f celery-worker

   # OR check worker logs (MULTI-QUEUE workers)
   docker-compose --profile multi-queue logs -f celery-worker-small
   docker-compose --profile multi-queue logs -f celery-worker-medium
   docker-compose --profile multi-queue logs -f celery-worker-large

   # Inspect worker configuration
   celery -A audio_text_backend.celery.app inspect conf

   # Check queue status
   celery -A audio_text_backend.celery.app inspect active_queues

   # Restart workers (default)
   docker-compose --profile default restart celery-worker

   # OR restart workers (multi-queue)
   docker-compose --profile multi-queue restart celery-worker-small celery-worker-medium celery-worker-large
   ```

4. **WebSocket Connection Issues**

   ```bash
   # Check Redis pub/sub channel
   docker-compose exec redis redis-cli
   > PSUBSCRIBE job_updates

   # Check WebSocket connection tracking
   docker-compose logs app | grep "WebSocket"

   # Verify Redis connectivity
   docker-compose exec redis redis-cli ping
   ```

5. **S3 Permission Errors**
   - Verify AWS credentials in config.ini
   - Check bucket permissions and region

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes with tests
4. Submit a pull request

### Code Style

- Follow PEP 8
- Use type hints
- Document functions and classes
- Write tests for new features

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
