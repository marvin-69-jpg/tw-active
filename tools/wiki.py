#!/usr/bin/env python3
"""
wiki — CLI for wiki health checks, entity matching, and research tools.

Subcommands:
  lint          Check bidirectional links, orphans, dangling refs, meta-page staleness
  match         Match keywords against wiki page names + aliases (for ingest planning)
  status        Quick wiki overview
  gaps          Find research opportunities (single-source, open questions, tag gaps)
  research-log  List past research reports (for dedup)
  arxiv         Search arxiv for papers (official API, no key needed)

Usage:
  wiki lint
  wiki match <keyword> [<keyword> ...]
  wiki status
  wiki gaps
  wiki research-log
  wiki arxiv "agent memory" multimodal [-n 5]

Global options:
  --wiki-dir PATH   Wiki directory (default: /home/node/agent-memory-research/wiki/)
  --index PATH      Index file (default: /home/node/agent-memory-research/index.md)
  --log PATH        Log file (default: /home/node/agent-memory-research/log.md)
"""

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ── Defaults ──────────────────────────────────────────────

WIKI_DIR = Path("/home/node/agent-memory-research/wiki/")
INDEX_PATH = Path("/home/node/agent-memory-research/index.md")
LOG_PATH = Path("/home/node/agent-memory-research/log.md")
CONCEPT_MAP = "concept-map.md"
OPEN_QUESTIONS = "open-questions.md"
META_PAGES = {CONCEPT_MAP, OPEN_QUESTIONS}
REQUIRED_FIELDS = {"aliases", "first_seen", "last_updated", "tags"}

# ── Shared helpers ────────────────────────────────────────


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    if not text.startswith("---"):
        return None, text
    end = text.find("---", 3)
    if end == -1:
        return None, text
    fields = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip()
    return fields, text[end + 3 :].strip()


def parse_aliases(raw: str) -> list[str]:
    if raw.startswith("[") and raw.endswith("]"):
        return [a.strip().lower() for a in raw[1:-1].split(",") if a.strip()]
    return [raw.strip().lower()] if raw.strip() else []


def extract_links(text: str) -> set[str]:
    """Extract all [[target]] and [[target|display]] wiki-links, normalized to stems.
    Preserves raw/ prefix so callers can distinguish raw refs from wiki refs."""
    raw_links = re.findall(r"\[\[([^\]|\\]+)(?:[|\\][^\]]+)?\]\]", text)
    stems = set()
    for link in raw_links:
        stem = link.strip()
        # Strip wiki/ prefix (wiki pages are referenced by stem)
        if stem.startswith("wiki/"):
            stem = stem[len("wiki/") :]
        # Strip .md suffix
        if stem.endswith(".md"):
            stem = stem[:-3]
        stems.add(stem.lower())
    return stems


def extract_related_links(text: str) -> set[str]:
    """Extract links only from the ## Related section."""
    in_related = False
    related_text = []
    for line in text.splitlines():
        if line.startswith("## Related"):
            in_related = True
            continue
        if in_related and line.startswith("## "):
            break
        if in_related:
            related_text.append(line)
    return extract_links("\n".join(related_text))


def load_wiki_pages(wiki_dir: Path) -> dict[str, dict]:
    """Load all wiki pages. Returns {stem: {fields, body, aliases, links, related_links, text}}."""
    pages = {}
    for f in sorted(wiki_dir.glob("*.md")):
        if f.name.startswith("_"):
            continue
        try:
            text = f.read_text("utf-8")
        except Exception:
            continue
        fields, body = parse_frontmatter(text)
        aliases = []
        if fields and "aliases" in fields:
            aliases = parse_aliases(fields["aliases"])
        pages[f.stem.lower()] = {
            "fields": fields,
            "body": body,
            "text": text,
            "aliases": aliases,
            "links": extract_links(text),
            "related_links": extract_related_links(text),
            "path": f,
        }
    return pages


