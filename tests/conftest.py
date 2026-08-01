from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pave_rec.domain import CandidateScore, RecommendationStateBuildRequest
from pave_rec.fixture import MockFixture, load_fixture
from pave_rec.recommendation_state.builder import (
    DefaultRecommendationStateBuilder,
    empty_evidence_state,
    empty_observation_state,
)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def mock_fixture(repo_root: Path) -> MockFixture:
    return load_fixture(
        repo_root / "tests/fixtures/mock/v1/scenario.json", expected_version="mock-v1"
    )


@pytest.fixture
def initial_state(mock_fixture: MockFixture):
    candidate_ids = mock_fixture.input.candidate_ids
    request = RecommendationStateBuildRequest(
        schema_version="1",
        run_id="mock-v1-golden",
        user_id=mock_fixture.input.user_id,
        user_memory=mock_fixture.user_memory,
        initial_ranking=mock_fixture.initial_ranking,
        current_scores=tuple(
            CandidateScore(item_id=entry.item_id, score=entry.score)
            for entry in mock_fixture.initial_ranking.candidates
        ),
        item_feature_refs=mock_fixture.item_feature_refs,
        segment_catalog=mock_fixture.segment_catalog,
        evidence_state=empty_evidence_state(candidate_ids),
        observation_state=empty_observation_state(candidate_ids, mock_fixture.segment_catalog),
        max_perception_actions=2,
        remaining_perception_actions=2,
        step=0,
        metadata={},
    )
    return DefaultRecommendationStateBuilder().build(request)


@pytest.fixture
def synthetic_project(tmp_path: Path, repo_root: Path) -> Path:
    root = tmp_path / "project"
    (root / "configs").mkdir(parents=True)
    (root / "tests/fixtures/mock/v1").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "synthetic-pave-rec"\nversion = "0.0.0"\n',
        encoding="utf-8",
        newline="\n",
    )
    shutil.copyfile(repo_root / "configs/base.yaml", root / "configs/base.yaml")
    shutil.copyfile(repo_root / "configs/mock.yaml", root / "configs/mock.yaml")
    shutil.copyfile(
        repo_root / "tests/fixtures/mock/v1/scenario.json",
        root / "tests/fixtures/mock/v1/scenario.json",
    )
    return root
