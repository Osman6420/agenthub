from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.gateway.tests.conftest import Fixture, build_scenario
from apps.identity.models import Consumer, ConsumerBinding, ConsumerProtocol
from apps.identity.tokens import create_token


@dataclass
class McpFixture(Fixture):
    rest_consumer: Consumer
    rest_token: str


@pytest.fixture
def scenario_fixture(db: object) -> McpFixture:
    rest = build_scenario()
    mcp_consumer = Consumer.objects.create(
        organization=rest.organization,
        subject="svc-mcp",
        name="MCP Backend",
        protocol=ConsumerProtocol.MCP,
    )
    _, mcp_token = create_token(mcp_consumer, "test")
    ConsumerBinding.objects.create(
        consumer=mcp_consumer,
        scenario=rest.scenario,
        capabilities=list(rest.consumer.bindings.get().capabilities),
    )
    return McpFixture(
        organization=rest.organization,
        scenario=rest.scenario,
        alias=rest.alias,
        consumer=mcp_consumer,
        raw_token=mcp_token,
        rest_consumer=rest.consumer,
        rest_token=rest.raw_token,
    )
