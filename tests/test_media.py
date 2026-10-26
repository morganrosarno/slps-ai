import shutil
import subprocess
import sys

import pytest

from media import MediaError, _run, classify_transcript, inspect_video


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg and ffprobe are required for local media tests",
)


def clip(tmp_path, *, audio="tone", duration=1.2, extension="mp4"):
    target = tmp_path / f"clip.{extension}"
    command = ["ffmpeg", "-y", "-nostdin", "-v", "error", "-f", "lavfi", "-i", f"color=c=navy:s=320x180:d={duration}"]
    if audio == "tone":
        command += ["-f", "lavfi", "-i", f"sine=frequency=880:duration={duration}", "-shortest"]
    elif audio == "quiet":
        command += ["-f", "lavfi", "-i", f"sine=frequency=880:duration={duration}", "-filter:a", "volume=0.01", "-shortest"]
    elif audio == "silent":
        command += ["-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono:d={duration}", "-shortest"]
    if extension == "webm":
        command += ["-c:v", "libvpx-vp9", "-c:a", "libopus"]
    else:
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    command += [str(target)]
    subprocess.run(command, check=True)
    return target.read_bytes()


def test_extracts_adaptive_frames_and_audible_audio(tmp_path):
    raw = clip(tmp_path)
    temp_root = tmp_path / "work"
    temp_root.mkdir()
    result = inspect_video(raw, expected_mime="video/mp4", max_bytes=5_000_000, max_seconds=30, temp_root=temp_root)
    assert result["validated"] is True
    assert result["sampling"]["method"] == "timestamp_adaptive"
    assert len(result["frames"]) == 3
    assert all(frame["image_data_url"].startswith("data:image/jpeg;base64,") for frame in result["frames"])
    assert result["audio"]["status"] == "ready_for_transcription"
    assert result["transcription"]["status"] == "not_performed"
    assert result["original_retention"]["status"] == "not_implemented"
    assert list(temp_root.iterdir()) == []


def test_private_artifacts_are_returned_only_when_requested(tmp_path):
    raw = clip(tmp_path)
    public = inspect_video(raw, expected_mime="video/mp4", max_bytes=5_000_000, max_seconds=30)
    assert "_artifacts" not in public
    private = inspect_video(
        raw, expected_mime="video/mp4", max_bytes=5_000_000,
        max_seconds=30, include_artifacts=True,
    )
    assert len(private["_artifacts"]["frames"]) == len(private["frames"])
    assert all(frame["data"].startswith(b"\xff\xd8") for frame in private["_artifacts"]["frames"])
    assert private["_artifacts"]["audio"]["media_type"] == "audio/wav"
    assert private["_artifacts"]["audio"]["data"].startswith(b"RIFF")


def test_distinguishes_absent_and_silent_audio(tmp_path):
    absent = inspect_video(clip(tmp_path, audio=None, extension="webm"), expected_mime="video/webm", max_bytes=5_000_000, max_seconds=30)
    assert absent["audio"]["status"] == "absent"
    silent = inspect_video(clip(tmp_path, audio="silent"), expected_mime="video/mp4", max_bytes=5_000_000, max_seconds=30)
    assert silent["audio"]["status"] == "silent"
    quiet = inspect_video(clip(tmp_path, audio="quiet"), expected_mime="video/mp4", max_bytes=5_000_000, max_seconds=30)
    assert quiet["audio"]["status"] == "low_level"
    assert quiet["transcription"]["status"] == "not_performed"


def test_rejects_invalid_and_too_long_video(tmp_path):
    with pytest.raises(MediaError) as invalid:
        inspect_video(b"not-video", expected_mime="video/mp4", max_bytes=5_000_000, max_seconds=30)
    assert invalid.value.code == "invalid_video"
    with pytest.raises(MediaError) as long:
        inspect_video(clip(tmp_path, duration=1.2), expected_mime="video/mp4", max_bytes=5_000_000, max_seconds=1)
    assert long.value.code == "video_too_long"
    with pytest.raises(MediaError) as mismatch:
        inspect_video(clip(tmp_path, extension="webm"), expected_mime="video/mp4", max_bytes=5_000_000, max_seconds=30)
    assert mismatch.value.code == "invalid_video"


def test_subprocess_output_is_bounded():
    with pytest.raises(MediaError) as oversized:
        _run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 5000)"], 2, max_stdout=1000)
    assert oversized.value.code == "media_processing_limit"


@pytest.mark.parametrize("text", [
    "Fermate il carrello elevatore.",
    "Stoppen Sie den Gabelstapler.",
    "Arrêtez le chariot élévateur.",
    "Stop the forklift.",
])
def test_transcript_fixture_keeps_supported_language_text_without_guessing(text):
    result = classify_transcript(text)
    assert result == {"status": "available", "text": text, "language": None}


def test_transcript_states_are_explicit():
    assert classify_transcript()["status"] == "not_performed"
    assert classify_transcript("[inaudible]")["status"] == "unintelligible"
    assert classify_transcript(processing_error="failed")["status"] == "error"
