#!/usr/bin/env bash
# ffmpeg-compose.sh
# Usage: ./ffmpeg-compose.sh project_id page_images... narration.mp3 output.mp4

PROJECT_ID=$1
shift
IMAGES=($@)
# last arg is audio
AUDIO=${IMAGES[-1]}
unset 'IMAGES[${#IMAGES[@]}-1]'
OUTPUT=${PROJECT_ID}_final.mp4

# create individual clips with Ken Burns effect
COUNTER=0
INPUT_LIST="inputs.txt"
> $INPUT_LIST
for img in "${IMAGES[@]}"; do
  COUNTER=$((COUNTER+1))
  CLIP="clip_${COUNTER}.mp4"
  ffmpeg -y -loop 1 -t 5 -i "$img" -vf "scale=1920:1080,zoompan=z='min(1.1,zoom+0.0005)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'" -c:v libx264 -pix_fmt yuv420p -preset veryfast -crf 23 "$CLIP"
  echo "file '$PWD/$CLIP'" >> $INPUT_LIST
done

# concatenate and add audio
ffmpeg -y -f concat -safe 0 -i $INPUT_LIST -i "$AUDIO" -c:v libx264 -c:a aac -shortest "$OUTPUT"

# move output to /out or upload via script
mv "$OUTPUT" /out/

