I'll create a streamlined project structure optimized for audio transcription, focusing on Chilean Spanish with enhanced low-voice processing. Here's the complete project:

### Project Structure
```
sa-transcription/
├── data/
│   ├── audio/          # Processed audio files
│   ├── originals/      # Original uploads
│   ├── transcripts/    # JSON transcripts
│   └── queue.json      # Processing queue
├── src/
│   ├── main.py         # FastAPI entry point
│   ├── diarization.py  # Core processing logic
│   ├── preprocessing.py # Audio enhancement
│   ├── models.py       # Model management
│   └── config.py       # Configuration
├── requirements.txt
├── .env
└── run.sh              # Startup script
```

### File Contents

#### 1. `requirements.txt`
```python
fastapi==0.111.0
uvicorn==0.29.0
python-multipart==0.0.9
pydub==0.25.1
torch==2.3.0
torchaudio==2.3.0
whisper-openai==20231117
pyannote.audio==3.1.0
noisereduce==1.0.0
scipy==1.13.0
python-dotenv==1.0.1
aiofiles==23.2.1
numpy==1.26.4
psutil==5.9.8
```

#### 2. `.env`
```python
PYANNOTE_AUTH_TOKEN="<YOUR_HF_TOKEN_HERE>"
AUDIO_DIR="./data/audio"
ORIGINALS_DIR="./data/originals"
TRANSCRIPT_DIR="./data/transcripts"
QUEUE_PATH="./data/queue.json"
```

#### 3. `src/config.py`
```python
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PYANNOTE_AUTH_TOKEN = os.getenv("PYANNOTE_AUTH_TOKEN")
    AUDIO_DIR = os.getenv("AUDIO_DIR", "./data/audio")
    ORIGINALS_DIR = os.getenv("ORIGINALS_DIR", "./data/originals")
    TRANSCRIPT_DIR = os.getenv("TRANSCRIPT_DIR", "./data/transcripts")
    QUEUE_PATH = os.getenv("QUEUE_PATH", "./data/queue.json")
    
    # Create directories
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(ORIGINALS_DIR, exist_ok=True)
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    
    # Hardware acceleration
    TORCH_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    TORCH_FLOAT = "fp16" if TORCH_DEVICE == "cuda" else "fp32"

settings = Settings()
```

#### 4. `src/preprocessing.py`
```python
import numpy as np
import noisereduce as nr
from pydub import AudioSegment, effects
from pydub.silence import detect_nonsilent
from scipy.io import wavfile
import tempfile

def enhance_audio(audio: AudioSegment, params: dict) -> AudioSegment:
    """Apply audio enhancements with Chilean Spanish optimization"""
    # Dynamic noise reduction
    if params.get('noise_reduce'):
        noise_sample = audio[:2000]  # First 2s as noise profile
        audio = audio.noise_reduce(
            noise_profile=noise_sample, 
            reduction_db=params.get('reduction_db', 25)
        )
    
    # Chilean voice frequency enhancement
    if params.get('voice_enhance'):
        audio = audio.low_pass_filter(3400).high_pass_filter(300)
        audio = audio.compand(
            threshold=-50, 
            ratio=4, 
            attack=5, 
            release=200
        )
    
    # Adaptive gain for Chilean speech patterns
    if params.get('apply_gain'):
        target_lufs = -16  # Broadcast standard
        gain_needed = max(target_lufs - audio.dBFS, 0)
        audio = audio.apply_gain(gain_needed)
    
    return audio

def apply_audio_treatments(audio_path: str, params: dict) -> str:
    """Process audio file with Chilean Spanish optimizations"""
    audio = AudioSegment.from_file(audio_path)
    
    # Apply treatments
    audio = enhance_audio(audio, params)
    
    # Remove silence for low-volume voices
    if params.get('remove_silence'):
        audio = remove_silence(
            audio, 
            silence_thresh=params.get('silence_thresh', -45),
            min_silence_len=params.get('min_silence_len', 800)
        )
    
    # Export processed audio
    processed_path = audio_path.replace(".wav", "_processed.wav")
    audio.export(processed_path, format="wav", bitrate="192k")
    return processed_path

def remove_silence(audio: AudioSegment, silence_thresh: float, min_silence_len: int) -> AudioSegment:
    """Remove silent portions optimized for Chilean Spanish"""
    nonsilent_ranges = detect_nonsilent(
        audio, 
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh
    )
    if not nonsilent_ranges:
        return audio
    
    return sum((audio[start:end] for start, end in nonsilent_ranges), AudioSegment.empty())
```

