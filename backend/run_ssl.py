import pathlib
import sys
import uvicorn

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))
from backend.app.main import app

if __name__ == "__main__":
    cert_dir = ROOT / "certs"
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_certfile=str(cert_dir / "server.cert.pem"),
        ssl_keyfile=str(cert_dir / "server.key.pem"),
    )
