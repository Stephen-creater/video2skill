import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.backend.pipeline import (
    AIPingSkillCompiler,
    MAX_VIDEO_SECONDS,
    FFmpegFrameExtractor,
    JobContext,
    Pipeline,
    PipelineUnavailable,
    PydanticSkillValidator,
    Transcript,
    MLXTranscriber,
)


TARGET_BVID = "BV1ZW42197oE"


def valid_skill() -> dict:
    return {
        "bvid": TARGET_BVID,
        "title": "网页卡片练习",
        "steps": [
            {
                "id": f"step-{number}",
                "title": f"第 {number} 步",
                "videoSeconds": number * 100,
                "starter": {"html": "<main></main>", "css": ".card {}", "js": ""},
                "tests": [{"framework": "jest", "name": "works", "code": "expect(true).toBe(true);"}],
                "hint": "继续完成代码。",
                "failureExplanation": "缺少关键实现。",
                "evidence": {
                    "audio": {"startSeconds": number * 100 - 1, "endSeconds": number * 100 + 1, "quote": "讲解步骤。"},
                    "visual": {"startSeconds": number * 100 - 1, "endSeconds": number * 100 + 1, "description": "代码编辑器。"},
                },
            }
            for number in range(1, 5)
        ],
    }


class Recorder:
    def __init__(self, events: list[tuple], raw: str):
        self.events = events
        self.raw = raw
        self.repairs: list[tuple[str, str, Path]] = []

    def download(self, bvid: str, context: JobContext) -> Path:
        self.events.append(("download", context.job_id))
        return context.workdir / "video.mp4"

    def transcribe(self, video: Path, context: JobContext) -> Transcript:
        self.events.append(("transcribe", context.job_id))
        return Transcript(text="完整转录文本", segments=[])

    def extract(self, video: Path, context: JobContext) -> list[Path]:
        self.events.append(("frames", context.job_id))
        return [context.workdir / "frames" / "frame-0000.jpg"]

    def compile(self, transcript: Transcript, frames: list[Path], context: JobContext) -> str:
        self.events.append(("compile", context.job_id))
        return self.raw

    def repair(self, raw_output: str, error: str, context: JobContext) -> str:
        self.repairs.append((raw_output, error, context.workdir))
        return json.dumps(valid_skill())


def context(tmp_path: Path, job_id: str) -> JobContext:
    return JobContext(bvid=TARGET_BVID, job_id=job_id, workdir=tmp_path / job_id)


def test_pipeline_runs_all_stages_in_order_for_every_regeneration(tmp_path):
    events: list[tuple] = []
    observed: list[tuple[str, str]] = []
    recorder = Recorder(events, json.dumps(valid_skill()))
    pipeline = Pipeline(recorder, recorder, recorder, recorder, PydanticSkillValidator())

    pipeline.run(TARGET_BVID, context(tmp_path, "first"), lambda stage, state: observed.append((stage, state)))
    pipeline.run(TARGET_BVID, context(tmp_path, "second"), lambda stage, state: observed.append((stage, state)))

    assert events == [
        ("download", "first"),
        ("transcribe", "first"),
        ("frames", "first"),
        ("compile", "first"),
        ("download", "second"),
        ("transcribe", "second"),
        ("frames", "second"),
        ("compile", "second"),
    ]
    assert [stage for stage, state in observed if state == "running"] == list(("download", "transcribe", "frames", "compile", "validate")) * 2
    assert [stage for stage, state in observed if state == "completed"] == list(("download", "transcribe", "frames", "compile", "validate")) * 2
    assert (tmp_path / "first" / "skill.json").exists()
    assert (tmp_path / "second" / "skill.json").exists()


def test_invalid_json_is_repaired_once_with_the_original_output(tmp_path):
    events: list[tuple] = []
    recorder = Recorder(events, "not valid json")
    pipeline = Pipeline(recorder, recorder, recorder, recorder, PydanticSkillValidator())

    skill = pipeline.run(TARGET_BVID, context(tmp_path, "repair"))

    assert skill["bvid"] == TARGET_BVID
    assert len(recorder.repairs) == 1
    assert recorder.repairs[0][0] == "not valid json"
    assert "JSON" in recorder.repairs[0][1]