def parse_index_pages(index_path: Path) -> set[str]:
    """Extract page stems referenced in index.md wiki table."""
    stems = set()
    if not index_path.exists():
        return stems
    for line in index_path.read_text("utf-8").splitlines():
        # Match [[wiki/name\|Display]] or [[wiki/name|Display]]
        for m in re.finditer(r"\[\[wiki/([^\]|\\]+)", line):
            stems.add(m.group(1).lower())
    return stems


def build_alias_index(pages: dict) -> dict[str, str]:
    """Map every alias (lowercased) to its page stem. Also maps stem → stem."""
    idx = {}
    for stem, page in pages.items():
        idx[stem] = stem
        for alias in page["aliases"]:
            idx[alias] = stem
    return idx


def tokenize_query(query: str) -> list[str]:
    """Split query into keywords, with CJK n-gram support."""
    tokens = []
    cjk_range = r"[\u4e00-\u9fff\u3400-\u4dbf]"
    parts = re.split(f"({cjk_range}+)", query.lower())
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if re.match(f"^{cjk_range}+$", part):
            for n in (2, 3):
                for i in range(len(part) - n + 1):
                    tokens.append(part[i : i + n])
        else:
            tokens.extend(w for w in part.split() if w)
    return list(dict.fromkeys(tokens))


# ── lint ──────────────────────────────────────────────────


def cmd_lint(wiki_dir: Path, index_path: Path, **_):
    pages = load_wiki_pages(wiki_dir)
    issues = []

    def add(sev, page, msg):
        issues.append((sev, page, msg))

    all_stems = set(pages.keys())

    # 1. Missing backlinks (Related section only — bidirectional rule)
    #    If A has B in its Related section, B should have A in its Related section.
    #    Links in Current Understanding / Key Sources don't require backlinks.
    for stem, page in pages.items():
        for target in page["related_links"]:
            if target == stem or target.startswith("raw/"):
                continue
            if target in all_stems and target not in {s.replace(".md", "") for s in META_PAGES}:
                target_page = pages.get(target)
                if target_page and stem not in target_page["related_links"]:
                    add("error", target, f"missing backlink to [[{stem}]] in Related (linked from {stem})")

    # 2. Orphan pages (0 inbound links, excluding meta pages)
    inbound_counts: dict[str, int] = {s: 0 for s in all_stems}
    for stem, page in pages.items():
        for target in page["links"]:
            if target in inbound_counts:
                inbound_counts[target] += 1
    for stem, count in inbound_counts.items():
        if count == 0 and stem not in {s.replace(".md", "") for s in META_PAGES}:
            add("warn", stem, "orphan page (0 inbound links)")

    # 3. Dangling links (skip raw/ refs — those point to raw/ directory, not wiki pages)
    alias_index = build_alias_index(pages)
    for stem, page in pages.items():
        for target in page["links"]:
            if target.startswith("raw/"):
                continue
            if target not in all_stems and target not in alias_index:
                add("error", stem, f"dangling link [[{target}]]")

    # 4. Index sync
    index_stems = parse_index_pages(index_path)
    for stem in all_stems:
        if stem not in index_stems:
            add("warn", stem, "not in index.md")
    for stem in index_stems:
        if stem not in all_stems:
            add("error", "index.md", f"dangling reference to '{stem}'")

    # 5. Concept-map staleness
    cm_stem = CONCEPT_MAP.replace(".md", "")
    if cm_stem in pages:
        cm_links = pages[cm_stem]["links"]
        for stem in all_stems:
            if stem != cm_stem and stem not in cm_links and stem != OPEN_QUESTIONS.replace(".md", ""):
                add("warn", CONCEPT_MAP, f"missing page: {stem}")

    # 6. Open-questions staleness
    oq_stem = OPEN_QUESTIONS.replace(".md", "")
    if oq_stem in pages:
        oq_updated = pages[oq_stem]["fields"].get("last_updated", "") if pages[oq_stem]["fields"] else ""
        newest_date = ""
        for stem, page in pages.items():
            if page["fields"]:
                d = page["fields"].get("last_updated", "")
                if d > newest_date:
                    newest_date = d
        if oq_updated and newest_date and oq_updated < newest_date:
            add("warn", OPEN_QUESTIONS, f"stale (last updated {oq_updated}, wiki has pages from {newest_date})")

    # 7. Missing frontmatter fields
    for stem, page in pages.items():
        if page["fields"] is None:
            add("error", stem, "missing frontmatter")
            continue
        for field in REQUIRED_FIELDS:
            if field not in page["fields"]:
                add("warn", stem, f"missing field: {field}")

    # Report
    print(f"wiki lint — {len(pages)} pages")

    if not issues:
        print("✓ all clear")
        return 0

    for sev in ("error", "warn"):
        items = [(s, p, m) for s, p, m in issues if s == sev]
        if items:
            icon = {"error": "✗", "warn": "△"}[sev]
            for _, p, msg in items:
                print(f"  {icon} {p}: {msg}")

    errors = sum(1 for s, _, _ in issues if s == "error")
    warnings = sum(1 for s, _, _ in issues if s == "warn")
    print(f"\n{errors} errors, {warnings} warnings")
    return 1 if errors else 0


