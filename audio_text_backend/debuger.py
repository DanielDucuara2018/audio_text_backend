import uvicorn

from audio_text_backend.api.api import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        # ssl_certfile="../localhost.crt",
        # ssl_keyfile="../localhost.key",
    )
