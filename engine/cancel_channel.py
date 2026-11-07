"""Cancel a capture through standard input, for systems without SIGTERM.

Windows has no SIGTERM: Node's child.kill() and Python's send_signal() end the process at once, so
the engine cannot remove its staging folder or stop the workers and browsers it started. With
--cancel-on-stdin the parent writes the line "cancel" instead, or closes standard input (for example
when Obsidian quits), and the engine stops the way SIGTERM stops it on Linux and macOS.
"""
from __future__ import annotations

import os
import signal
import sys
import threading

_finished = threading.Event()


def listen(stream=None) -> threading.Thread:
    """Start the background reader. A "cancel" line or the end of input cancels the capture."""
    _finished.clear()
    thread = threading.Thread(target=_wait, args=(sys.stdin if stream is None else stream,),
                              name='web-obs-cancel', daemon=True)
    thread.start()
    return thread


def finish() -> None:
    """The capture has ended; input closing from now on is not a cancel."""
    _finished.set()


def finished() -> bool:
    return _finished.is_set()


def _wait(stream) -> None:
    if hasattr(signal, 'pthread_sigmask'):
        # Signals must reach the main thread, which blocks them while it swaps the capture folders.
        # A thread that does not block them would take them and run the handler mid-swap.
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        for line in stream:
            if line.strip() == 'cancel':
                break
    except (OSError, ValueError):
        pass
    if not _finished.is_set():
        _interrupt()


def _interrupt() -> None:
    if os.name == 'nt':
        # Raising SIGINT also wakes a main thread that is sleeping, which SIGTERM would not do there.
        signal.raise_signal(signal.SIGINT)
    else:
        # A signal sent to the process reaches the main thread, which a thread's own raise would not.
        os.kill(os.getpid(), signal.SIGTERM)
