#!/bin/bash
# download-models.sh — Run once on network volume to pre-cache all model files.
# Usage: bash download-models.sh /path/to/network-volume/models
set -euo pipefail

DEST="${1:-/runpod-volume/models}"
REPO="Comfy-Org/Wan_2.2_ComfyUI_repackaged"

mkdir -p "${DEST}/unet" "${DEST}/clip" "${DEST}/vae" \
         "${DEST}/audio_encoders" "${DEST}/loras" "${DEST}/frame_interpolation"

echo "Downloading models from ${REPO} into ${DEST}..."

# UNET — 16.4 GB
hf download "${REPO}" split_files/diffusion_models/wan2.2_s2v_14B_fp8_scaled.safetensors \
    --local-dir "${DEST}/unet" --local-dir-use-symlinks False

# CLIP / Text Encoder — 6.74 GB
hf download "${REPO}" split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
    --local-dir "${DEST}/clip" --local-dir-use-symlinks False

# VAE — 254 MB
hf download "${REPO}" split_files/vae/wan_2.1_vae.safetensors \
    --local-dir "${DEST}/vae" --local-dir-use-symlinks False

# Audio Encoder — 631 MB
hf download "${REPO}" split_files/audio_encoders/wav2vec2_large_english_fp16.safetensors \
    --local-dir "${DEST}/audio_encoders" --local-dir-use-symlinks False

# LoRA — 1.23 GB
hf download "${REPO}" split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors \
    --local-dir "${DEST}/loras" --local-dir-use-symlinks False

# Frame Interpolation — 66 MB
hf download Comfy-Org/frame_interpolation frame_interpolation/film_net_fp16.safetensors \
    --local-dir "${DEST}/frame_interpolation" --local-dir-use-symlinks False

echo "All models downloaded."
echo "Total size:" && du -sh "${DEST}"
