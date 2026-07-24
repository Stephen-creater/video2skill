from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class PipelineUnavailable(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class Downloader(Protocol):
    def download(self, bvid: str) -> Path: ...


class Transcriber(Protocol):
    def transcribe(self, video: Path) -> str: ...


class FrameExtractor(Protocol):
    def extract(self, video: Path) -> list[Path]: ...


class SkillCompiler(Protocol):
    def compile(self, transcript: str, frames: list[Path]) -> dict[str, Any]: ...


class SkillValidator(Protocol):
    def validate(self, skill: dict[str, Any]) -> None: ...


class UnavailableDownloader:
    def download(self, bvid: str) -> Path:
        raise PipelineUnavailable("download", "download dependency is not configured")


StageObserver = Callable[[str, str], None]


class Pipeline:
    def __init__(
        self,
        downloader: Downloader | None = None,
        transcriber: Transcriber | None = None,
        frame_extractor: FrameExtractor | None = None,
        compiler: SkillCompiler | None = None,
        validator: SkillValidator | None = None,
    ):
        self.downloader = downloader or UnavailableDownloader()
        self.transcriber = transcriber
        self.frame_extractor = frame_extractor
        self.compiler = compiler
        self.validator = validator

    def run(self, bvid: str, observe: StageObserver | None = None) -> dict[str, Any]:
        video = self._run_stage("download", lambda: self.downloader.download(bvid), observe)
        transcript = self._run_stage("transcribe", lambda: self._required("transcribe", self.transcriber).transcribe(video), observe)
        frames = self._run_stage("frames", lambda: self._required("frames", self.frame_extractor).extract(video), observe)
        skill = self._run_stage("compile", lambda: self._required("compile", self.compiler).compile(transcript, frames), observe)
        self._run_stage("validate", lambda: self._required("validate", self.validator).validate(skill), observe)
        return skill

    @staticmethod
    def _required(stage: str, dependency: Any) -> Any:
        if dependency is None:
            raise PipelineUnavailable(stage, f"{stage} dependency is not configured")
        return dependency

    @staticmethod
    def _run_stage(stage: str, action: Callable[[], Any], observe: StageObserver | None) -> Any:
        if observe:
            observe(stage, "running")
        result = action()
        if observe:
            observe(stage, "completed")
        return result