# ── match ─────────────────────────────────────────────────


def cmd_match(wiki_dir: Path, keywords: list[str], **_):
    pages = load_wiki_pages(wiki_dir)
    alias_index = build_alias_index(pages)

    q = " ".join(keywords)
    tokens = tokenize_query(q)

    scores: dict[str, float] = {}

    for stem, page in pages.items():
        score = 0.0
        fname = stem.replace("-", " ").replace("_", " ")
        body_lower = page["body"].lower()
        tags_str = (page["fields"].get("tags", "") if page["fields"] else "").lower()

        for kw in tokens:
            # Exact stem match
            if kw == stem or kw == fname:
                score += 20
            # Exact alias match
            elif kw in page["aliases"]:
                score += 15
            # Partial stem match
            elif kw in fname or fname in kw:
                score += 10
            # Partial alias match
            else:
                for alias in page["aliases"]:
                    if kw in alias or alias in kw:
                        score += 8
                        break

            # Tag match
            if kw in tags_str:
                score += 5

            # Body frequency (capped at +5)
            body_hits = body_lower.count(kw)
            score += min(body_hits, 5)

        if score > 0:
            scores[stem] = score

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:15]

    print(f"wiki match: \"{q}\"\n")
    if not ranked:
        print("(no matches)")
        return 0

    for stem, score in ranked:
        page = pages[stem]
        # Get display name
        name = stem
        for line in page["text"].splitlines():
            if line.startswith("# "):
                name = line[2:].strip()
                break
        tags = page["fields"].get("tags", "") if page["fields"] else ""
        print(f"  {score:5.0f}  {stem:30s} [{name}] ({tags})")

    return 0


# ── status ────────────────────────────────────────────────


