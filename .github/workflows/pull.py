#!/usr/bin/env python3
"""Life OS Garmin relay — with one-time MFA handling and encrypted token storage."""
import json, os, re, sys, time, datetime, pathlib, subprocess
from cryptography.fernet import Fernet
from garminconnect import Garmin

TOKEN_DIR = os.path.expanduser("~/.garmin_tokens")
TOK_ENC = pathlib.Path("data/garmin_tokens.enc")
DAYS = 7
FERNET = Fernet(os.environ["ENC_KEY"].encode())

def save_tokens():
    d = {p.name: p.read_text() for p in pathlib.Path(TOKEN_DIR).iterdir() if p.is_file()}
    TOK_ENC.parent.mkdir(exist_ok=True)
    TOK_ENC.write_bytes(FERNET.encrypt(json.dumps(d).encode()))
    print("tokens saved (encrypted) to repo")

def load_tokens():
    if not TOK_ENC.exists():
        return False
    d = json.loads(FERNET.decrypt(TOK_ENC.read_bytes()))
    pathlib.Path(TOKEN_DIR).mkdir(parents=True, exist_ok=True)
    for name, text in d.items():
        (pathlib.Path(TOKEN_DIR) / name).write_text(text)
    return True

def wait_for_mfa_code(timeout=600):
    print("MFA required. Garmin just emailed you a code.")
    print("On GitHub: Code tab -> Add file -> Create new file -> name it  mfa.txt")
    print("-> paste the code -> Commit. I'll check every 15 seconds for 10 minutes.")
    t0 = time.time()
    while time.time() - t0 < timeout:
        subprocess.run(["git", "pull", "-q"], check=False)
        p = pathlib.Path("mfa.txt")
        if p.exists():
            m = re.search(r"\d{4,8}", p.read_text())
            if m:
                print("code received")
                return m.group(0)
        time.sleep(15)
    sys.exit("No MFA code appeared within 10 minutes — run the workflow again.")

def login():
    if load_tokens():
        try:
            api = Garmin()
            api.login(TOKEN_DIR)
            print("login: saved token")
            return api
        except Exception as e:
            print("token login failed:", type(e).__name__)
    api = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"],
                 return_on_mfa=True)
    r1, r2 = api.login()
    if r1 == "needs_mfa":
        api.resume_login(r2, wait_for_mfa_code())
    pathlib.Path(TOKEN_DIR).mkdir(parents=True, exist_ok=True)
    api.client.dump(TOKEN_DIR)
    save_tokens()
    pathlib.Path("mfa.txt").unlink(missing_ok=True)
    print("login: password + MFA (token stored for future runs)")
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
        ds = (today - datetime.timedelta(days=i)).isoformat()
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
                day["sleep_score"] = ((dto.get("sleepScores") or {}).get("overall") or {}).get("value")
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
    data = pathlib.Path("data"); data.mkdir(exist_ok=True)
    (data / "latest.json.enc").write_bytes(FERNET.encrypt(json.dumps(out).encode()))
    (data / "last_updated.txt").write_text(out["pulled_at_utc"] + "\n")
    print(f"wrote data/latest.json.enc — {len(out['days'])} days, {len(out['activities'])} activities")

if __name__ == "__main__":
    main()
