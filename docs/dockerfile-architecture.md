# Dockerfile Architecture

This document explains the multi-stage Dockerfile structure for the Audio Text Backend project.

## Overview

The project uses a **single unified Dockerfile** with multiple build stages to support:

- **Development**: Hot reload environment for local development
- **Production API**: Lightweight container without ML libraries
- **Production Worker**: Full container with Whisper and ML processing capabilities

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Multi-Stage Dockerfile                   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ BASE STAGE (python:3.12-slim-trixie)                        │
│ • System dependencies (libmagic1)                           │
│ • Working directory setup                                   │
│ • Dependency file copying (pyproject.toml, README.md)       │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
        ▼                             ▼
┌───────────────┐           ┌──────────────────────┐
│ DEPENDENCIES  │           │ WORKER (production)  │
│  • pip install│           │ • ffmpeg installed   │
│  • Base deps  │           │ • ML dependencies    │
│    (no Whisper│           │ • Whisper models     │
│     no ML)    │           │ • Celery worker CMD  │
└───────┬───────┘           └──────────────────────┘
        │
        ├─────────────┬─────────────┐
        ▼             ▼             ▼
    ┌───────┐   ┌───────────┐ ┌──────────────┐
    │  DEV  │   │    API    │ │   (unused)   │
    │       │   │(production)│ │              │
    │• Hot  │   │• Lightweight│ │              │
    │ reload│   │• No ML libs│ │              │
    │• Full │   │• Multi-     │ │              │
    │ source│   │  worker     │ │              │
    └───────┘   └───────────┘ └──────────────┘
```

## Build Stages

### 1. `base` Stage

**Purpose**: Common foundation for all variants

**Includes**:

- Python 3.12 slim (Debian trixie)
- System dependency: `libmagic1` (for file type detection)
- Dependency files: `pyproject.toml`, `README.md`

**Size**: ~150MB

**When changes**: Rarely (only when Python version or base system deps change)

```dockerfile
FROM python:3.12-slim-trixie AS base
WORKDIR /app
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends libmagic1 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
```

### 2. `dependencies` Stage

**Purpose**: Install Python dependencies (except ML libraries)

**Includes**:

- Upgraded pip
- FastAPI, Uvicorn, SQLAlchemy, Celery, Boto3, etc.
- **Excludes**: openai-whisper, setuptools-rust (moved to `[worker]` optional dependencies)

**Size**: ~200MB additional

**When changes**: When pyproject.toml core dependencies change

```dockerfile
FROM base AS dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --editable .  # Installs only core dependencies
```

**Key optimization**:

- Uses BuildKit cache mounts to persist pip cache between builds
- Only installs core dependencies (API, Celery, Database, Storage)
- ML libraries excluded - installed separately in worker stage

### 3. `dev` Stage (Development)

**Purpose**: Local development with hot reload

**Includes**:

- All dependencies from `dependencies` stage
- Full source code (mounted as volume in docker-compose)
- Uvicorn with `--reload` flag

**Size**: ~250MB + source code

**Usage**:

```bash
# docker-compose.yml
docker-compose up -d app celery-worker
```

**Features**:

- ✅ Hot reload on code changes
- ✅ Volume mounts for source code
- ✅ All dependencies installed (including Whisper for local testing)
- ✅ Fast rebuild (only source layer changes)

```dockerfile
FROM dependencies AS dev
COPY . .
EXPOSE 3203
CMD ["uvicorn", "audio_text_backend.api.api:app", \
     "--host", "0.0.0.0", "--port", "3203", "--reload"]
```

### 4. `api` Stage (Production API)

**Purpose**: Lightweight production API server

**Includes**:

- All dependencies from `dependencies` stage
- Only API-related code (`audio_text_backend/api/`, `audio_text_backend/schema/`)
- Alembic migrations
- Multi-worker Uvicorn (4 workers)
- Non-root user (security)

**Excludes**:

- ❌ Whisper models (saves ~500MB)
- ❌ ML processing libraries
- ❌ Celery worker code (included but not used)

**Size**: ~250MB (50% smaller than worker)

**Usage**:

```bash
# Build API image
docker build --target api -t audio-api .

# Cloud Build
gcloud builds submit --config=ci/deployment.yaml
```

**Optimizations**:

- Lightweight (no ML dependencies means faster cold starts)
- Multiple workers for better throughput
- Runs as non-root user (`appuser`)
- Only copies necessary files

```dockerfile
FROM dependencies AS api
COPY audio_text_backend/ ./audio_text_backend/
COPY alembic/ ./alembic/
COPY config.ini ./
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 3203
CMD ["uvicorn", "audio_text_backend.api.api:app", \
     "--host", "0.0.0.0", "--port", "3203", "--workers", "4"]
