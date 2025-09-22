# Audio Text Backend

A scalable FastAPI backend service for converting audio files to text using OpenAI Whisper with asynchronous processing, S3 storage, and real-time WebSocket updates.

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
   Worker -- "4.3 Run transcription" --> Whisper[OpenAI Whisper Model]
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

- **Async Processing**: Non-blocking audio processing using Celery
- **S3 Storage**: Scalable file storage with S3-compatible services
- **Real-time Updates**: WebSocket support for live progress updates
- **Job Management**: Track processing status and history
- **Multiple Formats**: Support for MP3, WAV, M4A, FLAC, OGG, AAC
- **Microservices Architecture**: Containerized services with Docker
- **Database Migrations**: Alembic for schema management

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
    │   ├── __init__.py
    │   ├── audio.py                   # Audio file handling & S3 operations
    │   ├── job.py                     # Job management & WebSocket
    │   └── tasks.py                   # Celery task definitions
    ├── celery/                        # Celery configuration
    │   └── app.py                     # Celery application setup
    └── api/                           # FastAPI routers
        ├── __init__.py
        ├── api.py                     # Main FastAPI application
        └── routers/
            ├── audio.py               # Audio upload endpoints
            └── job.py                 # Job status endpoints
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
[celery]
redis_url = redis://redis:6379/0
celery_broker_url = redis://redis:6379/0
celery_result_backend = redis://redis:6379/0
```

### File Processing Configuration

```ini
[file]
max_size_mb = 10                             # Maximum file size in MB
allowed_audio_extensions = mp3,wav,flac,mp4,m4a,aac,ogg
whisper_model = base                         # Whisper model (tiny, base, small, medium, large)
```

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

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Check service status
docker-compose ps
```

This starts:

- **FastAPI app** on `localhost:3203`
- **PostgreSQL** on `localhost:5432`
- **Redis** on `localhost:6379`
- **Celery worker** for background processing

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

## Architecture Components

### 1. FastAPI Application (`api/api.py`)

- **Purpose**: REST API server and WebSocket handler
- **Port**: 3203
- **Features**: CORS middleware, automatic OpenAPI documentation
- **Dependencies**: PostgreSQL, Redis

### 2. Celery Worker (`action/tasks.py`)

- **Purpose**: Asynchronous audio processing
- **Queue**: `audio_processing`
- **Tasks**: Download from S3, Whisper transcription, cleanup
- **Models**: Supports all Whisper models (tiny to large)

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
  - Queue: `audio_processing`
  - Pub/Sub: `job_updates` channel
  - Results: Celery task results

### 5. AWS S3 Storage

- **Purpose**: Audio file storage with presigned URLs
- **Features**: Automatic bucket creation, file cleanup
- **Security**: Temporary URLs for secure uploads

### 6. WebSocket Manager (`action/job.py`)

- **Purpose**: Real-time progress updates
- **Transport**: Redis pub/sub
- **Features**: Connection management, automatic cleanup

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

# Flower monitoring (if enabled)
# Visit http://localhost:5555
```

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

### Production Considerations

1. **Environment Variables**: Use environment variables instead of config.ini
2. **SSL/TLS**: Add HTTPS termination with reverse proxy
3. **Scaling**: Scale Celery workers based on load
4. **Monitoring**: Add Prometheus metrics, health checks
5. **Security**: Restrict S3 bucket access, use IAM roles

### Docker Swarm/Kubernetes

The application is designed for container orchestration with:

- Stateless API servers (horizontal scaling)
- Shared Redis/PostgreSQL instances
- S3 for persistent storage

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

   # Restart worker
   docker-compose restart celery-worker
   ```

4. **S3 Permission Errors**
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
