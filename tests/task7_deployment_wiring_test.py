from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_includes_phase1_worker_and_rabbitmq_wiring():
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "rabbitmq:" in compose_text
    assert "container_name: threatrag-rabbitmq" in compose_text
    assert "threatrag-worker:" in compose_text
    assert "dockerfile: Dockerfile.worker" in compose_text
    assert "container_name: threatrag-worker" in compose_text
    assert "RABBITMQ_URL=" in compose_text
