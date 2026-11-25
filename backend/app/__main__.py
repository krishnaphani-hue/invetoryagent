"""Start the server with the settings from .env:  python -m app   (run from the backend folder)

Same command on Windows, Linux, in Docker or under a service manager. HOST and APP_PORT decide where it
listens. When nginx runs on the same machine in front of it, uvicorn trusts nginx's X-Forwarded-* headers
(proxy headers are on by default and trusted from 127.0.0.1; set FORWARDED_ALLOW_IPS if the proxy is elsewhere).
"""
import uvicorn

from app.config import settings

if __name__ == "__main__":
    print(f"Asset Inventory Server on http://{settings.host}:{settings.app_port}  (Ctrl+C to stop)")
    if settings.host in ("127.0.0.1", "localhost"):
        print("Local mode: only this computer can connect. Set HOST=0.0.0.0 in .env to accept other machines.")
    if not settings.ingest_api_key:
        print("INGEST_API_KEY is empty: agents can POST without a key.")
    uvicorn.run("app.main:app", host=settings.host, port=settings.app_port)
