"""Decide what is allowed into the pool, and record why anything isn't.

Events are judged by their decklists, never by their names. Rejected events are
quarantined with a verdict, not deleted, and the combined pool is rebuilt from the
per-event files by one writer.
"""
