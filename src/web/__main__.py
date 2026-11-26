"""Start the Invesk browser API."""

import os

import uvicorn

DEFAULT_WEB_PORT = 8001


def main() -> None:
    host = os.environ.get("INVESK_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("INVESK_WEB_PORT", str(DEFAULT_WEB_PORT)))
    uvicorn.run("src.web.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
