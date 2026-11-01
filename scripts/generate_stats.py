#!/usr/bin/env python3
"""Generate neon-themed GitHub stats SVGs (stats, languages, activity) for a profile README.

Runs inside GitHub Actions with GITHUB_TOKEN, so the README never depends on
third-party image services. Output goes to ./assets/.
"""
import json, os, re, sys, urllib.request, urllib.error
from datetime import date, timedelta
from html import escape

USER = os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "karan-kharad"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = os.environ.get("OUT_DIR", "assets")

BG, PINK, CYAN, YEL, TXT, DIM = "#0d0221", "#ff2a6d", "#05d9e8", "#f9f002", "#e8e6ff", "#8b7ab8"
FONT = "'Courier New', Courier, monospace"


def http(url, data=None, accept="application/vnd.github+json"):
    headers = {"User-Agent": "profile-stats-generator", "Accept": accept}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def api(path):
    try:
        return json.loads(http("https://api.github.com" + path))
    except (urllib.error.URLError, ValueError) as e:
        print(f"warn: {path}: {e}", file=sys.stderr)
        return None


def total_count(query):
    d = api("/search/" + query)
    return (d or {}).get("total_count", 0)


# ---------------------------------------------------------------- data
def fetch_stats():
    u = api(f"/users/{USER}") or {}
    repos = api(f"/users/{USER}/repos?per_page=100&type=owner") or []
    stars = sum(r.get("stargazers_count", 0) for r in repos)
    langs = {}
    for r in repos:
        if r.get("fork"):
            continue
        d = api(f"/repos/{USER}/{r['name']}/languages") or {}
        for k, v in d.items():
            langs[k] = langs.get(k, 0) + v
    return {
        "name": u.get("name") or USER,
        "repos": u.get("public_repos", len(repos)),
        "followers": u.get("followers", 0),
        "stars": stars,
        "commits": total_count(f"commits?q=author:{USER}&per_page=1"),
        "prs": total_count(f"issues?q=author:{USER}+type:pr&per_page=1"),
        "issues": total_count(f"issues?q=author:{USER}+type:issue&per_page=1"),
        "langs": langs,
    }


def contributions_graphql():
    if not TOKEN:
        return None
    q = ("query($u:String!){user(login:$u){contributionsCollection{contributionCalendar{"
         "totalContributions weeks{contributionDays{date contributionCount}}}}}}")
    try:
        raw = http("https://api.github.com/graphql",
                   data=json.dumps({"query": q, "variables": {"u": USER}}).encode(),
                   accept="application/json")
        cal = json.loads(raw)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        days = {d["date"]: d["contributionCount"] for w in cal["weeks"] for d in w["contributionDays"]}
        return cal["totalContributions"], days
    except Exception as e:
        print(f"warn: graphql: {e}", file=sys.stderr)
        return None


def contributions_scrape():
    try:
        html = http(f"https://github.com/users/{USER}/contributions", accept="text/html")
    except Exception as e:
        print(f"warn: scrape: {e}", file=sys.stderr)
        return 0, {}
    ids = {}
    for m in re.finditer(r'<td[^>]*?data-date="([\d-]+)"[^>]*?id="([^"]+)"', html):
        ids[m.group(2)] = m.group(1)
    for m in re.finditer(r'<td[^>]*?id="([^"]+)"[^>]*?data-date="([\d-]+)"', html):
        ids[m.group(1)] = m.group(2)
    days = {}
    for m in re.finditer(r'<tool-tip[^>]*?for="([^"]+)"[^>]*>\s*([^<]*?)\s*</tool-tip>', html):
        d = ids.get(m.group(1))
        if not d:
            continue
        n = re.match(r"(\d+)", m.group(2))
        days[d] = int(n.group(1)) if n else 0
    return sum(days.values()), days


def fetch_contributions():
    return contributions_graphql() or contributions_scrape()


