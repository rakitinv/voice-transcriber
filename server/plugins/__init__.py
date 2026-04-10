"""
Plugin architecture for:
- ASR providers
- diarization providers
- LLM providers

Each provider type will expose a minimal interface so that implementations
such as Whisper, Faster-Whisper, Vosk, WhisperX, Pyannote, Ollama, etc.
can be wired without changing core business logic.
"""

