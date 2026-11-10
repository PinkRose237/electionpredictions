"""Build the static contact directory. Run daily; no credentials required.

Only public office contact information is copied. Addresses entered by visitors
never reach this script. Archives are read in memory, never extracted to disk.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import io
import json
from pathlib import Path
import re
import tarfile

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "congress": "https://github.com/unitedstates/congress-legislators",
    "openstates": "https://github.com/openstates/people",
    "civicpatch": "https://github.com/CivicPatch/open-data",
}


def fetch(url):
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content


def strings(values):
    return list(dict.fromkeys(str(v).strip() for v in values if v and str(v).strip()))


def current(role, today):
    # Year/month-only dates are uncertain: retain through that period and show
    # the source date in the UI, rather than inventing an exact departure date.
    start = str(role.get("start_date") or role.get("start") or "")
    end = str(role.get("end_date") or role.get("end") or "")
    return (not start or start <= today) and (not end or end >= today[:len(end)])


def yaml_members(content):
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            if member.isfile() and member.name.endswith((".yml", ".yaml")) and "/data/" in member.name:
                yield member.name.split("/data/", 1)[1], yaml.safe_load(archive.extractfile(member))


def state_records(content, today):
    for path, person in yaml_members(content):
        parts = path.split("/")
        if len(parts) != 3 or parts[1] not in {"legislature", "executive"} or parts[0] == "us":
            continue
        if not isinstance(person, dict):
            continue
        for role in person.get("roles", []):
            if not current(role, today):
                continue
            kind = role.get("type", "")
            jurisdiction = role.get("jurisdiction", "").replace("ocd-jurisdiction/", "ocd-division/").removesuffix("/government")
            district = str(role.get("district", ""))
            division = jurisdiction
            if kind in {"upper", "lower"}:
                division += f"/sld{'u' if kind == 'upper' else 'l'}:{district.lower()}"
            label = {"upper": "State senator", "lower": "State representative", "governor": "Governor", "lt_governor": "Lieutenant governor", "attorney_general": "Attorney general", "secretary_of_state": "Secretary of state"}.get(kind, kind.replace("_", " ").capitalize())
            yield parts[0], dict(
                id=person["id"], name=person["name"], aliases=strings(n.get("name") for n in person.get("other_names", [])),
                office=label + (f" · District {district}" if district else ""),
                division=division, jurisdiction=jurisdiction, level="state", kind=kind,
                emails=strings([person.get("email")]), phones=strings(o.get("voice") for o in person.get("offices", [])),
                urls=strings(l.get("url") for l in person.get("links", [])),
                source=SOURCES["openstates"] + "/blob/main/data/" + path,
                start=str(role.get("start_date") or ""), end=str(role.get("end_date") or ""),
            )


def local_records(content, today):
    for path, people in yaml_members(content):
        parts = path.split("/")
        if len(parts) < 3 or not isinstance(people, list):
            continue
        for person in people:
            # CivicPatch has used both office and roles schemas.
            roles = person.get("roles") or ([person["office"]] if person.get("office") else [])
            for role in roles:
                if not current(role, today):
                    continue
                jurisdiction = (role.get("jurisdiction_ocdid") or person.get("jurisdiction_ocdid") or "").replace("ocd-jurisdiction/", "ocd-division/").removesuffix("/government")
                division = role.get("division_ocdid") or jurisdiction
                if not jurisdiction or not division:
                    continue
                yield parts[0], dict(
                    id="civicpatch/" + str(person.get("id", path + person["name"])),
                    name=person["name"], aliases=strings(n.get("name") if isinstance(n, dict) else n for n in person.get("other_names", [])),
                    office=role.get("name") or "Local official", division=division, jurisdiction=jurisdiction,
                    level="county" if "/county:" in jurisdiction else "local", kind="local",
                    emails=strings(person.get("emails", [])), phones=strings(person.get("phones", [])), urls=strings(person.get("urls", [])),
                    source=SOURCES["civicpatch"] + "/blob/main/data/" + path,
                    checked=str(person.get("updated_at") or "")[:10],
                    start=str(role.get("start_date") or ""), end=str(role.get("end_date") or ""),
                )


def congress_records(content, today, executive=False):
    for person in yaml.safe_load(content):
        for term in person.get("terms", []):
            if not current(term, today):
                continue
            kind = term["type"]
            if kind not in {"sen", "rep", "prez", "viceprez"}:
                continue
            state = str(term.get("state", "us")).lower()
            division = "ocd-division/country:us" + (f"/state:{state}" if state != "us" else "")
            if kind == "rep":
                division += f"/cd:{term.get('district', 0)}"
            name = person["name"]
            urls = [term.get("url")]
            contact_form = term.get("contact_form")
            if executive:
                urls = ["https://www.whitehouse.gov/"]
                contact_form = "https://www.whitehouse.gov/contact/"
            yield state, dict(
                id=person["id"].get("bioguide") or person["id"].get("govtrack"),
                name=name.get("official_full") or " ".join(name.get(k, "") for k in ["first", "middle", "last", "suffix"]).replace("  ", " ").strip(),
                office={"sen": "U.S. senator", "rep": "U.S. representative", "prez": "President", "viceprez": "Vice president"}[kind],
                division=division, jurisdiction=division.split("/cd:")[0], level="federal", kind=kind,
                emails=strings([term.get("email")]), phones=strings([term.get("phone")]), urls=strings(urls),
                contact_form=contact_form,
                source=SOURCES["congress"] + ("/blob/main/executive.yaml" if executive else "/blob/main/legislators-current.yaml"),
                start=str(term.get("start") or ""), end=str(term.get("end") or ""),
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "site" / "representatives-data")
    parser.add_argument("--openstates-archive", type=Path)
    parser.add_argument("--civicpatch-archive", type=Path)
    args = parser.parse_args()
    today = date.today().isoformat()
    states = defaultdict(list)
    for key, url in [("openstates", "https://github.com/openstates/people/archive/refs/heads/main.tar.gz"), ("civicpatch", "https://github.com/CivicPatch/open-data/archive/refs/heads/main.tar.gz")]:
        local = getattr(args, key + "_archive")
        content = local.read_bytes() if local else fetch(url)
        transform = state_records if key == "openstates" else local_records
        source_count = 0
        for state, record in transform(content, today):
            if re.fullmatch(r"[a-z]{2}", state):
                states[state].append(record)
                source_count += 1
        if source_count < (6000 if key == "openstates" else 1000):
            raise RuntimeError(f"Incomplete {key} source; leaving the existing directory untouched")
    for filename in ["legislators-current.yaml", "executive.yaml"]:
        content = fetch(f"https://raw.githubusercontent.com/unitedstates/congress-legislators/main/{filename}")
        source_count = 0
        for state, record in congress_records(content, today, filename == "executive.yaml"):
            states[state].append(record)
            source_count += 1
        if source_count < (400 if filename == "legislators-current.yaml" else 2):
            raise RuntimeError(f"Incomplete {filename} source; leaving the existing directory untouched")
    if len(states) < 50 or sum(len(v) for v in states.values()) < 7000:
        raise RuntimeError("Incomplete source download; leaving the existing directory untouched")
    args.output.mkdir(parents=True, exist_ok=True)
    # Stable ordering makes refresh diffs reviewable. Publish only after every source succeeded.
    counts = {}
    for state, records in sorted(states.items()):
        records.sort(key=lambda r: (r["jurisdiction"], r["name"], r["office"]))
        (args.output / f"{state}.json").write_text(json.dumps(records, ensure_ascii=False, separators=(",", ":")) + "\n")
        counts[state] = len(records)
    manifest = dict(updated=today, sources=SOURCES, states=counts, license="CC0 / public domain; see source repositories")
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Exported {sum(counts.values()):,} public-office records across {len(counts)} files")


if __name__ == "__main__":
    main()
