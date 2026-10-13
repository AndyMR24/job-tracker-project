"""Explicit permission gate for future external operations."""
from __future__ import annotations


class PermissionDenied(PermissionError): pass


def require_external_approval(*, action: str, destination: str, data_summary: str, approved: bool) -> dict:
    if action == "submit_application":
        raise PermissionDenied("Application submission is always blocked; the user applies manually.")
    if not approved:
        raise PermissionDenied(f"Approval is required immediately before sending {data_summary} to {destination} for {action}.")
    return {"action": action, "destination": destination, "data_summary": data_summary, "approved": True}