def test_schema_failure_is_repaired_once_with_the_original_output(tmp_path):
    events: list[tuple] = []
    malformed = valid_skill()
    malformed["steps"] = malformed["steps"][:3]
    recorder = Recorder(events, json.dumps(malformed))
    pipeline = Pipeline(recorder, recorder, recorder, recorder, PydanticSkillValidator())

    skill = pipeline.run(TARGET_BVID, context(tmp_path, "schema-repair"))

    assert skill["bvid"] == TARGET_BVID
    assert len(recorder.repairs) == 1
    assert "exactly 4" in recorder.repairs[0][1]


def test_second_invalid_response_fails_validation_after_one_repair(tmp_path):
    events: list[tuple] = []
    recorder = Recorder(events, "not valid json")
    recorder.repair = lambda raw, error, job: "still not json"
    pipeline = Pipeline(recorder, recorder, recorder, recorder, PydanticSkillValidator())

    with pytest.raises(PipelineUnavailable, match="repair failed") as error:
        pipeline.run(TARGET_BVID, context(tmp_path, "bad-repair"))

    assert error.value.stage == "validate"


def test_strict_schema_requires_four_steps_jest_and_valid_evidence_times():
    validator = PydanticSkillValidator()
    malformed = valid_skill()
    malformed["steps"] = malformed["steps"][:3]
    with pytest.raises(PipelineUnavailable, match="exactly 4"):
        validator.validate(json.dumps(malformed))

    malformed = valid_skill()
    malformed["steps"][0]["tests"] = [{"framework": "vitest", "name": "works", "code": "expect(true).toBe(true);"}]
    with pytest.raises(PipelineUnavailable, match="jest"):
        validator.validate(json.dumps(malformed))

    malformed = valid_skill()
    malformed["steps"][0]["evidence"]["audio"]["endSeconds"] = MAX_VIDEO_SECONDS + 1
    with pytest.raises(PipelineUnavailable, match="1937"):
        validator.validate(json.dumps(malformed))


def test_frame_extractor_records_periodic_coverage_from_zero_to_video_end(tmp_path):
    commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        commands.append(command)
        Path(command[-1]).touch()

    extractor = FFmpegFrameExtractor(runner=runner, interval_seconds=900)
    workdir = tmp_path / "job"
    frames = extractor.extract(tmp_path / "video.mp4", JobContext(TARGET_BVID, "job", workdir))

    manifest = json.loads((workdir / "frames.json").read_text())
    assert [frame["timestampSeconds"] for frame in manifest["frames"]] == [0, 900, 1800, 1936]
    assert len(commands) == len(frames) == 4
    assert frames[-1].name == "frame-1936.jpg"


def test_mlx_transcriber_rejects_segments_without_word_timestamps(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "mlx_whisper",
        SimpleNamespace(transcribe=lambda *args, **kwargs: {"text": "一段文本", "segments": [{"start": 0, "end": 1, "text": "一段文本"}]}),
    )
    context = JobContext(TARGET_BVID, "asr", tmp_path / "work")
    context.prepare()

    with pytest.raises(PipelineUnavailable, match="word timestamps") as error:
        MLXTranscriber().transcribe(tmp_path / "video.mp4", context)

    assert error.value.stage == "transcribe"


def test_ai_compiler_sends_full_transcript_and_all_frames_without_a_real_request(tmp_path, monkeypatch):
    frames = []
    for name in ("frame-0000.jpg", "frame-1937.jpg"):
        frame = tmp_path / name
        frame.write_bytes(b"jpeg")
        frames.append(frame)
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(valid_skill())}}]}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setenv("AIPING_API_KEY", "test-key")
    monkeypatch.setattr("src.backend.pipeline.httpx.post", post)
    compiler = AIPingSkillCompiler(tmp_path)
    context = JobContext(TARGET_BVID, "ai", tmp_path / "work")
    context.prepare()

    raw = compiler.compile(
        Transcript(text="完整 ASR 文本", segments=[{"start": 12.5, "end": 15.0, "text": "带时间的讲解"}]),
        frames,
        context,
    )

    assert json.loads(raw)["bvid"] == TARGET_BVID
    assert calls[0][0].endswith("/chat/completions")
    assert calls[0][1]["json"]["model"] == "Kimi-K2.7-Code"
    content = calls[0][1]["json"]["messages"][1]["content"]
    assert "完整 ASR 文本" in content[0]["text"]
    assert "12.5" in content[0]["text"]
    assert "带时间的讲解" in content[0]["text"]
    assert content[1]["text"] == "VIDEO FRAME timestamp=0s"
    assert content[3]["text"] == "VIDEO FRAME timestamp=1937s"
    assert len([part for part in content if part["type"] == "image_url"]) == len(frames)
