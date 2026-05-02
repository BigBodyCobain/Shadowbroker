"""Shared pytest fixtures for the infonet economy test suite.

The repo-level ``backend/tests/conftest.py`` patches scheduler/stream
services on every test — those patches are only relevant when the FastAPI
app is loaded. The infonet package tests are pure-Python unit tests
that never touch ``main.app`` so we don't import that conftest's
fixtures here.

The only shared fixture is a CONFIG reset, so a test that simulates a
governance petition execution cannot leak state into the next test.
"""

from __future__ import annotations

import pytest

from services.infonet.config import reset_config_for_tests


@pytest.fixture(autouse=True)
def _reset_infonet_config():
    reset_config_for_tests()
    yield
    reset_config_for_tests()
