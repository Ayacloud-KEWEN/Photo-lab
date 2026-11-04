"""The process entry point."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from lumen.__main__ import _quiet_connection_resets


def test_connection_resets_are_not_logged_as_errors() -> None:
    loop = MagicMock(spec=asyncio.AbstractEventLoop)
    reset = {"message": "connection lost", "exception": ConnectionResetError(10054, "reset")}
    _quiet_connection_resets(loop, reset)
    loop.default_exception_handler.assert_not_called()

    other = {"message": "boom", "exception": ValueError("boom")}
    _quiet_connection_resets(loop, other)
    loop.default_exception_handler.assert_called_once_with(other)
