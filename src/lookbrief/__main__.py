"""`uv run lookbrief` -> serve the app (Replay works with no configuration)."""

import os

import uvicorn


def main() -> None:
    uvicorn.run("lookbrief.app:create_app", factory=True, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8731")), proxy_headers=True,
                access_log=False)  # brief tokens travel in URLs: keep them out of logs


if __name__ == "__main__":
    main()
