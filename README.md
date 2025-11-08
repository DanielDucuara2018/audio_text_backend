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
   API -- "3.3 Job queued for celery" --> Redis[(Redis Cache/Queue<br/>:6379)]

   Redis -- "4.1 Gives the job to worker" --> Worker[Celery Worker<br/>audio_processing queue]
   Worker -- "4.2 Download file" --> S3
   Worker -- "4.3 Run transcription" --> Whisper[faster-whisper Model<br/>CTranslate2]
   Worker -- "4.4 Publish update messages to job_updates channel" --> Redis

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
4. **Queue Processing**: Job queued in Redis for Celery worker
5. **Transcription**: Worker downloads file, processes with Whisper
6. **Real-time Updates**: Progress updates sent via Redis pub/sub to WebSocket
7. **Completion**: Results stored in database, client notified

## Features

- **High Performance**: 75-80% faster transcription with faster-whisper (CTranslate2)
- **Cost Efficient**: 60-70% reduction in compute costs with int8 quantization
- **Async Processing**: Non-blocking audio processing using Celery with advanced configuration
- **S3 Storage**: Scalable file storage with S3-compatible services
- **Real-time Updates**: WebSocket support for live progress updates with singleton pattern
- **Job Management**: Track processing status and history
- **Multiple Formats**: Support for MP3, WAV, M4A, FLAC, OGG, AAC
- **Advanced Features**: Word-level timestamps, language detection, VAD filtering
- **Microservices Architecture**: Containerized services with Docker
- **Database Migrations**: Alembic for schema management
- **Resource Management**: Context managers with reference counting for safe cleanup
- **Configuration Management**: Type-safe dataclass-based configuration system

## Project Structure

```
audio_text_backend/
├── README.md                           # This documentation file
├── config.ini                         # Application configuration
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
    ├── config.py                      # Configuration loader
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

The application uses `config.ini` for configuration management:

### Database Configuration

```ini
[database]
database = audiotext              # Database name
host = postgres                   # Database hostname (Docker service)
password = postgres               # Database password
port = 5432                      # Database port
user = postgres                  # Database username
ref_table = transcription_job    # Reference table for migrations
```

### AWS S3 Configuration

```ini
[aws]
bucket_name = bucket_name         # S3 bucket name
access_key = YOUR_ACCESS_KEY      # AWS access key
secret_key = YOUR_SECRET_KEY      # AWS secret key
region = eu-west-3               # AWS region
```

### Celery/Redis Configuration

```ini
[redis]
host = redis                          # Redis hostname (Docker service)
port = 6379                          # Redis port
pub_sub_channel = job_updates        # Redis pub/sub channel for WebSocket updates

[celery]
queue_name = audio_processing        # Celery queue name
routing_key = audio_processing       # Task routing key
serialization_format = json          # Task serialization format
timezone = UTC                       # Timezone for task scheduling
enable_utc = 1                      # Enable UTC timestamps
task_track_started = 1              # Track task start events
task_acks_late = 1                  # Acknowledge tasks after completion
worker_prefetch_multiplier = 1      # Tasks prefetched per worker process
worker_disable_rate_limits = 1      # Disable rate limiting
worker_max_tasks_per_child = 10     # Max tasks per worker before restart
task_time_limit = 600               # Hard task time limit (10 min) - reduced with faster-whisper
task_soft_time_limit = 480          # Soft task time limit (8 min) - reduced with faster-whisper
task_default_retry_delay = 60       # Default retry delay (seconds)
task_max_retries = 3                # Maximum retry attempts
worker_autoscaler = celery.worker.autoscale:Autoscaler
retry_policy_max_retries = 3        # Retry policy max attempts
retry_policy_interval_start = 0     # Retry policy start interval
retry_policy_interval_step = 60     # Retry policy step interval
retry_policy_interval_max = 300     # Retry policy max interval
```

### File Processing Configuration

```ini
[file]
max_size_mb = 10                             # Maximum file size in MB
allowed_audio_extensions = mp3,wav,flac,mp4,m4a,aac,ogg
```

### Whisper Model Configuration (faster-whisper)

```ini
[whisper]
device = cpu                                 # Device: cpu or cuda
compute_type = int8                          # Quantization: int8 (fast), float16 (GPU), float32
cpu_threads = 4                              # CPU threads: 0=auto, or specific number
beam_size = 5                                # Beam search: 1=fast, 5=balanced, 10=best
word_timestamps = true                       # Enable word-level timestamps
vad_filter = true                            # Enable Voice Activity Detection
vad_min_silence_duration_ms = 500            # Minimum silence duration to remove (ms)
```

**Performance**: With int8 quantization on CPU, expect **75-80% faster** processing compared to openai-whisper.

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
cp config.ini.example config.ini
# Edit config.ini with your AWS credentials and settings
```

### 2. Docker Setup (Recommended)

#### Fast Development Start (Optimized)

```bash
# Quick start with optimized build performance
./scripts/start-dev.sh
```

This enables Docker BuildKit for faster builds and provides:

- ✅ **60-85% faster builds** through advanced layer caching
- ✅ **Parallel processing** with BuildKit
- ✅ **Smart dependency management** (rebuilds only when needed)
- ✅ **Optimized volume mounting** for development

#### Standard Docker Setup

```bash
# Start all services (traditional method)
docker-compose up -d --build

# View logs
docker-compose logs -f

# Check service status
docker-compose ps
```

Both methods start:

- **FastAPI app** on `localhost:3203`
- **PostgreSQL** on `localhost:5432`
- **Redis** on `localhost:6379`
- **Celery worker** for background processing

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

### 2. Celery Worker (`action/tasks.py`)

- **Purpose**: Asynchronous audio processing with comprehensive configuration
- **Queue**: `audio_processing` with advanced routing and retry policies
- **Tasks**: Download from S3, Whisper transcription, cleanup
- **Models**: Supports all Whisper models (tiny to large)
- **Configuration**: Auto-scaling, time limits, retry mechanisms, task tracking

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

- **Purpose**: Centralized configuration using dataclasses
- **Features**:
  - Type-safe configuration loading
  - Environment-specific settings
  - Comprehensive Celery configuration
  - Database, Redis, AWS, and file handling settings

### 6. WebSocket Manager (`action/job.py`)

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

### Enhanced Celery Features

The Celery configuration includes advanced features:

- **Auto-scaling**: Dynamic worker scaling based on queue size
- **Task Time Limits**: Soft (25min) and hard (30min) limits prevent runaway tasks
- **Retry Policies**: Exponential backoff with configurable intervals
- **Prefetch Control**: Single task prefetch prevents memory issues
- **Task Routing**: Dedicated `audio_processing` queue with custom routing
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

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# View migration history
alembic history
```

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

- API: 1GB RAM, 1 CPU, scales 0-10 instances, public access
- Worker: 4GB RAM, 2 CPU, scales 1-5 instances, private access

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
   # Check worker logs
   docker-compose logs celery-worker

   # Inspect worker configuration
   celery -A audio_text_backend.celery.app inspect conf

   # Check queue status
   celery -A audio_text_backend.celery.app inspect active_queues

   # Restart worker
   docker-compose restart celery-worker
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
