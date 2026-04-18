#!/bin/bash
# Optimized 4K desktop recording using Intel Arc VA-API via FFmpeg
# Requires portal screen capture to be piped in via pw-record or similar
# This version uses kmsgrab (requires root/CAP_SYS_ADMIN) for direct capture

set -euo pipefail

OUTPUT_DIR="${HOME}/Recordings"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="${OUTPUT_DIR}/desktop_${TIMESTAMP}.mp4"

DEFAULT_SINK=$(pactl get-default-sink)
AUDIO_MONITOR="${DEFAULT_SINK}.monitor"

mkdir -p "${OUTPUT_DIR}"

echo "=== Intel Arc Desktop Recording (FFmpeg) ==="
echo "Output: ${OUTPUT_FILE}"
echo "Audio: ${AUDIO_MONITOR}"
echo "Press q to stop recording."
echo ""

# FFmpeg with VAAPI on Intel Arc (renderD128)
# - Uses PulseAudio/PipeWire for audio
# - kmsgrab for DRM capture (requires privileges)
exec nice -10 ionice -c2 -n0 ffmpeg -y \
    -vaapi_device /dev/dri/renderD128 \
    -f pulse -i "${AUDIO_MONITOR}" \
    -f kmsgrab -framerate 60 -i - \
    -vf 'hwmap=derive_device=vaapi,scale_vaapi=format=nv12' \
    -c:v h264_vaapi \
    -qp 23 \
    -g 60 \
    -bf 0 \
    -c:a aac -b:a 192k -ar 48000 \
    -movflags +faststart \
    "${OUTPUT_FILE}"
