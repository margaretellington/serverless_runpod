# ComfyUI — WAN 2.2 S2V Audio-to-Video (RunPod Serverless)

[![Runpod](https://api.runpod.io/badge/margaretellington/serverless_runpod)](https://console.runpod.io/hub/margaretellington/serverless_runpod)

Generate talking-head videos from a reference image + audio file using **WAN 2.2 S2V 14B** on RunPod Serverless.

## How it works

1. Provide an `image_url` (reference photo) and `audio_url` (speech/audio file)
2. The worker downloads the inputs, patches the WAN S2V workflow, and submits it to ComfyUI
3. ComfyUI generates a lip-synced video — frame-interpolated for smooth output
4. The video is uploaded to your RunPod S3 bucket and the URL is returned

## Zero-config startup

All 6 model files (~25 GB) are **auto-downloaded** from HuggingFace on the first cold start. No network volume or manual model caching required. If you attach a RunPod network volume with pre-downloaded models, those are used instead.

## Job input

```json
{
  "input": {
    "image_url": "https://example.com/portrait.png",
    "audio_url": "https://example.com/speech.mp3",
    "positive_prompt": "A person speaking naturally to the camera...",
    "negative_prompt": "blurry, low quality, distorted",
    "seed": 42,
    "steps": 4,
    "cfg": 1.0,
    "width": 320,
    "height": 480,
    "num_frames": 77,
    "chunk_length": 114,
    "batch_size": 1,
    "frame_multiplier": 2,
    "timeout": 600
  }
}
```

| Parameter | Default | Description |
|---|---|---|
| `image_url` | (required) | URL of the reference portrait image |
| `audio_url` | (required) | URL of the audio file to drive lip sync |
| `positive_prompt` | — | Positive text prompt guiding the video |
| `negative_prompt` | — | Negative prompt (things to avoid) |
| `seed` | random | RNG seed for reproducibility |
| `steps` | 4 | Sampling steps (4 with LightX2V LoRA) |
| `cfg` | 1.0 | CFG scale |
| `width` | 320 | Output width |
| `height` | 480 | Output height |
| `num_frames` | 77 | Total frames to generate |
| `chunk_length` | 114 | Latent chunk length |
| `frame_multiplier` | 2 | Frame interpolation multiplier (1 = no interpolation) |
| `timeout` | 600 | Max seconds to wait for completion |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `S3_ENDPOINT` | `https://s3api-us-il-1.runpod.io` | S3-compatible endpoint |
| `S3_BUCKET` | `comfyui-wan-outputs` | S3 bucket for output videos |
| `S3_ACCESS_KEY_ID` | — | S3 access key |
| `S3_SECRET_ACCESS_KEY` | — | S3 secret key |
| `MODEL_VOLUME` | — | Path to network volume with pre-cached models |
| `COMFYUI_PORT` | `8188` | Internal ComfyUI server port |

## GPU requirements

**Minimum: NVIDIA A40 (48 GB VRAM)**. The WAN 2.2 S2V 14B model in FP8 needs ~24 GB VRAM for inference.