def cmd_status(wiki_dir: Path, index_path: Path, log_path: Path, **_):
    pages = load_wiki_pages(wiki_dir)

    # Count raw sources
    raw_dir = wiki_dir.parent / "raw"
    raw_count = len(list(raw_dir.glob("*.md"))) if raw_dir.exists() else 0

    print(f"wiki status — {len(pages)} pages, {raw_count} raw sources")

    # Last ingest
    if log_path.exists():
        log_text = log_path.read_text("utf-8")
        m = re.search(r"## \[(\d{4}-\d{2}-\d{2})\] ingest \| (.+)", log_text)
        if m:
            print(f"  last ingest: {m.group(1)} ({m.group(2).strip()})")

    # Tag distribution
    tag_counts: dict[str, int] = {}
    for page in pages.values():
        if page["fields"] and "tags" in page["fields"]:
            raw_tags = page["fields"]["tags"]
            if raw_tags.startswith("[") and raw_tags.endswith("]"):
                tags = [t.strip() for t in raw_tags[1:-1].split(",") if t.strip()]
            else:
                tags = [raw_tags.strip()] if raw_tags.strip() else []
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
    if tag_counts:
        tag_str = ", ".join(f"{t}:{c}" for t, c in sorted(tag_counts.items(), key=lambda x: -x[1]))
        print(f"  tags: {tag_str}")

    # Lint summary (run internally)
    all_stems = set(pages.keys())
    errors = 0
    warnings = 0

    # Quick backlink check (Related section only, skip raw/ refs)
    for stem, page in pages.items():
        for target in page["related_links"]:
            if target == stem or target.startswith("raw/"):
                continue
            if target in all_stems and target not in {s.replace(".md", "") for s in META_PAGES}:
                target_page = pages.get(target)
                if target_page and stem not in target_page["related_links"]:
                    errors += 1

    # Concept-map coverage
    cm_stem = CONCEPT_MAP.replace(".md", "")
    cm_covered = 0
    cm_total = len(all_stems) - len(META_PAGES)
    if cm_stem in pages:
        cm_links = pages[cm_stem]["links"]
        cm_covered = sum(1 for s in all_stems if s in cm_links or s in {s2.replace(".md", "") for s2 in META_PAGES})

    print(f"  lint: {errors} missing backlinks")
    print(f"  concept-map: {cm_covered}/{cm_total} pages covered")

    # Open-questions freshness
    oq_stem = OPEN_QUESTIONS.replace(".md", "")
    if oq_stem in pages and pages[oq_stem]["fields"]:
        oq_date = pages[oq_stem]["fields"].get("last_updated", "?")
        print(f"  open-questions: last updated {oq_date}")

    return 0


# ── gaps ──────────────────────────────────────────────────

REPORTS_DIR = Path("/home/node/agent-memory-research/reports/")


