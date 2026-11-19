import json
from pathlib import Path
from typing import Any


def load_hospital_snapshot(filepath: str = "data/hospital_snapshot.json") -> dict[str, Any]:
    """Load the latest hospital operational snapshot from JSON."""
    path = Path(filepath)
    if not path.exists():
        return {"error": f"Snapshot file not found at {filepath}"}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def analyze_capacity_and_staffing(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Calculate bed occupancy rates, staffing deficits, and missing fields per unit."""
    units = snapshot.get("units", [])
    unit_reports = []
    missing_fields = []

    for u in units:
        name = u.get("unit_name", "Unknown")
        total = u.get("total_beds")
        occupied = u.get("occupied_beds")
        n_duty = u.get("nurses_on_duty")
        n_req = u.get("nurses_required")

        occ_rate = round((occupied / total) * 100, 1) if total else None
        open_beds = (total - occupied) if (total is not None and occupied is not None) else None
        nurse_gap = (n_req - n_duty) if (n_req is not None and n_duty is not None) else None

        if u.get("discharge_eta_hours") is None and name != "ICU":
            missing_fields.append(f"{name}: discharge_eta_hours is missing/null")

        unit_reports.append({
            "unit": name,
            "occupancy_pct": occ_rate,
            "open_beds": open_beds,
            "nurse_deficit": nurse_gap,
            "discharge_ready": u.get("discharge_ready_patients", 0),
            "pending_step_down": u.get("pending_step_down_transfers", 0),
        })

    return {
        "ed_incoming_per_hour": snapshot.get("ed_incoming_per_hour"),
        "ed_waiting_patients": snapshot.get("ed_waiting_patients"),
        "unit_reports": unit_reports,
        "missing_data_flags": missing_fields,
    }


def simulate_surge_and_discharge(
    snapshot: dict[str, Any],
    extra_admissions_next_4h: int = 12,
    expedited_discharges_next_4h: int = 6,
) -> dict[str, Any]:
    """Simulate a 4-hour admission surge combined with expedited discharges."""
    total_open_beds = sum(
        max(0, u.get("total_beds", 0) - u.get("occupied_beds", 0))
        for u in snapshot.get("units", [])
    )
    projected_net_change = extra_admissions_next_4h - expedited_discharges_next_4h
    projected_shortfall = max(0, projected_net_change - total_open_beds)

    return {
        "current_open_beds_all_units": total_open_beds,
        "extra_admissions_4h": extra_admissions_next_4h,
        "expedited_discharges_4h": expedited_discharges_next_4h,
        "projected_bed_shortfall_4h": projected_shortfall,
        "status": "CRITICAL_SHORTFALL" if projected_shortfall > 0 else "MANAGED_WITH_BUFFER",
    }