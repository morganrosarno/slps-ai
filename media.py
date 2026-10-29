"""Local, provider-free validation and evidence extraction for short videos."""
from array import array
import base64
import json
import math
import os
from pathlib import Path
import shutil
import selectors
import subprocess
import tempfile
import time
import wave


class MediaError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def media_tools_available(ffprobe="ffprobe", ffmpeg="ffmpeg"):
    return bool(shutil.which(ffprobe) and shutil.which(ffmpeg))


def _run(command, timeout, *, max_stdout=512_000, max_stderr=128_000):
    """Run a decoder with bounded time and bounded in-memory output."""
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise MediaError("media_processing_error", "Il file non può essere verificato in modo affidabile.", 422) from exc
    output = {process.stdout: bytearray(), process.stderr: bytearray()}
    limits = {process.stdout: max_stdout, process.stderr: max_stderr}
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    selector.register(process.stderr, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MediaError("media_processing_timeout", "La verifica del file ha superato il tempo consentito.", 422)
            for key, _mask in selector.select(min(remaining, 0.2)):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output[key.fileobj].extend(chunk)
                if len(output[key.fileobj]) > limits[key.fileobj]:
                    raise MediaError("media_processing_limit", "Il file produce dati oltre i limiti di verifica.", 422)
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except MediaError:
        process.kill()
        process.wait()
        raise
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise MediaError("media_processing_timeout", "La verifica del file ha superato il tempo consentito.", 422) from exc
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return subprocess.CompletedProcess(command, returncode, bytes(output[process.stdout]), bytes(output[process.stderr]))


def _timestamps(duration):
    # The sample count follows duration: it is deliberately not a fixed six-frame promise.
    count = min(10, max(3, math.ceil(duration / 4)))
    return [round(duration * (index + 1) / (count + 1), 3) for index in range(count)]


def classify_transcript(text=None, *, processing_error=None):
    """Classify an ASR result without pretending that transcription happened here."""
    if processing_error:
        return {"status": "error", "text": None, "language": None}
    if text is None:
        return {"status": "not_performed", "text": None, "language": None}
    cleaned = " ".join(str(text).split())
    markers = {"", "[inaudible]", "[unintelligible]", "[non comprensibile]"}
    if cleaned.casefold() in markers or len(cleaned) < 2:
        return {"status": "unintelligible", "text": None, "language": None}
    return {"status": "available", "text": cleaned, "language": None}


def _audio_metrics(wav_path):
    with wave.open(str(wav_path), "rb") as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise MediaError("audio_extraction_error", "La traccia audio estratta non è valida.", 422)
        samples = array("h", source.readframes(source.getnframes()))
        if os.sys.byteorder == "big":
            samples.byteswap()
        if not samples:
            raise MediaError("audio_extraction_error", "La traccia audio estratta è vuota.", 422)
        square_sum = sum(value * value for value in samples)
        return math.sqrt(square_sum / len(samples)), max(abs(value) for value in samples)


def inspect_video(
    raw, *, expected_mime, max_bytes, max_seconds, ffprobe="ffprobe",
    ffmpeg="ffmpeg", temp_root=None, include_artifacts=False,
):
    if not raw:
        raise MediaError("invalid_video", "Il video è vuoto.")
    if len(raw) > max_bytes:
        raise MediaError("file_too_large", "Il video supera il limite configurato.", 413)
    if expected_mime not in {"video/mp4", "video/webm", "video/quicktime"}:
        raise MediaError("invalid_media", "Formato video non supportato.")
    if not media_tools_available(ffprobe, ffmpeg):
        raise MediaError("media_tools_unavailable", "La verifica locale di video e audio non è disponibile.", 503)

    suffix = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}[expected_mime]
    with tempfile.TemporaryDirectory(prefix="slps-media-", dir=temp_root) as directory:
        job_deadline = time.monotonic() + 60
        def remaining(step_limit):
            budget = job_deadline - time.monotonic()
            if budget <= 0:
                raise MediaError("media_processing_timeout", "La verifica del file ha superato il tempo consentito.", 422)
            return min(step_limit, budget)

        source_path = Path(directory) / ("source" + suffix)
        source_path.write_bytes(raw)
        source_path.chmod(0o600)
        probe = _run([
            ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_entries", "format=duration,format_name:stream=index,codec_type,codec_name,width,height,duration,sample_rate,channels",
            "-of", "json", str(source_path),
        ], remaining(20), max_stdout=256_000)
        if probe.returncode != 0:
            raise MediaError("invalid_video", "Il contenuto non è un video valido o leggibile.")
        try:
            metadata = json.loads(probe.stdout)
            streams = metadata.get("streams", [])
            video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
            durations = [float(value) for value in [metadata.get("format", {}).get("duration"), *[stream.get("duration") for stream in streams]] if value not in (None, "N/A")]
            duration = max(durations)
        except (ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError) as exc:
            raise MediaError("invalid_video", "Il contenuto non contiene una traccia video valida.") from exc
        if not math.isfinite(duration) or duration <= 0:
            raise MediaError("invalid_video", "La durata del video non è valida.")
        if duration > max_seconds + 0.05:
            raise MediaError("video_too_long", f"Il video supera il limite di {max_seconds} secondi.", 422)
        width, height = int(video_stream.get("width") or 0), int(video_stream.get("height") or 0)
        if width <= 0 or height <= 0 or width * height > 33_177_600:
            raise MediaError("video_dimensions_invalid", "La risoluzione del video non rientra nei limiti di verifica.", 422)
        actual_formats = set(str(metadata.get("format", {}).get("format_name", "")).split(","))
        expected_formats = {"video/webm": {"webm", "matroska"}, "video/mp4": {"mov", "mp4"}, "video/quicktime": {"mov", "mp4"}}[expected_mime]
        if not actual_formats.intersection(expected_formats):
            raise MediaError("invalid_video", "Il contenuto del video non corrisponde al formato dichiarato.")

        frames = []
        frame_artifacts = []
        for timestamp in _timestamps(duration):
            extracted = _run([
                ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-ss", str(timestamp), "-i", str(source_path),
                "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=min(640\\,iw):-2",
                "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
            ], remaining(20), max_stdout=2_000_000)
            if extracted.returncode != 0 or not extracted.stdout:
                raise MediaError("frame_extraction_error", "Non è stato possibile estrarre i fotogrammi in modo affidabile.", 422)
            frames.append({
                "timestamp_seconds": timestamp,
                "image_data_url": "data:image/jpeg;base64," + base64.b64encode(extracted.stdout).decode("ascii"),
            })
            if include_artifacts:
                frame_artifacts.append({
                    "timestamp_seconds": timestamp,
                    "data": extracted.stdout,
                    "media_type": "image/jpeg",
                })

        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        audio_artifact = None
        if audio_stream is None:
            audio = {"status": "absent", "codec": None, "rms": None, "peak": None}
            transcript = {"status": "not_applicable", "text": None, "language": None}
        else:
            wav_path = Path(directory) / "audio.wav"
            extracted = _run([
                ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", str(source_path), "-map", "0:a:0",
                "-vn", "-t", str(max_seconds + 0.05), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-fs", "2500000", str(wav_path),
            ], remaining(30))
            if extracted.returncode != 0 or not wav_path.exists():
                audio = {"status": "error", "codec": audio_stream.get("codec_name"), "rms": None, "peak": None}
                transcript = classify_transcript(processing_error="audio extraction failed")
            else:
                try:
                    rms, peak = _audio_metrics(wav_path)
                    status = "silent" if peak == 0 else "low_level" if rms < 100 and peak < 1000 else "ready_for_transcription"
                    audio = {"status": status, "codec": audio_stream.get("codec_name"), "rms": round(rms, 2), "peak": peak}
                    transcript = {"status": "not_applicable", "text": None, "language": None} if status == "silent" else classify_transcript()
                    if include_artifacts:
                        audio_artifact = {
                            "data": wav_path.read_bytes(),
                            "media_type": "audio/wav",
                        }
                except (MediaError, OSError, wave.Error):
                    audio = {"status": "error", "codec": audio_stream.get("codec_name"), "rms": None, "peak": None}
                    transcript = classify_transcript(processing_error="invalid extracted audio")

        result = {
            "validated": True,
            "mime_type": expected_mime,
            "duration_seconds": round(duration, 3),
            "video": {"codec": video_stream.get("codec_name"), "width": video_stream.get("width"), "height": video_stream.get("height")},
            "frames": frames,
            "sampling": {
                "method": "timestamp_adaptive",
                "frame_count": len(frames),
                "limitation": "I fotogrammi sono campioni temporali e non rappresentano ogni istante del video.",
            },
            "audio": audio,
            "transcription": transcript,
            "original_retention": {"status": "not_implemented", "message": "Il file originale non è archiviato da questo incremento locale."},
        }
        if include_artifacts:
            # These bytes are private server-side evidence. The route removes
            # this key before serializing the public response.
            result["_artifacts"] = {
                "frames": frame_artifacts,
                "audio": audio_artifact,
            }
        return result
