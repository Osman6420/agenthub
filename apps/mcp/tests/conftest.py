from __future__ import annotations

import pytest

from apps.gateway.tests.conftest import Fixture, build_scenario


@pytest.fixture
def scenario_fixture(db: object) -> Fixture:
    return build_scenario()
