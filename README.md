# audio to text app

Extract the text from an audio file using whisper lib

## pre-commit

```bash
pip install --user pre-commit
pre-commit install
pre-commit run --all-files
```

## pytho venv

```bash
python3.9 -m venv venv
```

## generate docker containers

```bash
docker-compose up -d --build
```

## forwarding ports

Create a host name for report-calculation application:

```bash
sudo nano /etc/hosts
169.254.9.2 audio-text
```

Forward port in host machine:

```bash
ssh -L 127.0.0.1:3203:audio-text:3203 username@ip_address
```
