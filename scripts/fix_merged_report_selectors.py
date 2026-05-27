"""Fix merged report pages: sync filters from reports_* and correct misleading selectors."""
import json
from pathlib import Path
from urllib.parse import urlparse

SITE_MAP = Path(__file__).resolve().parents[1] / "site-map.json"
FILTER_SECTIONS = {"filters", "navigation", "reports_grid", "actions", "table_tools", "date_picker"}

# Crawled label entries that collide with workflow multiselect/date targets.
MISLEADING_LABEL_SELECTORS = {
    "label:has-text(\"Vehicle\")",
    "label:has-text(\"Fleet\")",
    "label:has-text(\"Driver\")",
    "label:has-text(\"Device\")",
    "label:has-text(\"Material\")",
}


def path_hash(url: str) -> str:
    if not url:
        return ""
    idx = url.find("#")
    return url[idx:] if idx >= 0 else urlparse(url).path


def upgrade_selector(sel: str) -> str:
  if sel == 'input[name="dateRange"]':
    return 'input[name="dateRange"]:visible'
  if sel.endswith('.dropdown-btn') and 'multiselect-dropdown' in sel:
    return f'{sel}:visible'
  if 'multiselect-select-all' in sel and 'multiselect-dropdown' in sel:
    return sel  # opened after dropdown click in executor
  return sel


def workflow_elements(page: dict) -> list:
    out = []
    for e in page.get("elements", []):
        section = e.get("section", "")
        sel = e.get("selector", "")
        if section in FILTER_SECTIONS or "dateRange" in sel or "multiselect-dropdown" in sel:
            copy = dict(e)
            copy["selector"] = upgrade_selector(copy["selector"])
            out.append(copy)
    return out


def main() -> None:
    data = json.loads(SITE_MAP.read_text(encoding="utf-8"))
    pages = data["pages"]

    curated = {k: p for k, p in pages.items() if k.startswith("reports_")}
    by_hash: dict[str, list[str]] = {}
    for name, page in pages.items():
        h = path_hash(page.get("url", ""))
        if h:
            by_hash.setdefault(h, []).append(name)

    synced = []
    demoted = []

    for cname, cpage in curated.items():
        workflow = workflow_elements(cpage)
        if not workflow:
            continue
        h = path_hash(cpage.get("url", ""))
        for pname in by_hash.get(h, []):
            if pname == cname or not pname.startswith("pages_reports_new_"):
                continue
            page = pages[pname]
            page["canonical_filters_from"] = cname
            if cpage.get("workflow_note"):
                page["workflow_note"] = cpage["workflow_note"]

            existing_labels = {e.get("label") for e in page.get("elements", [])}
            to_add = [e for e in workflow if e.get("label") not in existing_labels]
            if to_add:
                page["elements"] = to_add + page["elements"]
                synced.append((pname, cname, len(to_add)))

            for el in page["elements"]:
                sel = el.get("selector", "")
                if sel in MISLEADING_LABEL_SELECTORS and el.get("section") == "form_labels":
                    el["backup_selector"] = sel
                    el["section"] = "form_labels_deprecated"
                    el["label"] = f"{el.get('label', '')} (label only - do not use for actions)"
                    demoted.append((pname, sel))

    # Upgrade selectors on all curated report pages too
    for cname, cpage in curated.items():
        for el in cpage.get("elements", []):
            old = el.get("selector", "")
            new = upgrade_selector(old)
            if new != old:
                el["selector"] = new

    SITE_MAP.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Synced workflow elements to {len(synced)} merged pages")
    for row in synced[:5]:
        print(f"  {row[0]} <- {row[1]} (+{row[2]})")
    if len(synced) > 5:
        print(f"  ... and {len(synced) - 5} more")
    print(f"Demoted {len(demoted)} misleading form label selectors")


if __name__ == "__main__":
    main()