```

### 5. `worker` Stage (Production Celery Worker)

**Purpose**: Heavy ML processing with Whisper

**Includes**:

- All dependencies (FastAPI, Celery, **Whisper**, ML libraries)
- System dependency: `ffmpeg` (for audio processing)
- Pre-downloaded Whisper models (`tiny`, `base`, `small`)
- Celery worker configuration
- Non-root user (security)

**Size**: ~3.5GB (includes Whisper models)

**Usage**:

```bash
# Build Worker image
docker build --target worker -t audio-worker .

# Cloud Build (automatic in deployment.yaml)
gcloud builds submit --config=ci/deployment.yaml
```

**Key features**:

- ✅ Pre-downloads Whisper models during build (not at runtime)
- ✅ ffmpeg installed for audio format conversion
- ✅ Configured for single concurrent task (avoid memory issues)
- ✅ Auto-restarts after 5 tasks (prevent memory leaks)
- ✅ Runs as non-root user

```dockerfile
FROM base AS worker
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --editable .
COPY audio_text_backend/ ./audio_text_backend/
COPY config.ini ./
RUN python -c "import whisper; \
    whisper.load_model('tiny'); \
    whisper.load_model('base'); \
    whisper.load_model('small')"
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
CMD ["celery", "-A", "audio_text_backend.celery.app", "worker", ...]
```

## Build Commands

### Local Development

```bash
# Build dev stage (default)
docker-compose build

# Or explicitly specify dev target
docker build --target dev -t audio-backend-dev .

# Start dev environment
docker-compose up -d
```

### Production Builds

```bash
# Build API image only (lightweight)
docker build --target api -t audio-api:latest .

# Build Worker image only (with ML)
docker build --target worker -t audio-worker:latest .

# Build both
docker build --target api -t audio-api:latest . && \
docker build --target worker -t audio-worker:latest .
```

### Cloud Build (GCP)

```bash
# Deploy to Cloud Run (builds both images)
gcloud builds submit --config=ci/deployment.yaml

# With custom region
gcloud builds submit \
  --config=ci/deployment.yaml \
  --substitutions=_REGION=europe-west1
```

## Layer Caching Strategy

### Build Order (Least to Most Frequently Changed)

1. **Base image** (`python:3.12-slim-trixie`) - Never changes
2. **System packages** (`libmagic1`, `ffmpeg`) - Rarely changes
3. **Dependency files** (`pyproject.toml`) - Sometimes changes
4. **Python packages** (`pip install`) - Sometimes changes
5. **Whisper models** (`whisper.load_model()`) - Rarely changes
6. **Source code** (`COPY . .`) - Frequently changes

### Cache Optimization

```dockerfile
# ✅ Good: Dependencies cached separately
COPY pyproject.toml README.md ./
RUN pip install --editable .
COPY . .  # Only this layer rebuilds on code changes

# ❌ Bad: Everything rebuilds on code changes
COPY . .
RUN pip install --editable .
```

### BuildKit Cache Mounts

```dockerfile
# Persist pip cache between builds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip
```

**Benefit**:

- First build: Downloads packages (~2-3 minutes)
- Subsequent builds: Uses cache (~10-20 seconds)

## Size Comparison

| Image            | Size   | Includes                  | Use Case               |
| ---------------- | ------ | ------------------------- | ---------------------- |
| **base**         | ~150MB | Python + libmagic         | Foundation             |
| **dependencies** | ~250MB | + FastAPI, Celery, etc.   | Intermediate           |
| **dev**          | ~300MB | + Source code             | Local development      |
| **api**          | ~250MB | + API code only           | Production API servers |
| **worker**       | ~3.5GB | + Whisper models + ffmpeg | Production ML workers  |

**Why worker is larger**:

- Whisper models: ~1.5GB (tiny: 75MB, base: 150MB, small: 500MB, medium: 1.5GB)
- ML dependencies: ~1GB (torch, numpy, scipy, etc.)
- ffmpeg: ~100MB

## Docker Compose Usage

### Development Configuration

```yaml
services:
  app:
    build:
      context: ./
      dockerfile: ./Dockerfile
      target: dev # ← Use dev stage
    volumes:
      - ./audio_text_backend:/app/audio_text_backend # Hot reload
    command: ["uvicorn", "...", "--reload"]

  celery-worker:
    build:
      context: ./
      dockerfile: ./Dockerfile
      target: dev # ← Use dev stage (includes Whisper for testing)
    volumes:
      - ./audio_text_backend:/app/audio_text_backend
    command: ["celery", "-A", "audio_text_backend.celery.app", "worker", ...]
