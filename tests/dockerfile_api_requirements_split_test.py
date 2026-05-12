from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _requirement_names(text: str) -> set[str]:
    names: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        name = line.split(">=", 1)[0].split("==", 1)[0].split("[", 1)[0].strip()
        names.add(name)
    return names


def test_api_dockerfile_uses_runtime_requirements_file():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY requirements-api.txt ." in dockerfile
    assert "uv pip install --system -r requirements-api.txt" in dockerfile


def test_requirements_are_split_between_runtime_and_research_sets():
    umbrella = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    runtime = (ROOT / "requirements-api.txt").read_text(encoding="utf-8")
    research = (ROOT / "requirements-research.txt").read_text(encoding="utf-8")

    assert "-r requirements-api.txt" in umbrella
    assert "-r requirements-research.txt" in umbrella

    runtime_names = _requirement_names(runtime)
    research_names = _requirement_names(research)

    assert {"peft", "accelerate", "datasets", "gym"} <= research_names
    assert runtime_names.isdisjoint({"peft", "accelerate", "datasets", "gym"})


def test_api_runtime_requirements_exclude_unused_heavy_packages():
    runtime = (ROOT / "requirements-api.txt").read_text(encoding="utf-8")
    runtime_names = _requirement_names(runtime)

    assert "chromadb" not in runtime_names
    assert "faiss-cpu" not in runtime_names
    assert "FlagEmbedding" not in runtime_names
    assert "torch" not in runtime_names
    assert "transformers" not in runtime_names
    assert "sentence-transformers" not in runtime_names


def test_dockerignore_excludes_large_runtime_mounted_directories():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    normalized = {line.strip() for line in dockerignore if line.strip() and not line.strip().startswith("#")}

    assert "models" in normalized or "models/" in normalized
    assert "data" in normalized or "data/" in normalized