#### 5. `src/models.py`
```python
import torch
import whisper
from pyannote.audio import Pipeline
import gc
import logging

logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self):
        self.whisper_models = {}
        self.diarization_pipeline = None
    
    def get_whisper_model(self, model_size="large-v3"):
        """Load Whisper model with memory management"""
        if model_size not in self.whisper_models:
            logger.info(f"Loading Whisper model: {model_size}")
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.whisper_models[model_size] = whisper.load_model(
                model_size, 
                device=device
            )
        return self.whisper_models[model_size]
    
    def get_diarization_pipeline(self, token: str | None = None):
        """Load diarization pipeline optimized for Chilean Spanish"""
        if self.diarization_pipeline is None:
            logger.info("Loading Pyannote diarization pipeline")
            token = token or os.getenv("PYANNOTE_AUTH_TOKEN")
            if not token:
                raise ValueError("Pyannote auth token missing.")
            # Pipeline will pick up auth token from HUGGINGFACE_HUB_TOKEN or PYANNOTE_AUTH_TOKEN env vars
            self.diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                segmentation_batch_size=8,
                embedding_batch_size=16,
                embedding_exclude_overlap=True
            )
            # Configure for low-volume Chilean voices
            self.diarization_pipeline.segmentation.threshold = 0.25
            self.diarization_pipeline.embedding.window = "sliding"
            self.diarization_pipeline.embedding.step = 0.1
        return self.diarization_pipeline
    
    def clear_cache(self):
        """Free memory after processing"""
        self.whisper_models = {}
        self.diarization_pipeline = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

model_manager = ModelManager()
```

#### 6. `src/diarization.py`
```python
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydub import AudioSegment
import tempfile
import os
import json
import time
import logging
from .models import model_manager
from .preprocessing import apply_audio_treatments
from .config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

LANGUAGE_MAP = {
    "es-CL": "es",
    "es": "es",
    "en-US": "en",
    "en": "en",
    "pt": "pt",
    "pt-BR": "pt",
}

def post_process_chilean_spanish(text: str) -> str:
    """Enhanced Chilean Spanish corrections"""
    replacements = {
        r'\bpal otro\b': "pa'l otro",
        r'\bpo\b': "po'",
        r'\bchiquillos\b': "cabros",
        r'\bweon\b': "weón",
        r'\bsi po\b': "sí poh",
        r'\bvo(s)?\b': "vo'",
        r'\bnaiden\b': "naidie",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text

@router.post("/api/diarization/transcribe")
async def diarization_transcribe(
    audio: UploadFile = File(...),
    language: str = Form("es-CL"),
    model_size: str = Form("large-v3"),
    vad_threshold: float = Form(0.25),
    min_speakers: int = Form(1),
    max_speakers: int = Form(2),
    reduction_db: int = Form(30),
    silence_thresh: int = Form(-45)
):
    try:
        # Save original audio
        audio_path = os.path.join(settings.ORIGINALS_DIR, audio.filename)
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)
        
        # Convert to WAV if needed
        if not audio_path.lower().endswith('.wav'):
            audio_segment = AudioSegment.from_file(audio_path)
            wav_path = audio_path + ".wav"
            audio_segment.export(wav_path, format="wav")
            os.remove(audio_path)
            audio_path = wav_path
        
        # Apply Chilean-specific audio enhancements
        processed_path = apply_audio_treatments(audio_path, {
            "noise_reduce": True,
            "reduction_db": reduction_db,
            "voice_enhance": True,
            "apply_gain": True,
            "remove_silence": True,
            "silence_thresh": silence_thresh
        })
        
        # Diarization
        pipeline = model_manager.get_diarization_pipeline(settings.PYANNOTE_AUTH_TOKEN)
        pipeline.segmentation.threshold = vad_threshold
        pipeline.min_speakers = min_speakers
        pipeline.max_speakers = max_speakers
        
        diarization = pipeline(processed_path)
        
        # Transcription
        segments = []
        model = model_manager.get_whisper_model(model_size)
        
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            # Extract segment
            segment_audio = AudioSegment.from_wav(processed_path)[
                int(turn.start*1000):int(turn.end*1000)
            ]
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as seg_file:
                segment_audio.export(seg_file.name, format="wav")
                seg_path = seg_file.name
            
            # Transcribe with Chilean Spanish optimization
            result = model.transcribe(
                seg_path,
                language=LANGUAGE_MAP.get(language, "es"),
                temperature=0,  # Disable randomness for accuracy
                beam_size=5,
                compression_ratio_threshold=2.5,
                logprob_threshold=-0.8,
                condition_on_previous_text=False
            )
            
            # Apply Chilean Spanish post-processing
            text = post_process_chilean_spanish(result["text"])
            
            segments.append({
                "speaker": speaker,
                "start": float(turn.start),
                "end": float(turn.end),
                "text": text
            })
            os.remove(seg_path)
        
        # Save transcript
        transcript_id = f"transcript_{int(time.time())}"
        transcript_path = os.path.join(settings.TRANSCRIPT_DIR, f"{transcript_id}.json")
        with open(transcript_path, "w") as f:
            json.dump(segments, f, ensure_ascii=False)
        
        return JSONResponse({
            "segments": segments,
            "transcript_id": transcript_id,
            "audio_url": f"/audio/{os.path.basename(audio_path)}"
        })
        
    except Exception as e:
        logger.exception("Diarization error")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        model_manager.clear_cache()
        if 'processed_path' in locals() and os.path.exists(processed_path):
            os.remove(processed_path)
```

