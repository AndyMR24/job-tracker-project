"""Server-rendered HTML for the local dashboard.

Every dynamic value passes through `esc`, so public job data cannot inject markup. The stylesheet and
the small status script are static text. The module stays ASCII-only, and uses HTML entities where
typography matters, so it renders identically regardless of console code page.
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from . import dashboard

NAV = (("/", "Overview"), ("/jobs", "Jobs"), ("/saved", "Saved"), ("/applications", "Applications"), ("/search", "Search"), ("/history", "History"), ("/sources", "Sources"))

STYLE = """
:root { --bg:#f5f6f8; --card:#fff; --line:#d7dbe2; --ink:#1d2430; --muted:#5d6875; --accent:#2757c9; --good:#15683c; --warn:#8a5b00; --bad:#9d2b2d; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 "Segoe UI", system-ui, -apple-system, sans-serif; }
header { background:#111a2b; color:#fff; padding:10px 18px; display:flex; gap:20px; align-items:baseline; flex-wrap:wrap; }
header .brand { font-weight:600; letter-spacing:.02em; }
header nav a { color:#bcc8db; text-decoration:none; margin-right:14px; padding:3px 0; display:inline-block; }
header nav a:hover { color:#fff; }
header nav a.active { color:#fff; border-bottom:2px solid #7ba3ff; }
main { max-width:1500px; margin:18px auto; padding:0 18px 40px; }
footer { max-width:1500px; margin:0 auto; padding:0 18px 30px; color:var(--muted); font-size:12px; }
h2 { font-size:19px; margin:6px 0 12px; }
h3 { font-size:15px; margin:16px 0 8px; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px 16px; margin-bottom:16px; }
.card h3:first-child { margin-top:0; }
.grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(155px,1fr)); margin-bottom:16px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.stat .value { font-size:22px; font-weight:600; }
.stat .label { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
.wide { overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:8px; margin-bottom:16px; }
.wide table { margin:0; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:7px 9px; border-bottom:1px solid var(--line); vertical-align:top; }
th { background:#eef1f6; font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); white-space:nowrap; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:#f8fafc; }
td.num, th.num { text-align:right; white-space:nowrap; }
.badge { display:inline-block; padding:1px 7px; border-radius:10px; font-size:12px; font-weight:600; white-space:nowrap; }
.band-recommended { background:#e6f4ea; color:var(--good); border:1px solid #b7e0c4; }
.band-borderline { background:#fdf3e3; color:var(--warn); border:1px solid #f0d9a8; }
.band-excluded { background:#fdeaea; color:var(--bad); border:1px solid #f3c2c2; }
.badge.status { background:#eef1f6; color:var(--muted); border:1px solid var(--line); }
.id-chip { background:#eef1f6; color:var(--muted); border:1px solid var(--line); border-radius:6px; padding:1px 7px; font-size:14px; font-weight:600; vertical-align:middle; }
.badge.kind { background:#eef1f6; color:var(--muted); border:1px solid var(--line); font-weight:500; }
.muted { color:var(--muted); }
.small { font-size:12px; }
.notice { border:1px solid #b7e0c4; background:#e9f7ee; color:#14532d; padding:8px 12px; border-radius:6px; margin-bottom:14px; }
.error { border:1px solid #f3c2c2; background:#fdeaea; color:#7f1d1d; padding:8px 12px; border-radius:6px; margin-bottom:14px; }
.filters { display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; }
.filters label { display:block; font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }
input, select, textarea, button { font:inherit; padding:5px 7px; border:1px solid var(--line); border-radius:6px; background:#fff; color:inherit; }
button { cursor:pointer; }
button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
button.danger { background:#fff; border-color:#e2b6b6; color:var(--bad); }
form.inline { display:inline-block; margin:0 4px 4px 0; }
.row-actions { white-space:nowrap; }
ul.plain { margin:6px 0 0; padding-left:18px; }
ul.plain li { margin:2px 0; }
pre.body { white-space:pre-wrap; background:#fbfcfe; border:1px solid var(--line); border-radius:6px; padding:10px; max-height:420px; overflow:auto; margin:0; font-family:ui-monospace, Consolas, monospace; font-size:12.5px; }
.two-col { display:grid; grid-template-columns:minmax(0,2fr) minmax(280px,1fr); gap:16px; align-items:start; }
.three-col { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; align-items:start; }
dl.facts { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; margin:0; }
dl.facts dt { color:var(--muted); font-size:12px; }
dl.facts dd { margin:0; }
@media (max-width:1000px) { .two-col { grid-template-columns:1fr; } }
"""

SEARCH_SCRIPT = """
<script>
function logLine(text) { const item = document.createElement("li"); item.textContent = text; return item; }
function statusFact(label, value) { const line = document.createElement("p"); line.className = "small"; line.textContent = label + ": " + value; return line; }
async function refreshSearchStatus() {
  try {
    const response = await fetch("/search/status.json", { headers: { "Accept": "application/json" } });
    if (!response.ok) { return; }
    const state = await response.json();
    const box = document.getElementById("search-status");
    box.replaceChildren();
    const heading = document.createElement("p");
    heading.className = "small";
    const badge = document.createElement("span");
    badge.className = "badge status";
    badge.textContent = state.running ? "running" : "idle";
    heading.append(badge, document.createTextNode(" " + state.message));
    box.append(heading);
    box.append(statusFact("Queries", state.queries_done + " / " + state.queries_total));
    box.append(statusFact("Public results", state.found));
    box.append(statusFact("Stored", state.stored + " (" + state.new + " new, " + state.known + " known, " + state.excluded + " excluded)"));
    if (state.started_at) { box.append(statusFact("Started", state.started_at.slice(0, 19))); }
    if (state.finished_at) { box.append(statusFact("Finished", state.finished_at.slice(0, 19))); }
    const log = document.getElementById("search-log");
    log.replaceChildren();
    (state.log.slice(-20)).forEach(function (entry) { log.append(logLine(entry)); });
    const errors = document.getElementById("search-errors");
    errors.replaceChildren();
    (state.errors.length ? state.errors : ["No source errors."]).forEach(function (entry) { errors.append(logLine(entry)); });
  } catch (error) {
    return;
  }
}
refreshSearchStatus();
setInterval(refreshSearchStatus, 2000);
</script>
"""


def esc(value) -> str:
    return escape("" if value is None else str(value))


def options_html(values, labels=None, selected=None) -> str:
    items = []
    for value in values:
        label = labels.get(value, value) if labels else value
        items.append('<option value="%s"%s>%s</option>' % (esc(value), " selected" if value == selected else "", esc(label)))
    return "".join(items)


def band_of(record: dict) -> str:
    return "excluded" if record["excluded"] else record["assessment"]


def band_label(record: dict) -> str:
    return dashboard.BAND_LABELS.get(band_of(record), band_of(record))


def score_badge(record: dict) -> str:
    score = "not scored" if record["score"] is None else "%s/100" % record["score"]
    return '<span class="badge band-%s">%s %s</span>' % (esc(band_of(record)), esc(score), esc(band_label(record)))


def status_badge(record: dict) -> str:
    return '<span class="badge status">%s</span>' % esc(dashboard.STATUS_LABELS.get(record["status"], record["status"]))


def link(url, label=None) -> str:
    if not url:
        return '<span class="muted">&ndash;</span>'
    return '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (esc(url), esc(label or url))


def job_link(job_id) -> str:
    return '<a href="/jobs/%s">%s</a>' % (esc(job_id), esc(job_id))


def query_url(path: str, params: dict) -> str:
    kept = {key: value for key, value in params.items() if value not in (None, "", 0)}
    return path + ("?" + urlencode(kept) if kept else "")


def page(title: str, active: str, content: str, *, notice=None, error=None, database=None) -> str:
    nav = "".join('<a class="%s" href="%s">%s</a>' % ("active" if href == active else "", href, esc(label)) for href, label in NAV)
    banner = '<div class="notice">%s</div>' % esc(notice) if notice else ""
    failure = '<div class="error">%s</div>' % esc(error) if error else ""
    footer = '<footer>Local-first job agent &middot; database: %s &middot; applications are never submitted automatically</footer>' % esc(database) if database else ""
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s &middot; Job Agent</title>
<style>%s</style>
</head>
<body>
<header><span class="brand">Job Agent</span><nav>%s</nav></header>
<main>
%s%s
%s
</main>
%s
</body>
</html>
""" % (esc(title), STYLE, nav, banner, failure, content, footer)


def stat_cards(cards) -> str:
    items = "".join('<div class="stat"><div class="value">%s</div><div class="label">%s</div></div>' % (esc(value), esc(label)) for label, value in cards)
    return '<div class="grid">%s</div>' % items


def decision_forms(record: dict, next_path: str) -> str:
    return ('<form class="inline" method="post" action="/jobs/%s/decision">'
            '<input type="hidden" name="action" value="save"><input type="hidden" name="next" value="%s">'
            '<button type="submit">Save</button></form>'
            '<form class="inline" method="post" action="/jobs/%s/decision">'
            '<input type="hidden" name="action" value="reject"><input type="hidden" name="next" value="%s">'
            '<button class="danger" type="submit">Reject</button></form>') % (esc(record["id"]), esc(next_path), esc(record["id"]), esc(next_path))


def job_table(records, *, actions: bool = False) -> str:
    if not records:
        return '<div class="card muted">No jobs match the current selection.</div>'
    head = ["ID", "Score", "Title", "Company", "Location", "Arrangement", "Source", "Status", "Discovered"]
    if actions:
        head.append("Actions")
    rows = []
    for record in records:
        cells = [job_link(record["id"]), score_badge(record),
                 '<a href="/jobs/%s">%s</a>' % (esc(record["id"]), esc(record["title"])),
                 esc(record["company"] or "unknown"), esc(record["location"] or "unknown"), esc(record["arrangement"]),
                 esc(record["source"]), status_badge(record), esc((record["discovered_at"] or "")[:10])]
        if actions:
            posting = '<a class="small" href="%s" target="_blank" rel="noopener noreferrer">posting</a> ' % esc(record["source_url"]) if record["source_url"] else ""
            cells.append('<span class="row-actions">%s%s</span>' % (posting, decision_forms(record, "/saved")))
        rows.append("<tr>" + "".join("<td>%s</td>" % cell for cell in cells) + "</tr>")
    header = "".join("<th>%s</th>" % esc(name) for name in head)
    return '<div class="wide"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (header, "".join(rows))


def filter_bar(values: dict, sources, statuses, *, action: str = "/jobs") -> str:
    return """<form class="card filters" method="get" action="%s">
<div><label for="q">Search text</label><input id="q" type="search" name="q" value="%s" placeholder="title, company, location" size="20"></div>
<div><label for="source">Source</label><select id="source" name="source"><option value="">any</option>%s</select></div>
<div><label for="status">Status</label><select id="status" name="status"><option value="">any</option>%s</select></div>
<div><label for="assessment">Fit</label><select id="assessment" name="assessment"><option value="">any</option>%s</select></div>
<div><label for="arrangement">Arrangement</label><select id="arrangement" name="arrangement"><option value="">any</option>%s</select></div>
<div><label for="min_score">Min score</label><input id="min_score" type="number" name="min_score" min="0" max="100" step="5" value="%s" size="4"></div>
<div><label for="sort">Sort by</label><select id="sort" name="sort">%s</select></div>
<div><label for="include_excluded">Excluded jobs</label><select id="include_excluded" name="include_excluded">
<option value="0"%s>hide</option><option value="1"%s>show</option></select></div>
<div><label for="include_rejected">User rejections</label><select id="include_rejected" name="include_rejected">
<option value="0"%s>hide</option><option value="1"%s>show</option></select></div>
<div><label>&nbsp;</label><button class="primary" type="submit">Apply</button> <a class="small" href="%s">reset</a></div>
</form>""" % (esc(action), esc(values.get("q", "")),
               options_html(sources, selected=values.get("source", "")),
               options_html(statuses, labels=dashboard.STATUS_LABELS, selected=values.get("status", "")),
               options_html(dashboard.BANDS, labels=dashboard.BAND_LABELS, selected=values.get("assessment", "")),
               options_html(dashboard.ARRANGEMENTS, selected=values.get("arrangement", "")),
               esc(values.get("min_score", "")),
               options_html(sorted(dashboard.SORTS), labels=dashboard.SORTS, selected=values.get("sort", "score_desc")),
               " selected" if values.get("include_excluded", "0") == "0" else "",
               " selected" if values.get("include_excluded", "0") == "1" else "",
               " selected" if values.get("include_rejected", "0") == "0" else "",
               " selected" if values.get("include_rejected", "0") == "1" else "",
               esc(action))


def pager(path: str, values: dict, page_number: int, page_count: int, total: int) -> str:
    parts = []
    if page_number > 1:
        parts.append('<a href="%s">&larr; previous</a>' % esc(query_url(path, {**values, "page": page_number - 1})))
    parts.append('<span class="muted">page %s of %s &middot; %s matching job(s)</span>' % (page_number, page_count, total))
    if page_number < page_count:
        parts.append('<a href="%s">next &rarr;</a>' % esc(query_url(path, {**values, "page": page_number + 1})))
    return '<p class="small">' + " &middot; ".join(parts) + "</p>"


def list_block(title: str, items) -> str:
    if not items:
        return "<h3>%s</h3><p class=\"small muted\">None recorded.</p>" % esc(title)
    return "<h3>%s</h3><ul class=\"plain\">%s</ul>" % (esc(title), "".join("<li>%s</li>" % esc(item) for item in items))


def text_card(title: str, text) -> str:
    if not text:
        return ""
    return '<div class="card"><h3>%s</h3><pre class="body">%s</pre></div>' % (esc(title), esc(text))


def overview_page(cards, recent, shortlist, applications, sources) -> str:
    left = '<div class="card"><h3>Newest discoveries</h3>%s</div>' % job_table(recent)
    right = ['<div class="card"><h3>Saved shortlist</h3>']
    if shortlist:
        right.append('<ul class="plain">' + "".join('<li><a href="/jobs/%s">%s</a> <span class="small muted">%s</span></li>' % (esc(record["id"]), esc(record["title"]), esc(record["company"] or "unknown")) for record in shortlist) + "</ul>")
    else:
        right.append('<p class="small muted">Nothing saved yet. Save jobs from the <a href="/jobs">job list</a>.</p>')
    right.append("</div>")
    right.append('<div class="card"><h3>Applications in progress</h3>')
    if applications:
        right.append('<ul class="plain">' + "".join('<li><a href="/jobs/%s">%s</a> <span class="badge status">%s</span></li>' % (esc(row["job_id"]), esc(row["title"]), esc(dashboard.STATUS_LABELS.get(row["status"], row["status"]))) for row in applications) + "</ul>")
    else:
        right.append('<p class="small muted">Nothing tracked yet. Record manual progress on the <a href="/applications">applications page</a>.</p>')
    right.append("</div>")
    right.append('<div class="card"><h3>Sources</h3><ul class="plain">%s</ul></div>' % ("".join('<li>%s <span class="small muted">%s jobs &middot; average %s</span></li>' % (esc(item["source"]), item["jobs"], esc(item["average_score"] if item["average_score"] is not None else "-")) for item in sources) or '<li class="muted">No jobs stored yet.</li>'))
    return stat_cards(cards) + '<div class="two-col"><div>%s</div><div>%s</div></div>' % (left, "".join(right))


def jobs_page(records, values, sources, statuses, page_number, page_count, total) -> str:
    hint = '<p class="small muted">Jobs you rejected and jobs the evaluator excluded are hidden by default; set the matching filter to "show" to inspect them. They stay stored either way.</p>'
    return ('<h2>Jobs <span class="small muted">%s matching</span></h2>' % total) + filter_bar(values, sources, statuses) + hint + job_table(records) + pager("/jobs", values, page_number, page_count, total)


def job_detail_page(record, trail, cv_versions) -> str:
    evaluation = record["evaluation"]
    facts = [("Company", esc(record["company"] or "unknown")), ("Location", esc(record["location"] or "unknown")),
             ("Arrangement", esc(record["arrangement"])), ("Seniority", esc(record["seniority"])),
             ("Employment type", esc(record["employment_type"] or "unknown")), ("Salary", esc(record["salary"] or "unknown")),
             ("Source", esc(record["source"])), ("External ID", esc(record["external_job_id"] or "-")),
             ("Original posting", link(record["source_url"], record["source_url"])),
             ("Discovered", esc((record["discovered_at"] or "")[:19])), ("Last seen", esc((record["last_seen_at"] or "")[:19])),
             ("Status", esc(dashboard.STATUS_LABELS.get(record["status"], record["status"])))]
    if record["rejection_reason"]:
        facts.append(("Rejection reason", esc(record["rejection_reason"])))
    facts_html = "".join("<dt>%s</dt><dd>%s</dd>" % (esc(key), value) for key, value in facts)
    evaluation_card = ('<div class="card"><h3>Fit evaluation %s</h3>'
                       '<p class="small muted">The score describes how well the listing matches the stored profile and configured preferences. It is not a hiring probability.</p>%s%s%s%s</div>') % (
        score_badge(record), list_block("Strong matches", evaluation.get("strong_matches")), list_block("Potential gaps", evaluation.get("potential_gaps")),
        list_block("Important concerns", evaluation.get("concerns")), list_block("Uncertainties", evaluation.get("uncertainties")))
    requirement_rows = "".join('<tr><td>%s</td><td><span class="badge kind">%s</span></td><td>%s</td></tr>' % (esc(item.get("text", "")), esc(item.get("kind", "unknown")), esc(item.get("category", "skill"))) for item in record["requirements"])
    if not requirement_rows:
        requirement_rows = '<tr><td colspan="3" class="muted">No explicit requirements were extracted for this listing.</td></tr>'
    actions = """<div class="card"><h3>Actions</h3>
<form class="inline" method="post" action="/jobs/%s/decision"><input type="hidden" name="action" value="save"><input type="hidden" name="next" value="/jobs/%s"><button class="primary" type="submit">Save job</button></form>
<form class="inline" method="post" action="/jobs/%s/decision"><input type="hidden" name="action" value="reject"><input type="hidden" name="next" value="/jobs/%s">
<select name="reason"><option value="">reason (optional)</option>%s</select><button class="danger" type="submit">Reject job</button></form>
<form class="inline" method="post" action="/jobs/%s/cv"><button type="submit">Generate tailored CV</button></form>
<form class="inline" method="post" action="/jobs/%s/application"><select name="status">%s</select>
<input type="date" name="date"><input type="text" name="notes" placeholder="notes" size="14"><button type="submit">Record application status</button></form>
<p class="small muted">The tool never submits applications or contacts employers. Track your manual progress here.</p></div>""" % (
        esc(record["id"]), esc(record["id"]), esc(record["id"]), esc(record["id"]),
        "".join('<option value="%s">%s</option>' % (esc(reason), esc(reason)) for reason in dashboard.REJECTION_REASONS),
        esc(record["id"]), esc(record["id"]), options_html(dashboard.APPLICATION_STATUSES, labels=dashboard.STATUS_LABELS))
    if cv_versions:
        cv_body = '<ul class="plain">%s</ul>' % "".join('<li><a href="/jobs/%s/cv">open draft</a> <span class="small muted">%s &middot; %s</span></li>' % (esc(record["id"]), esc(row["path"]), esc((row["created_at"] or "")[:19])) for row in cv_versions)
    else:
        cv_body = '<p class="small muted">No CV draft generated for this job yet.</p>'
    trail_body = '<ul class="plain small">%s</ul>' % "".join('<li>%s &middot; %s%s</li>' % (esc((item["created_at"] or "")[:19]), esc(item["event"]), (" &middot; " + esc(item["details"])) if item["details"] else "") for item in trail) if trail else '<p class="small muted">No events recorded yet.</p>'
    right = actions + '<div class="card"><h3>CV drafts</h3>%s</div>' % cv_body + '<div class="card"><h3>History for this job</h3>%s</div>' % trail_body + '<div class="card"><h3>Navigation</h3><p class="small"><a href="/jobs">&larr; back to jobs</a> &middot; <a href="/saved">saved</a> &middot; <a href="/applications">applications</a></p></div>'
    left = '<div class="card"><h3>Listing</h3><dl class="facts">%s</dl></div>' % facts_html + evaluation_card + '<div class="card"><h3>Requirements</h3><div class="wide"><table><thead><tr><th>Requirement</th><th>Kind</th><th>Category</th></tr></thead><tbody>%s</tbody></table></div></div>' % requirement_rows + text_card("Description", record["description"]) + text_card("Qualification text", record["qualifications"]) + text_card("Responsibilities", record["responsibilities"])
    return '<h2>%s <span class="id-chip" title="internal job id used by the CLI and the database">#%s</span> %s</h2><div class="two-col"><div>%s</div><div>%s</div></div>' % (esc(record["title"]), esc(record["id"]), status_badge(record), left, right)


def saved_page(records) -> str:
    if not records:
        return '<h2>Saved jobs</h2><div class="card"><p>No saved jobs yet.</p><p class="small muted">Open <a href="/jobs">Jobs</a>, pick a promising listing and choose Save.</p></div>'
    return ('<h2>Saved jobs <span class="small muted">%s</span></h2>' % len(records)) + job_table(records, actions=True) + '<p class="small muted">Save and reject act on the same status the CLI uses, for example <code>job-agent save JOB_ID</code>.</p>'


def applications_page(applications, candidates, statuses) -> str:
    rows = "".join("""<tr><td><a href="/jobs/%s">%s</a> <span class="small muted">%s</span></td><td><span class="badge status">%s</span></td>
<td>%s</td><td>%s</td><td>%s</td><td><form class="inline" method="post" action="/jobs/%s/application"><select name="status">%s</select>
<input type="date" name="date"><input type="text" name="notes" placeholder="notes" size="12"><button type="submit">Update</button></form></td></tr>""" % (
        esc(row["job_id"]), esc(row["title"]), esc(row["company"] or ""), esc(dashboard.STATUS_LABELS.get(row["status"], row["status"])),
        esc(row["application_date"] or "-"), esc((row["updated_at"] or "")[:19]), esc(row["notes"] or ""), esc(row["job_id"]),
        options_html(statuses, labels=dashboard.STATUS_LABELS, selected=row["status"])) for row in applications)
    if not rows:
        rows = '<tr><td colspan="6" class="muted">No application tracked yet.</td></tr>'
    picker = options_html([record["id"] for record in candidates], labels={record["id"]: "%s - %s (%s)" % (record["id"], record["title"], dashboard.STATUS_LABELS.get(record["status"], record["status"])) for record in candidates})
    tracker = '<p class="muted">Save or view a job first so it can be tracked here.</p>' if not candidates else ('<form class="filters" method="post" action="/applications">'
        '<div><label for="job_id">Job</label><select id="job_id" name="job_id">%s</select></div>'
        '<div><label for="status">Status</label><select id="status" name="status">%s</select></div>'
        '<div><label for="date">Applied on</label><input id="date" type="date" name="date"></div>'
        '<div><label for="notes">Notes</label><input id="notes" type="text" name="notes" size="22"></div>'
        '<div><label>&nbsp;</label><button class="primary" type="submit">Record</button></div></form>') % (picker, options_html(statuses, labels=dashboard.STATUS_LABELS))
    return ('<h2>Applications <span class="small muted">%s tracked</span></h2>' % len(applications)) + \
        '<div class="wide"><table><thead><tr><th>Job</th><th>Status</th><th>Applied on</th><th>Updated</th><th>Notes</th><th>Change status</th></tr></thead><tbody>%s</tbody></table></div>' % rows + \
        '<div class="card"><h3>Track another application</h3>%s<p class="small muted">This records your manual progress only. Applications are never submitted by this tool.</p></div>' % tracker


def history_page(events, search_events) -> str:
    searches = "".join('<li>%s &middot; %s%s</li>' % (esc((item["created_at"] or "")[:19]), esc(item["event"]), (" &middot; " + esc(item["details"])) if item["details"] else "") for item in search_events) or '<li class="muted">No searches recorded yet.</li>'
    rows = "".join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (esc((item["created_at"] or "")[:19]), esc(item["event"]), job_link(item["job_id"]) if item["job_id"] else "-", esc(item["details"] or "")) for item in events) or '<tr><td colspan="4" class="muted">No events recorded yet.</td></tr>'
    return ('<h2>History</h2><div class="card"><h3>Search history</h3><ul class="plain small">%s</ul>'
            '<p class="small muted">Searches store public job results only. No profile, CV or contact data is transmitted.</p></div>'
            '<h3>Audit log</h3><div class="wide"><table><thead><tr><th>When</th><th>Event</th><th>Job</th><th>Details</th></tr></thead><tbody>%s</tbody></table></div>') % (searches, rows)


def sources_page(statistics, summary, config) -> str:
    rows = "".join("""<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td>
<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td>%s</td><td class="small">%s</td></tr>""" % (
        esc(item["source"]), item["jobs"], esc(item["average_score"] if item["average_score"] is not None else "-"),
        item["recommended"], item["borderline"], item["excluded"], item["saved"], item["applied"], item["remote"],
        esc((item["newest"] or "")[:10]), esc(" | ".join(item["samples"]))) for item in statistics)
    if not rows:
        rows = '<tr><td colspan="11" class="muted">No jobs stored yet.</td></tr>'
    families = "".join('<li><strong>%s</strong>: %s</li>' % (esc(family), esc(", ".join(queries) if queries else "none")) for family, queries in config.get("search_queries", {}).items()) or '<li class="muted">No queries configured.</li>'
    preferences = config.get("location_preferences", {})
    arrangements = "".join('<li>%s: %s</li>' % (esc(name), count) for name, count in sorted(summary["by_arrangement"].items())) or '<li class="muted">No data</li>'
    statuses = "".join('<li>%s: %s</li>' % (esc(dashboard.STATUS_LABELS.get(name, name)), count) for name, count in sorted(summary["by_status"].items())) or '<li class="muted">No data</li>'
    return ('<h2>Sources and statistics</h2>'
            '<div class="wide"><table><thead><tr><th>Source</th><th class="num">Jobs</th><th class="num">Avg score</th><th class="num">Recommended</th><th class="num">Borderline</th>'
            '<th class="num">Excluded</th><th class="num">Saved</th><th class="num">Applied</th><th class="num">Remote</th><th>Newest</th><th>Top titles</th></tr></thead><tbody>%s</tbody></table></div>'
            '<div class="three-col"><div class="card"><h3>Work arrangements</h3><ul class="plain">%s</ul></div>'
            '<div class="card"><h3>Statuses</h3><ul class="plain">%s</ul></div>'
            '<div class="card"><h3>Location preferences</h3><dl class="facts"><dt>Origin</dt><dd>%s</dd><dt>Radius</dt><dd>%s km</dd><dt>Remote beyond radius</dt><dd>%s</dd></dl></div>'
            '<div class="card"><h3>Configured search queries</h3><ul class="plain small">%s</ul></div></div>') % (
                rows, arrangements, statuses, esc(preferences.get("origin", "unknown")), esc(preferences.get("max_distance_km", "-")),
                esc(preferences.get("remote_only_beyond_distance", "-")), families)


def search_page(state, search_events, source_names, configured_queries) -> str:
    history = "".join('<li>%s &middot; %s%s</li>' % (esc((item["created_at"] or "")[:19]), esc(item["event"]), (" &middot; " + esc(item["details"])) if item["details"] else "") for item in search_events) or '<li class="muted">No searches recorded yet.</li>'
    return """<h2>Search public job sources</h2>
<div class="two-col">
<div>
<div class="card"><h3>Quick search</h3>
<form class="filters" method="post" action="/search">
<div><label for="query">Query</label><input id="query" type="text" name="query" placeholder="Data Analyst" required></div>
<div><label for="source">Source</label><select id="source" name="source">%s</select></div>
<div><label for="location">Location</label><input id="location" type="text" name="location" placeholder="optional city filter"></div>
<div><label>&nbsp;</label><button class="primary" type="submit">Run one query</button></div>
</form>
<p class="small muted">Only the public query text, and an optional location filter, are sent to the selected public source.</p></div>
<div class="card"><h3>Full configured search</h3>
<form method="post" action="/search"><input type="hidden" name="mode" value="configured">
<p class="small">Runs all <strong>%s</strong> queries configured in <code>data/search_config.json</code> through all %s public sources (%s), exactly like <code>job-agent search</code> without a query. This can take several minutes; progress is shown below.</p>
<button type="submit">Run configured search</button></form></div>
<h3>Search status</h3>
<div class="card" id="search-status"><p class="small muted">Loading status...</p></div>
</div>
<div>
<div class="card"><h3>Progress log</h3><ul class="plain small" id="search-log"><li class="muted">Nothing logged yet.</li></ul></div>
<div class="card"><h3>Source errors</h3><ul class="plain small" id="search-errors"><li class="muted">No source errors.</li></ul></div>
<div class="card"><h3>Recent searches</h3><ul class="plain small">%s</ul></div>
</div>
</div>
%s""" % (options_html(source_names), configured_queries, len(source_names), esc(", ".join(source_names)), history, SEARCH_SCRIPT)


def error_page(status: int, message: str, database=None) -> str:
    return page(str(status), "", '<div class="card"><h2>%s</h2><p>%s</p><p class="small"><a href="/">back to overview</a></p></div>' % (status, esc(message)), database=database)