def cmd_gaps(wiki_dir: Path, index_path: Path, log_path: Path, **_):
    pages = load_wiki_pages(wiki_dir)
    reports_dir = wiki_dir.parent / "reports"
    gaps = []  # (priority, category, description, details)

    # Load past research topics to avoid repeats
    past_topics = set()
    if reports_dir.exists():
        for f in reports_dir.glob("*.md"):
            try:
                text = f.read_text("utf-8")
                fm, _ = parse_frontmatter(text)
                if fm and "topic" in fm:
                    past_topics.add(fm["topic"].lower())
            except Exception:
                pass

    # 1. Single-source pages (only 1 Key Sources entry → needs more evidence)
    for stem, page in pages.items():
        if stem in {s.replace(".md", "") for s in META_PAGES}:
            continue
        source_count = len(re.findall(r"^\- \*\*\d{4}", page["body"], re.MULTILINE))
        if source_count <= 1:
            # Get page title
            title = stem
            for line in page["text"].splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            if stem.lower() not in past_topics and title.lower() not in past_topics:
                gaps.append((1, "SINGLE-SOURCE", title, f"{stem}.md — only {source_count} source(s)"))

    # 2. Open questions with no progress
    oq_stem = OPEN_QUESTIONS.replace(".md", "")
    if oq_stem in pages:
        oq_text = pages[oq_stem]["body"]
        # Find research gaps table
        in_gaps_table = False
        for line in oq_text.splitlines():
            if "Research Gaps" in line:
                in_gaps_table = True
                continue
            if in_gaps_table and line.startswith("|") and "---" not in line and "Gap" not in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if len(cells) >= 2:
                    gap_name = cells[0]
                    status = cells[1] if len(cells) > 1 else ""
                    if "完全沒覆蓋" in status:
                        if gap_name.lower() not in past_topics:
                            gaps.append((0, "RESEARCH-GAP", gap_name, f"完全沒覆蓋 — from open-questions.md"))
            if in_gaps_table and line.startswith("##"):
                break

    # 3. Tag imbalance (tags with very few pages)
    tag_counts: dict[str, int] = {}
    for page in pages.values():
        if page["fields"] and "tags" in page["fields"]:
            raw_tags = page["fields"]["tags"]
            if raw_tags.startswith("[") and raw_tags.endswith("]"):
                tags = [t.strip() for t in raw_tags[1:-1].split(",") if t.strip()]
            else:
                tags = [raw_tags.strip()] if raw_tags.strip() else []
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
    avg_count = sum(tag_counts.values()) / max(len(tag_counts), 1)
    for tag, count in sorted(tag_counts.items()):
        if count <= avg_count * 0.3 and tag not in past_topics:
            gaps.append((2, "TAG-IMBALANCE", tag, f"only {count} page(s), avg is {avg_count:.0f}"))

    # 4. Stale pages (not updated in 7+ days relative to newest)
    newest_date = ""
    for page in pages.values():
        if page["fields"]:
            d = page["fields"].get("last_updated", "")
            if d > newest_date:
                newest_date = d
    if newest_date:
        for stem, page in pages.items():
            if stem in {s.replace(".md", "") for s in META_PAGES}:
                continue
            if page["fields"]:
                d = page["fields"].get("last_updated", "")
                if d and d < newest_date[:8]:  # compare YYYY-MM prefix
                    title = stem
                    for line in page["text"].splitlines():
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break
                    if stem.lower() not in past_topics:
                        gaps.append((3, "STALE", title, f"{stem}.md — last updated {d}"))

    # Report
    gaps.sort(key=lambda x: x[0])
    print(f"wiki gaps — {len(gaps)} opportunities found (excluding {len(past_topics)} past topics)\n")

    if not gaps:
        print("✓ no gaps found")
        return 0

    for cat in ("RESEARCH-GAP", "SINGLE-SOURCE", "TAG-IMBALANCE", "STALE"):
        items = [(p, c, t, d) for p, c, t, d in gaps if c == cat]
        if items:
            labels = {
                "RESEARCH-GAP": "🔴 Research gaps (completely uncovered)",
                "SINGLE-SOURCE": "🟡 Single-source pages (need more evidence)",
                "TAG-IMBALANCE": "🔵 Underrepresented tags",
                "STALE": "⚪ Stale pages",
            }
            print(f"{labels[cat]} ({len(items)}):")
            for _, _, title, detail in items:
                print(f"  {title} — {detail}")
            print()

    # Suggest top 3
    top = gaps[:3]
    if top:
        print("── Suggested research topics (top 3) ──")
        for i, (_, cat, title, detail) in enumerate(top, 1):
            print(f"  {i}. [{cat}] {title}")

    return 0


