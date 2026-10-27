# bin

My personal scripts and command-line tools, kept in `~/bin`.

## Contents

- `aa-release.py`: opens a GitLab merge request that bumps a deploy-clowder ref.
- `fancy-git-commit`: writes a commit message from the current diff with the
  Claude CLI and commits.
- `python-docstring`: normalises Python docstrings.
- `pinecone-index`, `pinecone-query`, `pinecone-query-ai` and `weaviate-index`:
  index local Python code in a vector database and search it, optionally asking
  OpenAI to write code from the matches.
- `journal_report.py`: emails an HTML summary of today's systemd journal.
- `wordpress-update-code-blocks.py` and `wppost`: WordPress helpers.
- `backup.sh`: archives the home folder and uploads it with rclone.
- `record-desktop.sh` and `record-desktop-ffmpeg.sh`: record the desktop.
- `devshell`, `cloudflare-email`, `steam-x11` and `tropico6-proton9.sh`: other
  shell helpers and game launchers.
- RubyGems binstubs (`irb`, `rails`, `rdoc`, `ri`, `rubocop` and `thin`).
- Symlinks to tools in other repositories, such as `rh-issue`, `redhatter` and
  the MCP setup scripts. They only resolve on my machine.

## Tech

- Python and Bash

## Usage

Add the folder to your `PATH`. Scripts that need credentials read them from
environment variables.

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
