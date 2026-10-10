"""启动游戏权威后端。"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys


def main() -> None:
    parser = ArgumentParser(description="浊流之上后端")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent / "src"
    sys.path.insert(0, str(src_dir))

    import uvicorn

    uvicorn.run(
        "serious_game_backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(src_dir),
    )


if __name__ == "__main__":
    main()
