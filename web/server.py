#!/usr/bin/env python3
from __future__ import annotations

import os

import uvicorn

from jobradar_app.main import create_app


def main() -> None:
    host = os.environ.get("JOBRADAR_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("JOBRADAR_BIND_PORT", "8765"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
