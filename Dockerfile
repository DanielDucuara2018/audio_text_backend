FROM python:3.12-slim-trixie

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir --upgrade pip
RUN --mount=type=cache,target=/root/.cache pip install --editable .

RUN apt update -y && apt install ffmpeg libmagic1 -y

EXPOSE 3203

CMD ["uvicorn", "audio_text_backend.api.api:app", "--host", "0.0.0.0", "--port", "3203", "--log-level", "debug", "--reload"]
