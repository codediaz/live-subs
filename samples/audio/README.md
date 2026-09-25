# Clips de prueba

Estos audios son **sintéticos**, generados a partir de los guiones de referencia de esta carpeta. Se distribuyen bajo la licencia **Apache 2.0** del repositorio.

| Clip | Modelo | Voz | Fecha de generación (UTC) | Guion de referencia |
| --- | --- | --- | --- | --- |
| `charla_en.ogg` | `gemini-3.8-flash-tts` | `Kore` | 2026-09-25 | `charla_en.txt` |
| `charla_es.ogg` | `gemini-3.8-flash-tts` | `Puck` | 2026-09-25 | `charla_es.txt` |

`scripts/make_clips.py` genera cada párrafo con Gemini TTS y concatena el audio con ffmpeg. Los archivos finales usan OGG/Opus mono.
