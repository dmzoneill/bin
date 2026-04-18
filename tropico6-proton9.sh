#!/usr/bin/env bash
set -euo pipefail

APPID=858790
STEAM_ROOT="$HOME/.steam"
PROTON_DIR="$STEAM_ROOT/root/steamapps/common/Proton 9.0 (Beta)"
PROTON_BIN="$PROTON_DIR/proton"
GAME_EXE="$STEAM_ROOT/root/steamapps/common/Tropico 6/Tropico6.exe"

if [[ ! -x "$PROTON_BIN" ]]; then
  echo "Proton 9.0 (Beta) was not found at $PROTON_BIN" >&2
  echo "Install it from Steam > Tools before running this script." >&2
  exit 1
fi

if [[ ! -f "$GAME_EXE" ]]; then
  echo "Tropico 6 executable was not found at $GAME_EXE" >&2
  echo "Make sure the game is installed on this account." >&2
  exit 1
fi

export STEAM_COMPAT_CLIENT_INSTALL_PATH="$STEAM_ROOT"
export STEAM_COMPAT_DATA_PATH="$STEAM_ROOT/root/steamapps/compatdata/$APPID"
export SteamAppId="$APPID"
export SteamGameId="$APPID"
mkdir -p "$STEAM_COMPAT_DATA_PATH"

exec "$PROTON_BIN" run "$GAME_EXE" "$@"
