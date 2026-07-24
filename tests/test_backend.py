from fastapi.testclient import TestClient

from src.backend.app import TARGET_BVID, app
from src.backend.pipeline import Pipeline, PipelineUnavailable


client = TestClient(app)


def test_fixed_skill_has_four_executable_steps():
    response = client.get(f"/v1/skills/{TARGET_BVID}")
    assert response.status_code == 200
    skill = response.json()
    assert skill["bvid"] == TARGET_BVID
    assert len(skill["steps"]) == 4
    for step in skill["steps"]:
        assert set(step["starter"]) == {"html", "css", "js"}
        assert step["tests"]
        assert step["evidence"]["audio"]
        assert step["evidence"]["visual"]
        assert 0 <= step["videoSeconds"] <= 1937


def test_unknown_video_is_rejected():
    response = client.post("/v1/compile", json={"bvid": "BV0000000000"})
    assert response.status_code == 422


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


def test_fixed_skill_has_the_requested_frontend_exercises():
    skill = client.get(f"/v1/skills/{TARGET_BVID}").json()
    expected = ["HTML", "图片", "CSS", "按钮"]
    for step, label in zip(skill["steps"], expected):
        assert label in step["title"]
        assert step["hint"]
        assert step["failureExplanation"]
        assert step["tests"][0]["framework"] == "jest"
        assert "expect(" in step["tests"][0]["code"]


def test_default_pipeline_reports_its_unavailable_dependency():
    pipeline = Pipeline()
    try:
        pipeline.run(TARGET_BVID)
    except PipelineUnavailable as error:
        assert error.stage == "download"
        assert "not configured" in str(error)
    else:
        raise AssertionError("the default pipeline must not claim a completed skill")
