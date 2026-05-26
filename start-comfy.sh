#!/bin/bash
set -e

PORT="${COMFYUI_PORT:-8188}"
LISTEN="${COMFYUI_LISTEN:-0.0.0.0}"
MODEL_VOLUME="${MODEL_VOLUME:-/runpod-volume/models}"
MODEL_DIR="/app/ComfyUI/models"

REPO="Comfy-Org/Wan_2.2_ComfyUI_repackaged"
FILM_REPO="Comfy-Org/frame_interpolation"

# ---------------------------------------------------------------------------
# 1. Try network volume first
# ---------------------------------------------------------------------------
if [ -d "${MODEL_VOLUME}" ]; then
    echo "[setup] Network volume found at ${MODEL_VOLUME}, linking models..."
    for folder in unet clip vae audio_encoders loras frame_interpolation; do
        if [ -d "${MODEL_VOLUME}/${folder}" ]; then
            rm -rf "${MODEL_DIR}/${folder}"
            ln -sf "${MODEL_VOLUME}/${folder}" "${MODEL_DIR}/${folder}"
            echo "  [✓] models/${folder} → network volume"
        fi
    done
fi

# ---------------------------------------------------------------------------
# 2. Check which models are still missing
# ---------------------------------------------------------------------------
missing=0
need() {
    local dir="$1" file="$2" label="$3"
    if [ -f "${MODEL_DIR}/${dir}/${file}" ]; then
        echo "  [✓] ${label} (already present)"
    else
        echo "  [ ] ${label} — MISSING"
        missing=1
    fi
}

echo "[setup] Scanning for WAN 2.2 S2V models..."
need "unet"              "wan2.2_s2v_14B_fp8_scaled.safetensors"           "UNET"
need "clip"              "umt5_xxl_fp8_e4m3fn_scaled.safetensors"           "CLIP / Text Encoder"
need "vae"               "wan_2.1_vae.safetensors"                          "VAE"
need "audio_encoders"    "wav2vec2_large_english_fp16.safetensors"           "Audio Encoder"
need "loras"             "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"  "LoRA"
need "frame_interpolation" "film_net_fp16.safetensors"                      "Frame Interpolation"

# ---------------------------------------------------------------------------
# 3. Auto-download missing models from HuggingFace
# ---------------------------------------------------------------------------
if [ "${missing}" -eq 1 ]; then
    echo "[setup] Auto-downloading missing models from HuggingFace..."
    TMPDIR=$(mktemp -d)
    trap "rm -rf ${TMPDIR}" EXIT

    dl() {
        local repo="$1" src="$2" dest_dir="$3"
        echo "  → downloading ${dest_dir}..."
        hf download "${repo}" "${src}" --local-dir "${TMPDIR}/${dest_dir}" --local-dir-use-symlinks False -q
        # hf download nests files under the repo path, so flatten them
        find "${TMPDIR}/${dest_dir}" -name "*.safetensors" -exec mv {} "${MODEL_DIR}/${dest_dir}/" \;
        rm -rf "${TMPDIR}/${dest_dir}"
    }

    # UNET  — 16.4 GB
    if [ ! -f "${MODEL_DIR}/unet/wan2.2_s2v_14B_fp8_scaled.safetensors" ]; then
        dl "${REPO}" "split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors" "unet"
    fi

    # CLIP  — 6.74 GB
    if [ ! -f "${MODEL_DIR}/clip/umt5_xxl_fp8_e4m3fn_scaled.safetensors" ]; then
        dl "${REPO}" "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors" "clip"
    fi

    # VAE   — 254 MB
    if [ ! -f "${MODEL_DIR}/vae/wan_2.1_vae.safetensors" ]; then
        dl "${REPO}" "split_files/vae/wan_2.1_vae.safetensors" "vae"
    fi

    # Audio Encoder — 631 MB
    if [ ! -f "${MODEL_DIR}/audio_encoders/wav2vec2_large_english_fp16.safetensors" ]; then
        dl "${REPO}" "split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors" "audio_encoders"
    fi

    # LoRA  — 1.23 GB
    if [ ! -f "${MODEL_DIR}/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors" ]; then
        dl "${REPO}" "split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors" "loras"
    fi

    # FILM  — 66 MB
    if [ ! -f "${MODEL_DIR}/frame_interpolation/film_net_fp16.safetensors" ]; then
        dl "${FILM_REPO}" "frame_interpolation/film_net_fp16.safetensors" "frame_interpolation"
    fi

    echo "[setup] All models downloaded."
    du -sh "${MODEL_DIR}"/*/
fi

# ---------------------------------------------------------------------------
# 4. Start ComfyUI
# ---------------------------------------------------------------------------
echo "[setup] Starting ComfyUI on ${LISTEN}:${PORT}..."

python /app/ComfyUI/main.py \
    --listen "${LISTEN}" \
    --port "${PORT}" \
    --disable-auto-launch \
    --use-pytorch-cross-attention &

COMFY_PID=$!

echo "[setup] Waiting for ComfyUI to become ready..."
for i in $(seq 1 180); do
    if curl -s "http://127.0.0.1:${PORT}/system_stats" > /dev/null 2>&1; then
        echo "[setup] ComfyUI is ready (PID: ${COMFY_PID})."
        exit 0
    fi
    if [ $((i % 30)) -eq 0 ]; then
        echo "  ... still waiting (${i}s)"
    fi
    sleep 1
done

echo "ERROR: ComfyUI failed to start within 180 seconds."
exit 1
