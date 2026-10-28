"""Jobs for sandbox tests. Imported inside spawned worker processes."""

from __future__ import annotations

import os
import time


def echo(x):
    return x


def sleep_forever(_=None):
    time.sleep(3600)


def crash_hard(_=None):
    os._exit(139)  # simulates a native-library segfault


def raise_typed(_=None):
    from app.errors import TextTooLargeError

    raise TextTooLargeError("too big")


def raise_unexpected(_=None):
    raise RuntimeError("secret document text must not leak")


def allocate(mb):
    blob = bytearray(mb * 1024 * 1024)  # noqa: F841
    return "allocated"


def getpid(_=None):
    return os.getpid()
