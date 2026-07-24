from fastapi.testclient import TestClient

from src.backend.app import TARGET_BVID, app


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

