import base64
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


TARGET_BVID = "BV1ZW42197oE"
MAX_VIDEO_SECONDS = 1937
LAST_FRAME_SECOND = MAX_VIDEO_SECONDS - 1
AIPING_BASE_URL = "https://aiping.cn/api/v1"
AIPING_MODEL = "Kimi-K2.7-Code"
MLX_WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"


class PipelineUnavailable(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True)
class JobContext:
    bvid: str
    job_id: str
    workdir: Path

    def prepare(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Transcript:
    text: str
    segments: list[dict[str, Any]]


class Downloader(Protocol):
    def download(self, bvid: str, context: JobContext) -> Path: ...


class Transcriber(Protocol):
    def transcribe(self, video: Path, context: JobContext) -> Transcript: ...


class FrameExtractor(Protocol):
    def extract(self, video: Path, context: JobContext) -> list[Path]: ...


class SkillCompiler(Protocol):
    def compile(self, transcript: Transcript, frames: list[Path], context: JobContext) -> str: ...

    def repair(self, raw_output: str, error: str, context: JobContext) -> str: ...


class SkillValidator(Protocol):
    def validate(self, raw_output: str) -> dict[str, Any]: ...


class LocalVideoDownloader:
    def __init__(self, inputs_dir: Path):
        self.inputs_dir = inputs_dir

    def download(self, bvid: str, context: JobContext) -> Path:
        if bvid != TARGET_BVID:
            raise PipelineUnavailable("download", "only BV1ZW42197oE is supported")
        video = self.inputs_dir / f"{bvid}.mp4"
        if video.exists():
            return video
        try:
            import yt_dlp
        except ImportError as error:
            raise PipelineUnavailable("download", "yt-dlp dependency is not installed") from error
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        try:
            with yt_dlp.YoutubeDL(
                {
                    "format": "bv*+ba/b",
                    "outtmpl": str(self.inputs_dir / f"{bvid}.%(ext)s"),
                    "merge_output_format": "mp4",
                    "quiet": True,
                    "no_warnings": True,
                }
            ) as downloader:
                downloader.download([f"https://www.bilibili.com/video/{bvid}"])
        except Exception as error:
            raise PipelineUnavailable("download", "yt-dlp could not download the target video") from error
        if not video.exists():
            raise PipelineUnavailable("download", "yt-dlp did not produce the target mp4")
        return video


class MLXTranscriber:
    def transcribe(self, video: Path, context: JobContext) -> Transcript:
        try:
            from mlx_whisper import transcribe
        except ImportError as error:
            raise PipelineUnavailable(
                "transcribe", "mlx-whisper dependency is not installed; install the MLX ASR dependencies",
            ) from error
        try:
            result = transcribe(
                str(video),
                path_or_hf_repo=MLX_WHISPER_MODEL,
                word_timestamps=True,
                verbose=False,
            )
        except Exception as error:
            raise PipelineUnavailable("transcribe", "MLX ASR transcription failed") from error
        segments = result.get("segments") if isinstance(result, dict) else None
        if not isinstance(segments, list) or not segments:
            raise PipelineUnavailable("transcribe", "MLX ASR did not return timestamped segments")
        if any(not isinstance(segment, dict) or "start" not in segment or "end" not in segment for segment in segments):
            raise PipelineUnavailable("transcribe", "MLX ASR segments are missing timestamps")
        if any(
            not isinstance(segment.get("words"), list)
            or not segment["words"]
            or any(not isinstance(word, dict) or "start" not in word or "end" not in word for word in segment["words"])
            for segment in segments
        ):
            raise PipelineUnavailable("transcribe", "MLX ASR segments are missing word timestamps")
        text = str(result.get("text") or " ".join(str(segment.get("text", "")) for segment in segments)).strip()
        if not text:
            raise PipelineUnavailable("transcribe", "MLX ASR returned an empty transcript")
        payload = {"model": MLX_WHISPER_MODEL, "text": text, "segments": segments}
        (context.workdir / "transcript.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return Transcript(text=text, segments=segments)


CommandRunner = Callable[[list[str]], None]


def run_command(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


class FFmpegFrameExtractor:
    def __init__(self, runner: CommandRunner = run_command, interval_seconds: int = 60):
        self.runner = runner
        self.interval_seconds = interval_seconds

    def extract(self, video: Path, context: JobContext) -> list[Path]:
        if self.interval_seconds <= 0:
            raise PipelineUnavailable("frames", "frame sampling interval must be positive")
        frames_dir = context.workdir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        timestamps = list(range(0, LAST_FRAME_SECOND, self.interval_seconds))
        if not timestamps or timestamps[-1] != LAST_FRAME_SECOND:
            timestamps.append(LAST_FRAME_SECOND)
        frames: list[Path] = []
        for timestamp in timestamps:
            frame = frames_dir / f"frame-{timestamp:04d}.jpg"
            try:
                self.runner(
                    [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        str(timestamp),
                        "-i",
                        str(video),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=640:-2",
                        str(frame),
                    ]
                )
            except Exception as error:
                raise PipelineUnavailable("frames", f"ffmpeg frame extraction failed at {timestamp}s") from error
            if not frame.exists():
                raise PipelineUnavailable("frames", f"ffmpeg did not write the frame at {timestamp}s")
            frames.append(frame)
        manifest = {
            "videoSeconds": MAX_VIDEO_SECONDS,
            "intervalSeconds": self.interval_seconds,
            "frames": [{"timestampSeconds": timestamp, "path": str(frame.relative_to(context.workdir))} for timestamp, frame in zip(timestamps, frames)],
        }
        (context.workdir / "frames.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return frames


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Starter(StrictModel):
    html: str
    css: str
    js: str


class JestTest(StrictModel):
    framework: Literal["jest"]
    name: str = Field(min_length=1)
    code: str = Field(min_length=1)


class TimestampEvidence(StrictModel):
    startSeconds: float = Field(ge=0, le=MAX_VIDEO_SECONDS)
    endSeconds: float = Field(ge=0, le=MAX_VIDEO_SECONDS)

    @model_validator(mode="after")
    def has_valid_range(self) -> "TimestampEvidence":
        if self.endSeconds <= self.startSeconds:
            raise ValueError("evidence endSeconds must be greater than startSeconds")
        return self


class AudioEvidence(TimestampEvidence):
    quote: str = Field(min_length=1)


class VisualEvidence(TimestampEvidence):
    description: str = Field(min_length=1)


class Evidence(StrictModel):
    audio: AudioEvidence
    visual: VisualEvidence


class SkillStep(StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    videoSeconds: int = Field(ge=0, le=MAX_VIDEO_SECONDS)
    starter: Starter
    tests: list[JestTest] = Field(min_length=1)
    hint: str = Field(min_length=1)
    failureExplanation: str = Field(min_length=1)
    evidence: Evidence


class GeneratedSkill(StrictModel):
    bvid: Literal["BV1ZW42197oE"]
    title: str = Field(min_length=1)
    steps: list[SkillStep]

    @field_validator("steps")
    @classmethod
    def has_exactly_four_steps(cls, steps: list[SkillStep]) -> list[SkillStep]:
        if len(steps) != 4:
            raise ValueError("steps must contain exactly 4 items")
        return steps


class PydanticSkillValidator:
    def validate(self, raw_output: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError as error:
            raise PipelineUnavailable("validate", f"invalid JSON: {error.msg}") from error
        try:
            return GeneratedSkill.model_validate(parsed).model_dump(mode="json")
        except ValidationError as error:
            raise PipelineUnavailable("validate", f"skill schema validation failed: {error}") from error


class AIPingSkillCompiler:
    def __init__(self, project_root: Path):
        self.project_root = project_root

    def compile(self, transcript: Transcript, frames: list[Path], context: JobContext) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": self._compile_prompt(transcript)}]
        for frame in frames:
            try:
                image = base64.b64encode(frame.read_bytes()).decode("ascii")
            except OSError as error:
                raise PipelineUnavailable("compile", "could not read a full-video key frame") from error
            timestamp = int(frame.stem.rsplit("-", 1)[-1])
            content.extend(
                [
                    {"type": "text", "text": f"VIDEO FRAME timestamp={timestamp}s"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
                ]
            )
        raw_output = self._request(
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": content},
            ]
        )
        (context.workdir / "compile.raw.txt").write_text(raw_output, encoding="utf-8")
        return raw_output

    def repair(self, raw_output: str, error: str, context: JobContext) -> str:
        repaired = self._request(
            [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": (
                        "Repair this output. Return only a complete valid JSON object. "
                        f"Validation error:\n{error}\n\nOriginal output:\n{raw_output}"
                    ),
                },
            ]
        )
        (context.workdir / "repair.raw.txt").write_text(repaired, encoding="utf-8")
        return repaired

    def _request(self, messages: list[dict[str, Any]]) -> str:
        load_dotenv(self.project_root / ".env.local")
        api_key = os.getenv("AIPING_API_KEY")
        if not api_key:
            raise PipelineUnavailable("compile", "AIPING_API_KEY is not configured")
        try:
            response = httpx.post(
                f"{AIPING_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": AIPING_MODEL, "messages": messages, "temperature": 0},
                timeout=120,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise PipelineUnavailable("compile", "AI compilation request failed") from error
        if not isinstance(content, str) or not content.strip():
            raise PipelineUnavailable("compile", "AI compilation returned empty content")
        return content

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You produce Video2Skill JSON only. Do not use Markdown fences or prose. "
            "The JSON must contain bvid exactly BV1ZW42197oE, a non-empty title, and exactly four steps. "
            "Every step needs id, title, integer videoSeconds from 0 through 1937, starter with html/css/js, "
            "at least one non-empty Jest test ({framework:'jest', name, code}), hint, failureExplanation, "
            "and evidence.audio(startSeconds,endSeconds,quote) plus evidence.visual(startSeconds,endSeconds,description). "
            "Evidence times must be between 0 and 1937 and end after start."
        )

    @staticmethod
    def _compile_prompt(transcript: Transcript) -> str:
        timestamped = "\n".join(
            f"[{segment['start']:.2f}-{segment['end']:.2f}] {str(segment.get('text', '')).strip()}"
            for segment in transcript.segments
        )
        return (
            "Use the full transcript and the full-video key frames supplied with this message to create four executable "
            "web-learning steps. Cite meaningful audio and visual evidence with real timestamps.\n\n"
            f"FULL TRANSCRIPT:\n{transcript.text}\n\nTIMESTAMPED SEGMENTS:\n{timestamped}"
        )


StageObserver = Callable[[str, str], None]


class Pipeline:
    def __init__(
        self,
        downloader: Downloader | None = None,
        transcriber: Transcriber | None = None,
        frame_extractor: FrameExtractor | None = None,
        compiler: SkillCompiler | None = None,
        validator: SkillValidator | None = None,
        project_root: Path | None = None,
    ):
        root = project_root or Path(__file__).parents[2]
        self.downloader = downloader or LocalVideoDownloader(root / "inputs")
        self.transcriber = transcriber or MLXTranscriber()
        self.frame_extractor = frame_extractor or FFmpegFrameExtractor()
        self.compiler = compiler or AIPingSkillCompiler(root)
        self.validator = validator or PydanticSkillValidator()

    def run(self, bvid: str, context: JobContext, observe: StageObserver | None = None) -> dict[str, Any]:
        if bvid != TARGET_BVID or context.bvid != TARGET_BVID:
            raise PipelineUnavailable("download", "only BV1ZW42197oE is supported")
        context.prepare()
        video = self._run_stage("download", lambda: self.downloader.download(bvid, context), observe)
        transcript = self._run_stage("transcribe", lambda: self.transcriber.transcribe(video, context), observe)
        frames = self._run_stage("frames", lambda: self.frame_extractor.extract(video, context), observe)
        raw_output = self._run_stage("compile", lambda: self.compiler.compile(transcript, frames, context), observe)
        skill = self._run_stage("validate", lambda: self._validate_with_repair(raw_output, context), observe)
        (context.workdir / "skill.json").write_text(json.dumps(skill, ensure_ascii=False, indent=2), encoding="utf-8")
        return skill

    def _validate_with_repair(self, raw_output: str, context: JobContext) -> dict[str, Any]:
        try:
            return self.validator.validate(raw_output)
        except PipelineUnavailable as initial_error:
            repaired = self.compiler.repair(raw_output, str(initial_error), context)
            try:
                return self.validator.validate(repaired)
            except PipelineUnavailable as repaired_error:
                raise PipelineUnavailable("validate", f"skill repair failed: {repaired_error}") from repaired_error

    @staticmethod
    def _run_stage(stage: str, action: Callable[[], Any], observe: StageObserver | None) -> Any:
        if observe:
            observe(stage, "running")
        result = action()
        if observe:
            observe(stage, "completed")
        return result
