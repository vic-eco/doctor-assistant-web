from transformers import pipeline
from pydub import AudioSegment
from dotenv import load_dotenv
import io
import os
import numpy as np

load_dotenv()

pipe = pipeline(
    "automatic-speech-recognition",
    model="distil-whisper/distil-medium.en",
	return_timestamps=True,
    generate_kwargs={
        "temperature": 0.0,
        "condition_on_prev_tokens": False,
    },
	token=os.getenv("HUGGINGFACE_HUB_TOKEN")
)

def transcribe_audio(recording: str):
	
	audio_bytes = recording.read()
	audio_io = io.BytesIO(audio_bytes)
	audio_io.seek(0)

    # detect actual format
	audio_seg = AudioSegment.from_file(audio_io)
	audio_seg = audio_seg.set_frame_rate(16000).set_channels(1)

	samples = np.array(audio_seg.get_array_of_samples(), dtype=np.float32)

	# Normalize based on actual bit depth
	bits = audio_seg.sample_width * 8
	samples /= np.iinfo(np.int16).max if bits == 16 else np.iinfo(np.int32).max

	result = pipe(samples)
	return result["text"].replace("</s>", "").strip()

if __name__ == "__main__":
	transcribe_audio()
