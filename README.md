# Audio to Text Backend

This repository contains the backend component of an Audio-to-Text application. It provides an API service that processes audio files and returns their transcriptions using OpenAI's Whisper library.

## Features

* Accepts audio file uploads via API endpoints
* Processes audio files to extract text using Whisper
* Provides transcribed text responses
* Dockerized for easy deployment

## Technologies Used

* Python 3.9
* Whisper (OpenAI)
* Docker & Docker Compose
* Supervisor (for process management)

## Getting Started

### Prerequisites

* Python 3.9
* Docker and Docker Compose
* `pre-commit` installed globally (optional, for code quality checks)

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/DanielDucuara2018/audio_text_backend.git
   cd audio_text_backend
   ```
   
2. Set up a virtual environment (optional):

   ```bash
   python3.9 -m venv venv
   source venv/bin/activate
   ```
   
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Set up pre-commit hooks (optional):

   ```bash
   pip install --user pre-commit
   pre-commit install
   pre-commit run --all-files
   ```

### Running the Application

You can run the application using Docker Compose:

```bash
docker-compose up -d --build
```

This will build and start the backend service in detached mode.

### Port Forwarding (Optional)

If you need to forward ports from a remote host:

1. Edit your `/etc/hosts` file:

   ```bash
   sudo nano /etc/hosts
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

* `audio_text_backend/` - Main application code
* `Dockerfile` - Docker configuration
* `docker-compose.yml` - Docker Compose setup
* `supervisord.conf` - Supervisor configuration
* `pyproject.toml` and `setup.py` - Python project configurations

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request with your changes.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
