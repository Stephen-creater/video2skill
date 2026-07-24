from fastapi.testclient import TestClient

from src.backend.app import TARGET_BVID, app
from src.backend.pipeline import JobContext, Pipeline, PipelineUnavailable


client = TestClient(app)


def test_fixed_skill_has_four_objective_steps():
    response = client.get(f"/v1/skills/{TARGET_BVID}")
    assert response.status_code == 200
    skill = response.json()
    assert skill["bvid"] == TARGET_BVID
    assert len(skill["steps"]) == 4
    assert {step["type"] for step in skill["steps"]} == {"single_choice", "true_false"}
    for step in skill["steps"]:
        assert 2 <= len(step["options"]) <= 4
        assert step["correctOptionId"] in {option["id"] for option in step["options"]}
        assert step["question"]
        assert step["evidence"]["audio"]
        assert step["evidence"]["visual"]
        assert 0 <= step["videoSeconds"] <= 1937


def test_unknown_video_is_rejected():
    response = client.post("/v1/compile", json={"bvid": "BV0000000000"})
    assert response.status_code == 422


def test_backend_allows_extension_cors():
    response = client.get(
        f"/v1/skills/{TARGET_BVID}",
        headers={"Origin": "chrome-extension://test-extension"},
    )
    assert response.headers["access-control-allow-origin"] == "chrome-extension://test-extension"


def test_compile_returns_real_job_status(monkeypatch):
    from src.backend import app as app_module

    monkeypatch.setattr(app_module, "start_job", lambda job_id: None)
    response = client.post("/v1/compile", json={"bvid": TARGET_BVID})
    assert response.status_code == 202
    job_id = response.json()["jobId"]
    status = client.get(f"/v1/jobs/{job_id}")
    assert status.status_code == 200
    assert set(status.json()["stages"]) == {
        "download",
        "transcribe",
        "frames",
        "compile",
        "validate",
    }


def test_regeneration_does_not_overwrite_reviewed_skill(monkeypatch, tmp_path):
    from src.backend import app as app_module

    reviewed_path = tmp_path / "reviewed.json"
    reviewed_path.write_text('{"reviewed": true}', encoding="utf-8")
    monkeypatch.setattr(app_module, "SKILL_PATH", reviewed_path)
    reviewed = reviewed_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        app_module.pipeline,
        "run",
        lambda *_args, **_kwargs: {"bvid": TARGET_BVID, "title": "unreviewed", "steps": []},
    )
    monkeypatch.setattr(app_module, "WORK_ROOT", tmp_path)
    job_id, _ = app_module.new_job()
    app_module.run_job(job_id)

    assert reviewed_path.read_text(encoding="utf-8") == reviewed
    assert app_module.jobs[job_id]["status"] == "completed"


def test_fixed_skill_has_the_requested_frontend_topics():
    skill = client.get(f"/v1/skills/{TARGET_BVID}").json()
    expected = ["HTML", "图片", "CSS", "按钮"]
    for step, label in zip(skill["steps"], expected):
        assert label in step["title"]
        assert step["hint"]
        assert step["failureExplanation"]


def test_default_pipeline_reports_a_missing_mlx_dependency_at_transcribe_stage(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def import_without_mlx(name, *args, **kwargs):
        if name == "mlx_whisper":
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_mlx)

    class LocalVideo:
        def download(self, bvid, context):
            return tmp_path / "video.mp4"

    pipeline = Pipeline(downloader=LocalVideo())
    try:
        pipeline.run(TARGET_BVID, JobContext(TARGET_BVID, "missing-mlx", tmp_path / "work"))
    except PipelineUnavailable as error:
        assert error.stage == "transcribe"
        assert "mlx-whisper" in str(error)
    else:
        raise AssertionError("the pipeline must report the missing MLX dependency")
