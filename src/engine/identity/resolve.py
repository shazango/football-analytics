"""Deterministic identity resolution (PHASE-0-BRIEF.md §5, build order step 4).

Only exact name + date-of-birth matching. No fuzzy matching, no confirmation
UI — anything that isn't an unambiguous exact match goes to
`unresolved_alias` and is reported at the end of the run, per brief.

This resolves a *second* source's reference to our canonical `person.id`
(itself just the StatsBomb player_id, reused directly — see schema.py). If a
future source turns out to share StatsBomb's own ID numbering (e.g. a
co-branded release), that's a direct `person.id` lookup with no matching
needed at all — this module is for sources that don't.
"""

from datetime import date


def resolve_person(
    con, source: str, source_ref: str, display_name: str, dob: date | None = None
) -> int | None:
    """Resolve one external (source, source_ref) to a person_id, or None if
    ambiguous/unmatched (recorded in unresolved_alias). Idempotent."""
    existing = con.execute(
        "select person_id from person_alias where source = ? and source_ref = ?",
        [source, source_ref],
    ).fetchone()
    if existing:
        return existing[0]

    if dob is not None:
        matches = con.execute(
            "select id from person where lower(canonical_name) = lower(?) and dob = ?",
            [display_name, dob],
        ).fetchall()
    else:
        matches = con.execute(
            "select id from person where lower(canonical_name) = lower(?)",
            [display_name],
        ).fetchall()

    if len(matches) == 1:
        person_id = matches[0][0]
        con.execute(
            "INSERT OR IGNORE INTO person_alias VALUES (?, ?, ?, ?, ?, ?)",
            [person_id, source, source_ref, display_name, 1.0, None],
        )
        con.execute(
            "DELETE FROM unresolved_alias WHERE source = ? AND source_ref = ?",
            [source, source_ref],
        )
        return person_id

    reason = "no exact name/dob match" if not matches else f"{len(matches)} ambiguous matches"
    con.execute(
        "INSERT OR REPLACE INTO unresolved_alias VALUES (?, ?, ?, ?, now())",
        [source, source_ref, display_name, reason],
    )
    return None


def report_unresolved(con) -> list[tuple]:
    """Everything still parked in unresolved_alias. Call at the end of a
    resolution batch; print/log the result — brief requires unresolved
    aliases to be reported, not silently dropped."""
    return con.execute(
        "select source, source_ref, display_name, reason, detected_at "
        "from unresolved_alias order by source, source_ref"
    ).fetchall()
