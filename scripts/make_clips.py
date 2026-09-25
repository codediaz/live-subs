"""Generate the two repository test clips from their reference scripts."""

import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from google import genai


ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "samples" / "audio"
MODEL = "gemini-3.8-flash-tts"
VOICES = {"en": "Kore", "es": "Puck"}


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY must be set in the environment")

    for language in VOICES:
        output = AUDIO_DIR / f"charla_{language}.ogg"
        if output.exists():
            raise FileExistsError(f"Refusing to overwrite {output}")

    client = genai.Client(api_key=api_key)
    for language, voice in VOICES.items():
        source = AUDIO_DIR / f"charla_{language}.txt"
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", source.read_text(encoding="utf-8")) if part.strip()]
        if not paragraphs:
            raise ValueError(f"No paragraphs found in {source}")

        with TemporaryDirectory(prefix=f"live-subs-tts-{language}-") as temporary:
            wav_files: list[Path] = []
            for index, paragraph in enumerate(paragraphs, start=1):
                print(f"Generating {language} paragraph {index}/{len(paragraphs)}")
                response = client.models.generate_content(
                    model=MODEL,
                    contents=[{
                        "role": "user",
                        "parts": [{
                            "text": paragraph,
                            "speech_metadata": {"style": "clear conference talk at a natural pace"},
                        }],
                    }],
                    config={
                        "response_modalities": ["AUDIO"],
                        "speech_config": {"voice_config": {"voice": voice}},
                    },
                )
                parts = response.candidates[0].content.parts if response.candidates and response.candidates[0].content else []
                audio = next((part.inline_data.data for part in parts if part.inline_data and part.inline_data.data), None)
                if not audio or not audio.startswith(b"RIFF"):
                    raise RuntimeError(f"Gemini returned no WAV audio for {language} paragraph {index}")

                wav_path = Path(temporary) / f"paragraph_{index:02d}.wav"
                wav_path.write_bytes(audio)
                wav_files.append(wav_path)

            inputs = [argument for path in wav_files for argument in ("-i", str(path))]
            streams = "".join(f"[{index}:a]" for index in range(len(wav_files)))
            output = AUDIO_DIR / f"charla_{language}.ogg"
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-n",
                    *inputs,
                    "-filter_complex", f"{streams}concat=n={len(wav_files)}:v=0:a=1[out]",
                    "-map", "[out]", "-ac", "1", "-c:a", "libopus", "-f", "ogg", str(output),
                ],
                check=True,
            )
            print(f"Created {output}")


if __name__ == "__main__":
    main()
