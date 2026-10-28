import os
import re
import sys
import json
import time
from datetime import datetime, timezone
import requests
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
API_BASE = "https://api.spiget.org/v2"
SITE = "https://www.spigotmc.org"
CACHE_FILE = "last_versions.json"
LIST_FILE = "resources.txt"
HEADERS = {"User-Agent": "Spigot-Check-Bot/1.0.0 (GitHub Actions)"}
def http_get_json(url, params=None, retries=3):
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code == 404:
                return {}
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            print(f"Attempt {attempt}/{retries} ({url}): {e}")
            time.sleep(2 * attempt)
    return None
def load_ids():
    ids = []
    try:
        with open(LIST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                # ID seul, ou URL du type .../resources/nom.12345/
                m = re.fullmatch(r"\d+", line) or re.search(r"\.(\d+)(?:/|$|\?)", line) or re.search(r"/resources/(\d+)", line)
                if m:
                    rid = m.group(1) if m.lastindex else m.group(0)
                    if rid not in ids:
                        ids.append(rid)
                else:
                    print(f"Ligne ignorée (ID introuvable) : {line}")
    except FileNotFoundError:
        print(f"{LIST_FILE} introuvable.")
    return ids
def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
        f.write("\n")
def build_embed(res, ver):
    rid = res["id"]
    name = res.get("name", f"Resource {rid}")
    tested = res.get("testedVersions") or []
    fields = [
        {"name": "🆔 Version", "value": f"`{ver.get('name', '?')}`", "inline": True},
        {"name": "📦 Version Minecraft", "value": f"`{', '.join(tested[-4:]) or 'N/A'}`", "inline": True},
        {"name": "⬇️ Download", "value": f"[Spigot]({SITE}/resources/{rid}/download?version={ver['id']})", "inline": False},
    ]
    embed = {
        "title": f"🟢 {name.upper()} - New Version Detected",
        "url": f"{SITE}/resources/{rid}/updates",
        "color": 15844367,
        "fields": fields,
        "footer": {"text": "Plugin Update Checker - Automatic via GitHub"},
    }
    if res.get("tag"):
        embed["description"] = res["tag"][:200]
    icon = (res.get("icon") or {}).get("url")
    if icon:
        embed["thumbnail"] = {"url": f"{SITE}/{icon.lstrip('/')}"}
    ts = ver.get("releaseDate")
    if ts:
        embed["timestamp"] = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    return embed
def send_discord(embed):
    if DRY_RUN:
        print(json.dumps(embed, indent=2, ensure_ascii=False))
        return True
    for _ in range(3):
        try:
            res = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)
        except requests.RequestException as e:
            print(f"Discord network error : {e}")
            time.sleep(2)
            continue
        if res.status_code == 429:
            time.sleep(float(res.json().get("retry_after", 2)))
            continue
        if res.status_code < 400:
            return True
        print(f"Discord failure : {res.status_code} - {res.text}")
        return False
    return False
def main():
    if not WEBHOOK_URL and not DRY_RUN:
        print("Error: DISCORD_WEBHOOK is missing.")
        sys.exit(1)
    ids = load_ids()
    if not ids:
        print("Aucun ID dans resources.txt.")
        sys.exit(1)
    cache = load_cache()
    first_run = not cache
    failures = 0
    for rid in ids:
        ver = http_get_json(f"{API_BASE}/resources/{rid}/versions/latest")
        if ver is None:
            failures += 1
            continue
        if not ver:
            print(f"{rid}: no version found.")
            continue
        known = cache.get(rid)
        print(f"{rid} | API: {ver.get('name')} ({ver['id']}) | Cache: {known or '-'}")
        if known == str(ver["id"]):
            continue
        if first_run or known is None:
            cache[rid] = str(ver["id"])
            continue
        res = http_get_json(f"{API_BASE}/resources/{rid}")
        if not res:
            failures += 1
            continue
        if send_discord(build_embed(res, ver)):
            cache[rid] = str(ver["id"])
            print(f"Notification sent for {rid} {ver.get('name')}.")
        else:
            print(f"Send failed for {rid}: will retry on the next run.")
            failures += 1
        time.sleep(0.5)
    if not DRY_RUN:
        save_cache(cache)
    if failures:
        sys.exit(1)
if __name__ == "__main__":
    main()
