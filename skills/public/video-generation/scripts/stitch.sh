#!/usr/bin/env bash
# Concatenate two or more generated video clips into one deliverable MP4/MOV via ffmpeg.
#
# Usage:
#   bash stitch.sh \
#     --output-file /mnt/user-data/outputs/final-ad.mp4 \
#     --inputs /mnt/user-data/outputs/clip-1.mp4 /mnt/user-data/outputs/clip-2.mp4 [...] \
#     [--mode normalize|copy] \
#     [--fps 24]

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: stitch.sh --output-file <path.(mp4|mov)> --inputs <clip1> <clip2> [clip3 ...] [--mode normalize|copy] [--fps <int>]

Options:
  --output-file  Destination video path (.mp4 or .mov). Written atomically; existing output is preserved on failure.
  --inputs       Two or more input video clip files in playback order.
  --mode         normalize (default, re-encodes to H.264/AAC for reliable cuts) or copy (lossless stream copy).
  --fps          Optional constant frame rate integer (1-120), supported only in normalize mode.
  -h, --help     Show this help message.
EOF
}

OUTPUT_FILE=""
MODE="normalize"
FPS=""
INPUTS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-file)
      if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
        echo "Error: --output-file requires a file path" >&2
        exit 1
      fi
      OUTPUT_FILE="$2"
      shift 2
      ;;
    --mode)
      if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
        echo "Error: --mode requires 'normalize' or 'copy'" >&2
        exit 1
      fi
      MODE="$2"
      shift 2
      ;;
    --fps)
      if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
        echo "Error: --fps requires a positive integer" >&2
        exit 1
      fi
      FPS="$2"
      shift 2
      ;;
    --inputs)
      shift
      while [[ $# -gt 0 && "$1" != --* ]]; do
        INPUTS+=("$1")
        shift
      done
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$OUTPUT_FILE" ]]; then
  echo "Error: --output-file is required" >&2
  exit 1
fi

if [[ "$OUTPUT_FILE" == *$'\n'* || "$OUTPUT_FILE" == *$'\r'* ]]; then
  echo "Error: --output-file path must not contain newline characters" >&2
  exit 1
fi

if [[ -d "$OUTPUT_FILE" ]]; then
  echo "Error: --output-file points to an existing directory: $OUTPUT_FILE" >&2
  exit 1
fi

case "$MODE" in
  normalize|copy) ;;
  *)
    echo "Error: unsupported --mode '$MODE' (expected 'normalize' or 'copy')" >&2
    exit 1
    ;;
esac

if [[ -n "$FPS" ]]; then
  if [[ "$MODE" != "normalize" ]]; then
    echo "Error: --fps is only supported with --mode normalize" >&2
    exit 1
  fi
  if [[ ! "$FPS" =~ ^[1-9][0-9]*$ ]] || (( FPS > 120 )); then
    echo "Error: --fps must be an integer between 1 and 120, got '$FPS'" >&2
    exit 1
  fi
fi

if [[ "${#INPUTS[@]}" -lt 2 ]]; then
  echo "Error: --inputs requires at least 2 video clips, got ${#INPUTS[@]}" >&2
  exit 1
fi

OUT_LOWER="$(printf '%s' "$OUTPUT_FILE" | tr '[:upper:]' '[:lower:]')"
case "$OUT_LOWER" in
  *.mp4) OUT_EXT="mp4" ;;
  *.mov) OUT_EXT="mov" ;;
  *)
    echo "Error: unsupported output extension for '$OUTPUT_FILE' (supported: .mp4, .mov)" >&2
    exit 1
    ;;
esac

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Error: ffmpeg is required for multi-shot video stitching but was not found on PATH" >&2
  exit 1
fi

resolve_abs_path() {
  local target="$1"
  local dir
  dir="$(cd "$(dirname "$target")" && pwd -P)"
  printf '%s/%s\n' "$dir" "$(basename "$target")"
}

ABS_INPUTS=()
for clip in "${INPUTS[@]}"; do
  if [[ "$clip" == *$'\n'* || "$clip" == *$'\r'* ]]; then
    echo "Error: input clip path must not contain newline characters" >&2
    exit 1
  fi
  if [[ ! -f "$clip" ]]; then
    echo "Error: input clip not found: $clip" >&2
    exit 1
  fi
  if [[ ! -s "$clip" ]]; then
    echo "Error: input clip is empty: $clip" >&2
    exit 1
  fi
  ABS_INPUTS+=("$(resolve_abs_path "$clip")")
done

OUT_DIR="$(dirname "$OUTPUT_FILE")"
mkdir -p "$OUT_DIR"

TMP_DIR="$(mktemp -d "${OUT_DIR}/.stitch-tmp.XXXXXX")"
MANIFEST="${TMP_DIR}/concat.txt"
TMP_OUTPUT="${TMP_DIR}/output.${OUT_EXT}"

cleanup() {
  rm -f "$MANIFEST" "$TMP_OUTPUT"
  rmdir "$TMP_DIR" 2>/dev/null || true
}
trap cleanup EXIT

escape_concat_path() {
  local remaining="$1"
  local quote="'"
  local out=""
  while [[ "$remaining" == *"$quote"* ]]; do
    out+="${remaining%%"$quote"*}'\\''"
    remaining="${remaining#*"$quote"}"
  done
  printf '%s%s' "$out" "$remaining"
}

: > "$MANIFEST"
for abs_clip in "${ABS_INPUTS[@]}"; do
  escaped="$(escape_concat_path "$abs_clip")"
  printf "file '%s'\n" "$escaped" >> "$MANIFEST"
done

FFMPEG_ARGS=(
  -nostdin
  -hide_banner
  -loglevel error
  -y
  -f concat
  -safe 0
  -i "$MANIFEST"
)

if [[ "$MODE" == "copy" ]]; then
  FFMPEG_ARGS+=(-c copy)
else
  FFMPEG_ARGS+=(-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p)
  if [[ -n "$FPS" ]]; then
    FFMPEG_ARGS+=(-r "$FPS")
  fi
  FFMPEG_ARGS+=(-c:a aac -b:a 192k -ar 48000)
fi

FFMPEG_ARGS+=(-movflags +faststart "$TMP_OUTPUT")

ffmpeg "${FFMPEG_ARGS[@]}"

if [[ ! -s "$TMP_OUTPUT" ]]; then
  echo "Error: ffmpeg completed without producing a non-empty output file" >&2
  exit 1
fi

mv -f "$TMP_OUTPUT" "$OUTPUT_FILE"
printf 'Stitched %d clips successfully to %s\n' "${#ABS_INPUTS[@]}" "$OUTPUT_FILE"
