# Kobo Highlight Obsidian Sync

A Python script that syncs highlights from a Kobo eReader to an Obsidian vault.
It can run as a one-shot command or as a daemon that watches for the device to mount and syncs automatically.

## What it does

When your Kobo is connected, the script reads highlights from the device's SQLite database and writes them into your Obsidian vault:

- **Book notes** (`books/<title>.md`) — each highlight is appended as a blockquote entry:
  ```
  - 2024-01-15
  	> The highlighted passage goes here.
  ```

- **Daily notes** (`journal/<YYYY-MM-DD>.md`) — a reading task entry is added once per book per day:
  ```
  - [x] #reading [[Book Title]]  ✅ 2024-01-15
  ```

The script tracks the timestamp of the last synced highlight in `~/.local/share/kobo-highlight-obsidian-sync.json` so that subsequent runs only process new highlights.

## Requirements

- Python 3
- [`notifykit`](https://pypi.org/project/notifykit/) (see `requirements.txt`)

Install dependencies into a virtualenv:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Configuration

The script is configured via environment variables:

| Variable | Description | Example |
|---|---|---|
| `VAULT_DIR` | Path to your Obsidian vault root | `~/personal-vault` |
| `UDISKS_ROOT` | Directory where removable media is mounted | `/run/media/$USER` |
| `DB_PATH` | Full path to the Kobo SQLite database | `/run/media/$USER/KOBOeReader/.kobo/KoboReader.sqlite` |

## Usage

The `run` script sets up the environment and activates the virtualenv:

```sh
# One-shot sync (Kobo must already be mounted)
./run

# Watch for Kobo to mount and sync automatically
./run -w

# Only sync highlights newer than a given timestamp
./run --as-of 2024-01-01T00:00:00
```

### Options

| Flag | Description |
|---|---|
| `-w`, `--watch` | Watch for the eReader to mount and sync whenever it appears |
| `--as-of <ISO8601>` | Only sync highlights created after this timestamp (overrides saved state) |

## Running as a systemd service

A user service unit is provided in `kobo-highlight-obsidian-sync.service`. It runs the script in watch mode so highlights are synced automatically whenever you plug in your Kobo.

Install and enable it:

```sh
cp kobo-highlight-obsidian-sync.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kobo-highlight-obsidian-sync
```

The service uses these default paths which you can override by editing the unit file:

- Vault: `~/personal-vault`
- Media root: `/run/media/<user>`
- Database: `/run/media/<user>/KOBOeReader/.kobo/KoboReader.sqlite`

Check service logs with:

```sh
journalctl --user -u kobo-highlight-obsidian-sync -f
```

## Vault structure

The script expects (and will create if missing) the following directories inside your vault:

```
<VAULT_DIR>/
  books/      # One note per book title
  journal/    # Daily notes named YYYY-MM-DD.md
```
