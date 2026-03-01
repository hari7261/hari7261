#!/usr/bin/env python3
"""Generate a transparent SVG graph of language usage across GitHub repos."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from xml.sax.saxutils import escape


API_BASE = "https://api.github.com"
UA = "hari7261-language-graph-generator"


LANGUAGE_COLORS = {
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Python": "#3572A5",
    "Go": "#00ADD8",
    "Java": "#b07219",
    "C++": "#f34b7d",
    "C": "#555555",
    "C#": "#178600",
    "PHP": "#4F5D95",
    "Ruby": "#701516",
    "Rust": "#dea584",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
    "Dart": "#00B4AB",
    "Shell": "#89e051",
    "PowerShell": "#012456",
    "Jupyter Notebook": "#DA5B0B",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "SCSS": "#c6538c",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate GitHub language usage graph")
    parser.add_argument("--username", required=True, help="GitHub username")
    parser.add_argument("--output-svg", required=True, help="Output SVG path")
    parser.add_argument("--output-json", required=True, help="Output JSON summary path")
    parser.add_argument("--max-languages", type=int, default=12, help="Max languages to show")
    parser.add_argument(
        "--exclude-forks",
        action="store_true",
        help="Exclude forked repositories from aggregation",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived repositories",
    )
    return parser.parse_args()


def github_get(url: str, token: str | None) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": UA,
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"GitHub API error {err.code} for {url}: {body}") from err


def list_owner_repos(
    username: str,
    token: str | None,
    exclude_forks: bool,
    include_archived: bool,
) -> List[dict]:
    repos: List[dict] = []

    if token:
        # Authenticated mode can include private repos owned by the token owner.
        base = f"{API_BASE}/user/repos"
        common = {
            "affiliation": "owner",
            "visibility": "all",
            "sort": "updated",
            "per_page": 100,
        }
    else:
        # Unauthenticated mode only sees public repos.
        base = f"{API_BASE}/users/{urllib.parse.quote(username)}/repos"
        common = {
            "type": "owner",
            "sort": "updated",
            "per_page": 100,
        }

    page = 1
    while True:
        params = dict(common)
        params["page"] = page
        url = f"{base}?{urllib.parse.urlencode(params)}"
        batch = github_get(url, token)
        if not isinstance(batch, list):
            raise RuntimeError(f"Unexpected repo list payload type: {type(batch)}")
        if not batch:
            break
        repos.extend(batch)
        page += 1

    filtered: List[dict] = []
    for repo in repos:
        owner = (repo.get("owner") or {}).get("login")
        if owner and owner.lower() != username.lower():
            continue
        if exclude_forks and repo.get("fork"):
            continue
        if not include_archived and repo.get("archived"):
            continue
        filtered.append(repo)
    return filtered


def accumulate_languages(repos: Iterable[dict], token: str | None) -> Tuple[Dict[str, int], int]:
    totals: Dict[str, int] = defaultdict(int)
    used_repo_count = 0

    for repo in repos:
        languages_url = repo.get("languages_url")
        if not languages_url:
            continue
        lang_data = github_get(languages_url, token)
        if not isinstance(lang_data, dict):
            continue
        repo_has_language = False
        for language, byte_count in lang_data.items():
            try:
                value = int(byte_count)
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            totals[language] += value
            repo_has_language = True
        if repo_has_language:
            used_repo_count += 1
    return dict(totals), used_repo_count


def fallback_color(language: str) -> str:
    h = int(hashlib.md5(language.encode("utf-8")).hexdigest()[:8], 16) % 360
    return f"hsl({h}, 70%, 52%)"


def pick_color(language: str) -> str:
    return LANGUAGE_COLORS.get(language, fallback_color(language))


def format_bytes(num: int) -> str:
    value = float(num)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num} B"


def build_svg(
    username: str,
    language_rows: List[Tuple[str, int, float]],
    repo_count_used: int,
    total_bytes: int,
    generated_at: str,
) -> str:
    width = 1100
    left = 260
    right_text = 790
    bar_width_max = 500
    row_h = 22
    row_gap = 14
    top = 130
    height = top + len(language_rows) * (row_h + row_gap) + 80

    lines: List[str] = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">')
    lines.append("  <title id=\"title\">Most used languages across GitHub repositories</title>")
    lines.append("  <desc id=\"desc\">Transparent horizontal bar chart generated from GitHub repository language byte counts.</desc>")
    lines.append("  <style>")
    lines.append("    :root { --text: #111827; --muted: #4b5563; --axis: #9ca3af; }")
    lines.append("    @media (prefers-color-scheme: dark) { :root { --text: #e5e7eb; --muted: #9ca3af; --axis: #6b7280; } }")
    lines.append("    text { font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; }")
    lines.append("    .title { fill: var(--text); font-size: 28px; font-weight: 700; }")
    lines.append("    .subtitle { fill: var(--muted); font-size: 15px; }")
    lines.append("    .label { fill: var(--text); font-size: 16px; font-weight: 600; }")
    lines.append("    .value { fill: var(--muted); font-size: 14px; }")
    lines.append("  </style>")

    lines.append(f'  <text x="20" y="42" class="title">Most Used Languages - {escape(username)}</text>')
    lines.append(
        f'  <text x="20" y="70" class="subtitle">Aggregated by GitHub language bytes across {repo_count_used} repositories | Total: {escape(format_bytes(total_bytes))}</text>'
    )
    lines.append(f'  <text x="20" y="92" class="subtitle">Generated: {escape(generated_at)} UTC | Background: transparent</text>')

    for i, (language, byte_count, pct) in enumerate(language_rows):
        y = top + i * (row_h + row_gap)
        bar_w = max(2, round((pct / 100.0) * bar_width_max))
        color = pick_color(language)
        label = escape(language)
        value_label = escape(f"{pct:.2f}% ({format_bytes(byte_count)})")

        lines.append(f'  <text x="20" y="{y + 16}" class="label">{label}</text>')
        lines.append(
            f'  <rect x="{left}" y="{y}" width="{bar_width_max}" height="{row_h}" rx="11" fill="none" stroke="var(--axis)" stroke-opacity="0.45" />'
        )
        lines.append(
            f'  <rect x="{left}" y="{y}" width="{bar_w}" height="{row_h}" rx="11" fill="{color}" />'
        )
        lines.append(f'  <text x="{right_text}" y="{y + 16}" class="value">{value_label}</text>')

    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")

    repos = list_owner_repos(
        username=args.username,
        token=token,
        exclude_forks=args.exclude_forks,
        include_archived=args.include_archived,
    )
    if not repos:
        raise RuntimeError("No repositories found to aggregate.")

    totals, repo_count_used = accumulate_languages(repos, token)
    if not totals:
        raise RuntimeError("No language data returned by GitHub for selected repositories.")

    total_bytes = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    rows = [(lang, count, (count / total_bytes) * 100.0) for lang, count in ranked[: args.max_languages]]

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    svg = build_svg(
        username=args.username,
        language_rows=rows,
        repo_count_used=repo_count_used,
        total_bytes=total_bytes,
        generated_at=timestamp,
    )

    summary = {
        "username": args.username,
        "generated_at_utc": timestamp,
        "token_used": bool(token),
        "repo_count_scanned": len(repos),
        "repo_count_with_languages": repo_count_used,
        "exclude_forks": bool(args.exclude_forks),
        "include_archived": bool(args.include_archived),
        "total_bytes": total_bytes,
        "languages": [
            {"language": lang, "bytes": count, "percent": round(pct, 6)}
            for lang, count, pct in rows
        ],
    }

    output_svg = Path(args.output_svg)
    output_json = Path(args.output_json)
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    output_svg.write_text(svg, encoding="utf-8")
    output_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(
        f"Generated {output_svg} and {output_json} using {len(repos)} repos ({repo_count_used} with language data)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
