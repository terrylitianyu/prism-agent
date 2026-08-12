#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session context management using contextvars for multi-session concurrency.

Each request thread gets its own session via ContextVar, enabling
parallel processing of different sessions without a global lock.
"""

import contextvars
import threading

# The ContextVar — each thread/async context gets its own value
_session_var: contextvars.ContextVar = contextvars.ContextVar('_session_var')

# Per-session locks: {session_id: Lock}
_session_locks: dict = {}
_locks_lock = threading.Lock()


def set_current_session(session) -> None:
    """Set the session for the current execution context (thread)."""
    _session_var.set(session)


def get_current_session():
    """Get the session for the current execution context.

    Returns None if no session has been set in the current context.
    """
    try:
        return _session_var.get()
    except LookupError:
        return None


def get_session_lock(session_id: str) -> threading.Lock:
    """Get (or create) the per-session lock.

    Prevents two concurrent requests to the SAME session from racing,
    while allowing different sessions to proceed in parallel.
    """
    with _locks_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


def remove_session_lock(session_id: str) -> None:
    """Clean up lock when a session is deleted."""
    with _locks_lock:
        _session_locks.pop(session_id, None)