install:
    uv sync --all-packages --all-groups

upgrade:
    uv sync --all-packages --all-groups -U

build-check:
    uv run python tools/check_builds.py

dev:
    uv run mb dev miracle_entrance.py -w packages

run:
    uv run mb run miracle_entrance.py
