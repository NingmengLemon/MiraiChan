install:
    uv sync --all-packages --all-groups

upgrade:
    uv upgrade --all-packages --all-groups -U

dev:
    uv run mb dev miracle_entrance.py -w packages

run:
    uv run mb run miracle_entrance.py
