#!/usr/bin/env python3
"""Life OS Garmin relay — runs on GitHub Actions, three times a day."""
import json, os, datetime, pathlib
from cryptography.fernet import Fernet
from garminconnect import Garmin

TOKEN_DIR = os.path.expanduser("~/.garmin_tokens")
DAYS = 7

def login():
    try:
        api = Garmin()
        api.login(TOKEN_DIR)
        print("login: token")
        return api
    except Exception as e:
        print("token login failed:", type(e).__name__)
    api = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
    api.login()
    pathlib.Path(TOKEN_DIR).mkdir(parents=True, exist_ok=True)
    api.garth.dump(TOKEN_DIR)
    print("login: password (token saved)")
    return api

def num(v):
    if isinstance(v, dict):
        v = v.get("qty") or v.get("value")
    return v

def main():
    api = login()
    today = datetime.date.today()
    out = {"pulled_at_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
           "days": {}, "activities": []}

    for i in range(DAYS):
        d = today - datetime.timedelta(days=i)
        ds = d.isoformat()
        day = {}
        try:
            st = api.get_stats(ds) or {}
            day.update({
                "steps": st.get("totalSteps"),
                "rhr": st.get("restingHeartRate"),
                "stress_avg": st.get("averageStressLevel"),
                "body_battery_high": st.get("bodyBatteryHighestValue"),
                "body_battery_low": st.get("bodyBatteryLowestValue"),
                "calories": st.get("totalKilocalories"),
                "intensity_minutes": (st.get("moderateIntensityMinutes") or 0)
                                     + 2 * (st.get("vigorousIntensityMinutes") or 0),
            })
        except Exception as e:
            day["stats_err"] = str(e)[:120]
        try:
            s = api.get_sleep_data(ds) or {}
            dto = s.get("dailySleepDTO") or {}
            secs = dto.get("sleepTimeSeconds")
            if secs:
                day["sleep_h"] = round(secs / 3600, 2)
                day["deep_h"] = round((dto.get("deepSleepSeconds") or 0) / 3600, 2)
                day["rem_h"] = round((dto.get("remSleepSeconds") or 0) / 3600, 2)
                day["awake_h"] = round((dto.get("awakeSleepSeconds") or 0) / 3600, 2)
                sc = (dto.get("sleepScores") or {}).get("overall") or {}
                day["sleep_score"] = sc.get("value")
        except Exception as e:
            day["sleep_err"] = str(e)[:120]
        out["days"][ds] = day

    try:
        start = (today - datetime.timedelta(days=DAYS)).isoformat()
        for a in api.get_activities_by_date(start, today.isoformat()) or []:
            out["activities"].append({
                "date": (a.get("startTimeLocal") or "")[:10],
                "type": (a.get("activityType") or {}).get("typeKey"),
                "name": a.get("activityName"),
                "duration_min": round((num(a.get("duration")) or 0) / 60, 1),
                "avg_hr": a.get("averageHR"),
                "calories": a.get("calories"),
                "distance_km": round((a.get("distance") or 0) / 1000, 2),
            })
    except Exception as e:
        out["activities_err"] = str(e)[:120]

    f = Fernet(os.environ["ENC_KEY"].encode())
    blob = f.encrypt(json.dumps(out).encode())
    data = pathlib.Path("data"); data.mkdir(exist_ok=True)
    (data / "latest.json.enc").write_bytes(blob)
    (data / "last_updated.txt").write_text(out["pulled_at_utc"] + "\n")
    print(f"wrote data/latest.json.enc — {len(out['days'])} days, {len(out['activities'])} activities")

if __name__ == "__main__":
    main()
