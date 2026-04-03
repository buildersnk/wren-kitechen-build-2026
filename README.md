# wren-kitechen-build-2026

This project uses `pip3` with `python3.13`.

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
export GITHUB_TOKEN=<fromGithub>
```

## Test Connection

```bash
python3.13 upload_kitchen_items.py --test-connection
```

## Run

```bash
python3.13 upload_kitchen_items.py
```
