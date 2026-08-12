from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_post_setmotor_then_get_motor_returns_toto():
    post_response = client.post("/motor", json={"motorName": "toto"})
    assert post_response.status_code == 200

    get_response = client.get("/motor")
    assert get_response.status_code == 200
    assert get_response.json() == "toto"
