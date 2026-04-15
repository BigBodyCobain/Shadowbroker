from datetime import datetime
from services.data_fetcher import get_latest_data
from services.fetchers._store import source_timestamps, active_layers, source_freshness
from services.fetch_health import get_health_snapshot


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def main():
    data = get_latest_data()
    print("=== Diagnostics ===")
    print(f"Last updated: {_fmt_ts(data.get('last_updated'))}")
    print(
        f"Active layers: {sum(1 for v in active_layers.values() if v)} enabled / {len(active_layers)} total"
    )

    print("\n--- Source Timestamps ---")
    for k, v in sorted(source_timestamps.items()):
        print(f"{k:20} {_fmt_ts(v)}")

    print("\n--- Source Freshness ---")
    for k, v in sorted(source_freshness.items()):
        last_ok = _fmt_ts(v.get("last_ok"))
        last_err = _fmt_ts(v.get("last_error"))
        print(f"{k:20} ok={last_ok} err={last_err}")

    print("\n--- Fetch Health ---")
    health = get_health_snapshot()
    for k, v in sorted(health.items()):
        print(
            f"{k:20} ok={v.get('ok_count', 0)} err={v.get('error_count', 0)} "
            f"last_ok={_fmt_ts(v.get('last_ok'))} last_err={_fmt_ts(v.get('last_error'))} "
            f"avg_ms={v.get('avg_duration_ms')}"
        )


if __name__ == "__main__":
    main()