def cmd_arxiv(keywords: list[str], max_results: int = 10, **_):
    """Search arxiv for papers matching keywords."""
    import urllib.request
    import urllib.parse
    import xml.etree.ElementTree as ET

    # Build query: first keyword as title phrase, rest as AND terms in all fields
    # If only one keyword, search in all fields
    if len(keywords) == 1:
        query = f'all:"{keywords[0]}"'
    else:
        # First keyword as title search, rest as all-field AND
        parts = []
        for kw in keywords:
            if " " in kw:
                parts.append(f'all:"{kw}"')
            else:
                parts.append(f"all:{kw}")
        query = " AND ".join(parts)

    url = (
        f"http://export.arxiv.org/api/query?"
        f"search_query={urllib.parse.quote(query)}"
        f"&max_results={max_results}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"arxiv search failed: {e}")
        return 1

    root = ET.fromstring(xml_data)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    os_ns = "http://a9.com/-/spec/opensearch/1.1/"

    total_el = root.find(f"{{{os_ns}}}totalResults")
    total = total_el.text if total_el is not None else "?"

    entries = root.findall("a:entry", ns)
    print(f"arxiv search: \"{' '.join(keywords)}\" — {total} results (showing {len(entries)})\n")

    if not entries:
        print("(no results)")
        return 0

    for entry in entries:
        paper_id = entry.find("a:id", ns).text.split("/")[-1]
        title = entry.find("a:title", ns).text.strip().replace("\n", " ")
        published = entry.find("a:published", ns).text[:10]
        summary = entry.find("a:summary", ns).text.strip().replace("\n", " ")
        authors = [a.find("a:name", ns).text for a in entry.findall("a:author", ns)]
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += f" +{len(authors)-3}"

        # Truncate summary
        if len(summary) > 200:
            summary = summary[:197] + "..."

        print(f"  {published} | {paper_id}")
        print(f"  {title}")
        print(f"  {author_str}")
        print(f"  {summary}")
        print(f"  alphaxiv: https://www.alphaxiv.org/overview/{paper_id.split('v')[0]}")
        print()

    return 0


def cmd_research_log(wiki_dir: Path, **_):
    reports_dir = wiki_dir.parent / "reports"
    if not reports_dir.exists() or not list(reports_dir.glob("*.md")):
        print("research-log: no reports yet")
        return 0

    entries = []
    for f in sorted(reports_dir.glob("*.md"), reverse=True):
        try:
            text = f.read_text("utf-8")
            fm, _ = parse_frontmatter(text)
            if fm:
                entries.append({
                    "file": f.name,
                    "date": fm.get("date", "?"),
                    "topic": fm.get("topic", "?"),
                    "gap_type": fm.get("gap_type", "?"),
                    "sources_found": fm.get("sources_found", "?"),
                    "pages_updated": fm.get("wiki_pages_updated", "?"),
                    "pages_created": fm.get("wiki_pages_created", "?"),
                })
        except Exception:
            pass

    print(f"research-log — {len(entries)} reports\n")
    for e in entries:
        print(f"  {e['date']}  [{e['gap_type']}] {e['topic']}")
        print(f"           sources:{e['sources_found']} updated:{e['pages_updated']} created:{e['pages_created']}")
        print()

    return 0


# ── Main ──────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="wiki",
        description="Wiki management CLI",
    )
    parser.add_argument("--wiki-dir", default=str(WIKI_DIR))
    parser.add_argument("--index", default=str(INDEX_PATH))
    parser.add_argument("--log", default=str(LOG_PATH))

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("lint", help="Check bidirectional links, orphans, staleness")
    p_match = sub.add_parser("match", help="Match keywords against wiki pages")
    p_match.add_argument("keywords", nargs="+", help="Keywords to match")
    sub.add_parser("status", help="Quick wiki overview")
    sub.add_parser("gaps", help="Find research opportunities (single-source, open questions, tag gaps)")
    sub.add_parser("research-log", help="List past research reports (for dedup)")
    p_arxiv = sub.add_parser("arxiv", help="Search arxiv for papers")
    p_arxiv.add_argument("keywords", nargs="+", help="Search keywords (AND logic)")
    p_arxiv.add_argument("-n", "--max-results", type=int, default=10, help="Max results (default 10)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    kwargs = {
        "wiki_dir": Path(args.wiki_dir),
        "index_path": Path(args.index),
        "log_path": Path(args.log),
    }
    if args.command == "match":
        kwargs["keywords"] = args.keywords
    if args.command == "arxiv":
        kwargs["keywords"] = args.keywords
        kwargs["max_results"] = args.max_results
    cmds = {
        "lint": cmd_lint,
        "match": cmd_match,
        "status": cmd_status,
        "gaps": cmd_gaps,
        "research-log": cmd_research_log,
        "arxiv": cmd_arxiv,
    }
    sys.exit(cmds[args.command](**kwargs))


if __name__ == "__main__":
    main()