```

## Cloud Deployment (GCP Cloud Run)

### deployment.yaml Configuration

```yaml
steps:
  # Build API (lightweight, fast cold start)
  - name: "gcr.io/cloud-builders/docker"
    args:
      ["build", "--target", "api", "-t", "gcr.io/$PROJECT_ID/audio-api", "."]

  # Build Worker (heavy ML, pre-loaded models)
  - name: "gcr.io/cloud-builders/docker"
    args:
      [
        "build",
        "--target",
        "worker",
        "-t",
        "gcr.io/$PROJECT_ID/audio-worker",
        ".",
      ]

  # Deploy API (scales to 0, fast startup)
  - name: "gcr.io/cloud-builders/gcloud"
    args: ["run", "deploy", "audio-api", "--min-instances", "0", ...]

  # Deploy Worker (min 1 instance, always warm)
  - name: "gcr.io/cloud-builders/gcloud"
    args: ["run", "deploy", "audio-worker", "--min-instances", "1", ...]
```

### Why Separate Images?

1. **Cost Optimization**:

   - API can scale to 0 (no requests = no cost)
   - Worker stays warm (min 1 instance) for faster job processing

2. **Performance**:

   - API: Lightweight (~250MB) → Fast cold starts (~2-3 seconds)
   - Worker: Heavy (~3.5GB) → Pre-loaded models, no download delay

3. **Resource Allocation**:
   - API: 1 CPU, 1GB RAM (handles HTTP requests)
   - Worker: 2 CPU, 4GB RAM (handles ML processing)

## Troubleshooting

### Build Issues

**Problem**: "libmagic1 not found"

```bash
# Solution: Update apt cache
RUN apt-get update -y && apt-get install -y libmagic1
```

**Problem**: "Whisper models downloading at runtime"

```bash
# Solution: Pre-download in worker stage
RUN python -c "import whisper; whisper.load_model('base')"
```

**Problem**: "Slow pip installs"

```bash
# Solution: Use BuildKit cache mounts
RUN --mount=type=cache,target=/root/.cache/pip pip install ...
```

### Runtime Issues

**Problem**: "Permission denied" errors

```bash
# Solution: Ensure chown after USER directive
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
```

**Problem**: "Out of memory in worker"

```bash
# Solution: Limit concurrency and task count
CMD ["celery", "...", "--concurrency=1", "--max-tasks-per-child=5"]
```

## Migration from Old Structure

### Old Structure (3 Dockerfiles)

```
Dockerfile         → Development + API
Dockerfile.api     → Production API only
Dockerfile.worker  → Production Worker only
```

### New Structure (1 Dockerfile)

```
Dockerfile → Multi-stage with targets:
  ├─ dev     (development)
  ├─ api     (production API)
  └─ worker  (production worker)
```

### Changes Required

1. **docker-compose.yml**: Add `target: dev`

   ```yaml
   build:
     dockerfile: ./Dockerfile
     target: dev # ← Add this
   ```

2. **ci/deployment.yaml**: Update build commands

   ```yaml
   args: ["build", "--target", "api", ...] # ← Add --target
   ```

3. **Remove old files**:
   ```bash
   rm Dockerfile.api Dockerfile.worker
   # Keep backups if needed: *.old
   ```

## Best Practices

1. **Always use BuildKit**: `DOCKER_BUILDKIT=1 docker build ...`
2. **Order layers by change frequency**: System deps → Python deps → Source code
3. **Use cache mounts**: Speed up pip installs
4. **Pre-download models**: Don't download at container startup
5. **Run as non-root**: Better security in production
6. **Multi-worker API**: Better throughput (4 workers)
7. **Single-worker Celery**: Avoid memory issues with ML models

## References

- [Docker Multi-stage Builds](https://docs.docker.com/build/building/multi-stage/)
- [BuildKit Cache Mounts](https://docs.docker.com/build/cache/optimize/)
- [Cloud Run Best Practices](https://cloud.google.com/run/docs/best-practices)
- [Whisper Model Sizes](https://github.com/openai/whisper#available-models-and-languages)

---

**Last Updated**: October 24, 2025
