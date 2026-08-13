"""Entry point: `coherra-mcp` console script + `python -m coherra`."""
from .server import run_stdio


def main() -> None:
    run_stdio()


if __name__ == "__main__":
    main()
