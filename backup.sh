#!/usr/bin/bash -x

# === Config ===
REMOTE_NAME="google:"
REMOTE_FOLDER="work-backup-laptop-p4"
TMP_DIR="$HOME/tmp_backup"
EXCLUDE_FILE="$TMP_DIR/exclude-list.txt"
ARCHIVE_DATE="$(date +%Y-%m-%d)"
ARCHIVE_NAME="home-backup-$ARCHIVE_DATE.tar.gz"
ARCHIVE_PATH="$TMP_DIR/$ARCHIVE_NAME"
RCLONE_DEST="$REMOTE_NAME$REMOTE_FOLDER"

# === Ensure cleanup on exit ===
trap 'echo "Cleaning up temporary files..."; rm -rf "$TMP_DIR"' EXIT

# === Ensure tmp dir ===
mkdir -p "$TMP_DIR"

# === Write exclude list ===
cat > "$EXCLUDE_FILE" <<EOF
src/**
Downloads/**
.cache/**
.esmtp_queue/**
.mozilla/**
.llama/**
.npm/**
Documents/backup/**
tmp_backup/**
./.vscode/**
./.local/lib/**
./.local/share/**
./.ansible/**
./.continue/**
./.kube/**
./.vosk/**
./Documents/CandD/**
./.docker/**
Android/**
.var/**
.gradle/**
.nvm/**
.rustup/**
.jdks/**
.npm-global/**
.cargo/**
.wine/**
.steam/**
Games/**
Videos/**
.dotnet/**
.java/**
.semgrep/**
.sonarlint/**
.nv/**
.android/**
.password-store-bak/**
.steampid
.bash_history-*.tmp
Documents/backup.log
.antigravity/**
.git

# --- Application Config Exclusions ---
# General cache, log, and temp directories
*[Cc]ache*
*CacheStorage*
*[Ss]ervice [Ww]orker*
*[Ll]ogs*
*Code Cache*
*GPUCache*
*Crashpad*
*blob_storage*
*Local Storage*
*Session Storage*
*SharedStorage*
*TransportSecurity*
*Shared Dictionary*
*workspaceStorage*
*globalStorage*

# Browser Data
./.config/brave-browser/**
./.config/BraveSoftware/**
./.config/chromium/**
./.config/microsoft-edge/**
./.config/microsoft-edge-beta/**
./.config/microsoft-edge-dev/**

# Development Tools & Terminals
./.config/warp-terminal/**
./.config/waveterm/**
./.config/gcloud/logs/**
./.config/Cypress/**
./.config/Google/AndroidStudio*/**
./.config/Code/User/History/**

# --- More Application Caches ---
*leveldb*
*/*/File System/**
*/*/IndexedDB/**
*/*/Storage/**
*/*/Sessions/**
*/*/Web Applications/**
*/*/screen_ai/**
.config/Code/Backups/**
.config/Code/User/History/**
.config/github-copilot/multiLanguageContextProviderDocumentSymbols/**
.config/libreoffice/4/user/backup/**
.config/libreoffice/4/user/extensions/tmp/**
.config/libreoffice/4/user/uno_packages/cache/**
.config/fragments/**
.config/session/**
**OptGuideOnDeviceModel**

# Other Applications
**zed.app*
**/cursor
**/oc
**/bw
**/promtool
./.config/abrt/**
./.config/evolution/**
./.config/GIMP/**
./.config/obs-studio/**
./.config/transmission/**
./.config/vlc/**
./.config/Trolltech/**
./.config/Bitwarden/**
./.config/pgadmin4/**
./.config/VisualParadigm/ws/**
./.config/VisualParadigm/tmp/**
./.config/deluge/state/**
./.config/deluge/*.log
./.config/dfakeseeder/torrents/**
./.config/libvirt/qemu/**
./.config/filezilla/queue.sqlite3
./.config/libreoffice/**

# --- Large Data Exclusions ---
./.config/ollama-nvidia/**
./.config/ollama-cpu/**
./.config/ollama-igpu/**
./.config/ollama-npu/**
./.config/aa-workflow/**
./.config/meet-bot-chrome/**
./.config/Cursor/**
.libvirt/**

# --- Selective Backups ---
.cursor/extensions/**
.cursor/plans/**
.cursor/projects/**

# .claude
.claude/debug/**
.claude/downloads/**
.claude/file-history/**
.claude/ide/**
.claude/plans/**
.claude/projects/**
.claude/session-env/**
.claude/shell-snapshots/**
.claude/statsig/**
.claude/todos/**

# .gemini
.gemini/antigravity/**
.gemini/tmp/**

# .codex
.codex/log/**
.codex/sessions/**
EOF

# === Create the archive with verbose output ===
echo "Creating archive (showing archived files)..."
cd "$HOME"
tar -czvf "$ARCHIVE_PATH" --exclude-from="$EXCLUDE_FILE" . 2>&1 | tee /home/daoneill/Documents/backup.log


# === Upload to rclone ===
echo "Uploading to rclone remote..."
rclone copy "$ARCHIVE_PATH" "$RCLONE_DEST/daily/" --progress

# === Retention policy ===
echo "Applying retention policy..."

# Delete daily backups older than 30 days
rclone delete --min-age 31d "$RCLONE_DEST/daily/" --include "home-backup-*.tar.gz"

# Copy one backup per month to monthly/ if not already present
MONTHLY_BACKUP_NAME="home-backup-$(date +%Y-%m-01).tar.gz"
if ! rclone ls "$RCLONE_DEST/monthly/" | grep -q "$MONTHLY_BACKUP_NAME"; then
    echo "Saving monthly snapshot: $MONTHLY_BACKUP_NAME"
    rclone copy "$ARCHIVE_PATH" "$RCLONE_DEST/monthly/" --progress
fi

# Delete monthly backups older than 12 months
rclone delete --min-age 366d "$RCLONE_DEST/monthly/" --include "home-backup-*.tar.gz"

echo "Backup complete."