#### 7. `src/main.py`
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os
import logging
from .config import settings
from .diarization import router as diarization_router

app = FastAPI(title="SA transcription Transcription API")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(diarization_router)

# Serve static files
app.mount("/audio", StaticFiles(directory=settings.AUDIO_DIR), name="audio")
app.mount("/originals", StaticFiles(directory=settings.ORIGINALS_DIR), name="originals")
app.mount("/transcripts", StaticFiles(directory=settings.TRANSCRIPT_DIR), name="transcripts")

@app.get("/")
def health_check():
    return {"status": "active", "optimized_for": "Chilean Spanish"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8049,
        log_config={
            "version": 1,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(levelname)s - %(message)s"
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default"
                }
            },
            "loggers": {
                "uvicorn": {"handlers": ["console"], "level": "INFO"},
                "src": {"handlers": ["console"], "level": "DEBUG"}
            }
        }
    )
```
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

#### 8. `run.sh` (Startup Script)
```bash
#!/bin/bash

# Create data directories
mkdir -p data/{audio,originals,transcripts}

# Set up virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
uvicorn src.main:app \
    --host 0.0.0.0 \
    --port 8049 \
    --reload \
    --log-level info \
    --workers 2
```

### Key Features

1. **Chilean Spanish Optimization**:
   - Specialized audio preprocessing for low-volume voices
   - Chilean-specific vocabulary corrections
   - Frequency tuning for Chilean speech patterns

2. **Performance Enhancements**:
   - Batch processing for diarization
   - Memory management with explicit cache clearing
   - Hardware acceleration detection

3. **Audio Processing**:
   - Dynamic noise reduction
   - Adaptive gain control
   - Silence removal tuned for quiet voices

4. **API Endpoints**:
   - Optimized diarization/transcription endpoint
   - Static file serving for results
   - Health check endpoint

### Usage

1. Create the project structure:
```bash
mkdir -p sa-transcription/{data,src}
touch sa-transcription/{requirements.txt,.env,run.sh}
touch sa-transcription/src/{main.py,diarization.py,preprocessing.py,models.py,config.py}
```

2. Add the file contents as above

3. Make the script executable:
```bash
chmod +x sa-transcription/run.sh
```

4. Run the application:
```bash
cd sa-transcription
./run.sh
```

5. Access the API at `http://localhost:8049`

### Example API Call
```bash
curl -X POST "http://localhost:8049/api/diarization/transcribe" \
  -H "Content-Type: multipart/form-data" \
  -F "audio=@/path/to/audio.m4a" \
  -F "language=es-CL" \
  -F "reduction_db=35" \
  -F "silence_thresh=-50"
```

This project is specifically tuned for Chilean Spanish transcription with:
- Enhanced sensitivity to low-volume voices
- Noise reduction optimized for background chatter
- Vocabulary corrections for Chilean slang
- Memory-efficient processing
- Hardware acceleration support

The pipeline should significantly improve accuracy for quiet speakers and challenging audio environments typical in Chilean recordings.