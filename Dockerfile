FROM runpod/base:0.6.3-cuda12.4.0

# System deps for ComfyUI
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Use Python 3.11
RUN ln -sf $(which python3.11) /usr/local/bin/python && \
    ln -sf $(which python3.11) /usr/local/bin/python3

WORKDIR /app/ComfyUI

# Clone ComfyUI and install Python deps
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /app/ComfyUI && \
    pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121 && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir runpod boto3 requests huggingface_hub

# Copy worker files
COPY handler.py /app/handler.py
COPY start-comfy.sh /app/start-comfy.sh
COPY wan_audio_workflow.json /app/wan_audio_workflow.json
RUN chmod +x /app/start-comfy.sh

# Models go on a RunPod network volume mounted at /runpod-volume/models
# The start-comfy.sh script will symlink them at runtime if available

ENV COMFYUI_PORT=8188
ENV COMFYUI_LISTEN=0.0.0.0
ENV MODEL_VOLUME=/runpod-volume/models
ENV S3_ENDPOINT=https://s3api-us-il-1.runpod.io
ENV S3_BUCKET=comfyui-wan-outputs

# Start ComfyUI then launch the RunPod handler
CMD ["bash", "-c", "/app/start-comfy.sh && python -u /app/handler.py"]
