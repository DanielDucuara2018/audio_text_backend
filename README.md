# Audio Text Backend

A FastAPI backend service for converting audio files to text using OpenAI Whisper.

## Features

- **Async Processing**: Non-blocking audio processing using Celery
- **S3 Storage**: Scalable file storage with S3-compatible services
- **Real-time Updates**: WebSocket support for live progress updates
- **Job Management**: Track processing status and history
- **Multiple Formats**: Support for MP3, WAV, M4A, FLAC, OGG

## Quick Start

1. **Create a virtual environment**:

   ```bash
   python3 -m venv venv
   ```

2. **Install dependencies**:

   ```bash
   pip install -e .
   # or for development
   pip install -e ".[dev,test]"
   ```

3. **Start services** (using Docker):

   ```bash
   docker-compose up -d
   ```

4. **Set environment variables**:

   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Start the API server**:

   ```bash
   uvicorn app.main:app --reload
   ```

6. **Start Celery worker**:
   ```bash
   celery -A app.celery_app worker --loglevel=info -Q audio_processing
   ```

## API Endpoints

- `POST /upload` - Upload audio file for transcription
- `GET /status/{job_id}` - Get job status and results
- `GET /jobs` - List recent jobs
- `WS /ws/{job_id}` - WebSocket for real-time updates
- `GET /health` - Health check

## Usage Example

```python
import requests

# Upload file
with open("audio.mp3", "rb") as f:
    response = requests.post(
        "http://localhost:8000/upload",
        files={"file": f}
    )
    job_id = response.json()["job_id"]

# Check status
status = requests.get(f"http://localhost:8000/status/{job_id}")
print(status.json())
```

## Architecture Benefits

1. **Scalable**: S3 storage and Redis queues handle high load
2. **Non-blocking**: FastAPI remains responsive during processing
3. **Reliable**: Job persistence and error handling
4. **Real-time**: WebSocket updates for better UX
5. **Cloud-ready**: Easily deployable to cloud platforms
   sudo nano /etc/hosts

   ```

   ```

Add the following line:

```
169.254.9.2 audio-text
```

2. Set up SSH port forwarding:

   ```bash
   ssh -L 127.0.0.1:3203:audio-text:3203 username@ip_address
   ```

## Project Structure

- `audio_text_backend/` - Main application code
- `Dockerfile` - Docker configuration
- `docker-compose.yml` - Docker Compose setup
- `supervisord.conf` - Supervisor configuration
- `pyproject.toml` and `setup.py` - Python project configurations

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request with your changes.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
