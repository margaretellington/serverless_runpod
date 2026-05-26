#!/bin/bash
set -e

PORT="${COMFYUI_PORT:-8188}"
LISTEN="${COMFYUI_LISTEN:-0.0.0.0}"
MODEL_VOLUME="${MODEL_VOLUME:-/runpod-volume/models}"

# If a network volume has pre-downloaded models, symlink them into ComfyUI
if [ -d "${MODEL_VOLUME}" ]; then
    echo "Linking models from network volume ${MODEL_VOLUME}..."
    for folder in unet clip vae audio_encoders loras frame_interpolation; do
        if [ -d "${MODEL_VOLUME}/${folder}" ]; then
            # Remove the stock empty directory and replace with a symlink
            rm -rf "/app/ComfyUI/models/${folder}"
            ln -sf "${MODEL_VOLUME}/${folder}" "/app/ComfyUI/models/${folder}"
            echo "  ✓ models/${folder}"
        fi
    done
else
    echo "No network volume found at ${MODEL_VOLUME} — using image-baked models if present."
fi

echo "Starting ComfyUI on ${LISTEN}:${PORT}..."

python /app/ComfyUI/main.py \
    --listen "${LISTEN}" \
    --port "${PORT}" \
    --disable-auto-launch \
    --use-pytorch-cross-attention &

COMFY_PID=$!

# Wait for ComfyUI to be ready
echo "Waiting for ComfyUI to become ready..."
for i in $(seq 1 120); do
    if curl -s "http://127.0.0.1:${PORT}/system_stats" > /dev/null 2>&1; then
        echo "ComfyUI is ready (PID: ${COMFY_PID})."
        exit 0
    fi
    sleep 1
done

echo "ERROR: ComfyUI failed to start within 120 seconds."
exit 1
