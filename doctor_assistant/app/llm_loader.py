from llama_cpp import Llama
from django.conf import settings
import threading

_llm = None
_lock = threading.Lock()

def get_llm():
    global _llm

    if _llm is None:
        with _lock:
            if _llm is None:
                model_path = settings.BASE_DIR / "model_files" / "medgemma-1.5-4b-it-Q4_K_M.gguf"
                print("Loading MedGemma GGUF model...")
                _llm = Llama(
                    model_path=str(model_path),
                    n_ctx=4096,
                    n_threads=8,
                    n_gpu_layers=0
                )
                print("Model loaded.")

    return _llm