# ---------------------------------------------------------------- svg helpers
def frame(w, h, title, body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <defs><pattern id="sl" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="1" fill="#000" opacity="0.25"/></pattern></defs>
  <rect x="1" y="1" width="{w-2}" height="{h-2}" fill="{BG}" stroke="{PINK}" stroke-width="2"/>
  <text x="20" y="32" font-family="{FONT}" font-size="16" font-weight="700" fill="{YEL}">{escape(title)}</text>
  <line x1="20" y1="42" x2="{w-20}" y2="42" stroke="{CYAN}" stroke-opacity="0.5"/>
  {body}
  <rect x="1" y="1" width="{w-2}" height="{h-2}" fill="url(#sl)"/>
</svg>'''


def write(name, svg):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote", os.path.join(OUT, name))


def fmt(n):
    return f"{n:,}"


# ---------------------------------------------------------------- cards
def stats_card(s, year_total):
    rows = [("Total Stars", s["stars"]), ("Total Commits", s["commits"]),
            ("Total PRs", s["prs"]), ("Total Issues", s["issues"]),
            ("Public Repos", s["repos"]), ("Followers", s["followers"]),
            ("Contributions (1y)", year_total)]
    body = []
    for i, (k, v) in enumerate(rows):
        y = 70 + i * 26
        body.append(f'<rect x="22" y="{y-10}" width="8" height="8" fill="{PINK}"/>')
        body.append(f'<text x="40" y="{y}" font-family="{FONT}" font-size="14" fill="{CYAN}">{k}:</text>')
        body.append(f'<text x="380" y="{y}" text-anchor="end" font-family="{FONT}" font-size="14" font-weight="700" fill="{TXT}">{fmt(v)}</text>')
    return frame(400, 70 + len(rows) * 26 + 6, f"{s['name']}'s GitHub Stats", "\n  ".join(body))


def langs_card(langs):
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:6]
    colors = [CYAN, PINK, YEL, "#39ff14", "#b388ff", "#ff9e3d"]
    body = []
    if not top:
        body.append(f'<text x="20" y="80" font-family="{FONT}" font-size="14" fill="{DIM}">No language data yet</text>')
    for i, (k, v) in enumerate(top):
        y = 66 + i * 28
        pct = v / total * 100
        body.append(f'<text x="22" y="{y+10}" font-family="{FONT}" font-size="13" fill="{TXT}">{escape(k)}</text>')
        body.append(f'<text x="378" y="{y+10}" text-anchor="end" font-family="{FONT}" font-size="13" fill="{DIM}">{pct:.1f}%</text>')
        body.append(f'<rect x="130" y="{y}" width="190" height="10" fill="#1a0b3b"/>')
        body.append(f'<rect x="130" y="{y}" width="{max(2, 190*pct/100):.1f}" height="10" fill="{colors[i % len(colors)]}"/>')
    return frame(400, 70 + max(len(top), 1) * 28 + 6, "Top Languages", "\n  ".join(body))


def activity_card(days, total, span=30):
    end = date.today()
    series = [(end - timedelta(days=span - 1 - i)) for i in range(span)]
    vals = [days.get(d.isoformat(), 0) for d in series]
    W, H = 800, 260
    x0, x1, y0, y1 = 60, W - 30, 70, H - 50
    ymax = max(max(vals), 3)
    step = 1 if ymax <= 6 else (2 if ymax <= 12 else 5)
    ymax = ((ymax + step - 1) // step) * step
    px = lambda i: x0 + (x1 - x0) * i / (span - 1)
    py = lambda v: y1 - (y1 - y0) * v / ymax
    body = []
    for t in range(0, ymax + 1, step):
        y = py(t)
        body.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{CYAN}" stroke-opacity="0.18"/>')
        body.append(f'<text x="{x0-10}" y="{y+4:.1f}" text-anchor="end" font-family="{FONT}" font-size="11" fill="{DIM}">{t}</text>')
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(vals))
    body.append(f'<polygon points="{x0},{y1} {pts} {x1},{y1}" fill="{PINK}" fill-opacity="0.35"/>')
    body.append(f'<polyline points="{pts}" fill="none" stroke="{PINK}" stroke-width="2.5"/>')
    for i, v in enumerate(vals):
        body.append(f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="3" fill="{YEL}"/>')
        if i % 4 == 0 or i == span - 1:
            body.append(f'<text x="{px(i):.1f}" y="{y1+18}" text-anchor="middle" font-family="{FONT}" font-size="11" fill="{DIM}">{series[i].day}</text>')
    body.append(f'<text x="{(x0+x1)/2}" y="{H-12}" text-anchor="middle" font-family="{FONT}" font-size="11" fill="{DIM}">Days (last {span})</text>')
    return frame(W, H, f"{USER}'s Contribution Graph  ·  {fmt(total)} in the last year", "\n  ".join(body))


def main():
    s = fetch_stats()
    year_total, days = fetch_contributions()
    write("stats.svg", stats_card(s, year_total))
    write("languages.svg", langs_card(s["langs"]))
    write("activity.svg", activity_card(days, year_total))


if __name__ == "__main__":
    main()
