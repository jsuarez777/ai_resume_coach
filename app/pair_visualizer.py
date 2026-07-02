#!/usr/bin/env python3
"""Flask viewer for job-resume pairs: jobs list | job detail | resume carousel.

Loads a pairs_<ts>.jsonl (default: latest under data/resume/), joins each pair's
resume (sibling resumes_<ts>.jsonl) and job (indexed from data/job_description/),
and serves a 3-pane UI:
  - left 25%  : jobs that have paired resumes
  - middle 40%: the selected job
  - right 35% : its paired resumes, one at a time, with prev/next (wraps around)

Run from the project root:

    python app/pair_visualizer.py            # uses the latest pairs file
    python app/pair_visualizer.py --pairs data/resume/v1/pairs_20260629_093620.jsonl --port 5000
"""

from __future__ import annotations

import argparse
import math
import sys
import threading
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.resume_job_evaluator as ev  # noqa: E402 - reuse data loaders

app = Flask(__name__)

# Populated in main(): job_id -> job dict; job_id -> [{resume_id, fit_level, writing_style, resume}]
JOBS: dict[str, dict] = {}
JOB_RESUMES: dict[str, list[dict]] = {}


def _job_label(job: dict) -> str:
    c = job.get("company", {})
    req = job.get("requirements", {})
    bits = [c.get("name"), c.get("industry"), req.get("experience_level")]
    return "  ·  ".join(b for b in bits if b) or "(job)"


def _norm_str(skill: str) -> str:
    """Normalized, alpha-sorted token set for a skill (matches the labeler)."""
    return ", ".join(sorted(ev.normalize_skill_tokens(skill)))


def _norm_map(job: dict, resumes: list[dict]) -> dict[str, str]:
    """raw skill string -> normalized token string, for every skill on screen."""
    req = job.get("requirements", {})
    skills = set(req.get("required_skills", [])) | set(req.get("preferred_skills", []))
    for item in resumes:
        for s in item["resume"].get("skills", []):
            skills.add(s.get("name", ""))
    return {sk: _norm_str(sk) for sk in skills if sk}


def _match_ok(a: set[str], b: set[str]) -> bool:
    """Solid match: with n = min(#tokens) -> need n shared if n < 3, else ceil(n/2) (>=50%)."""
    n = min(len(a), len(b))
    if n == 0:
        return False
    needed = n if n < 3 else math.ceil(n / 2)
    return len(a & b) >= needed


def _skill_matches(resume: dict, required: list[str]) -> list[list[int]]:
    """Per resume skill, the 1-based numbers of required skills it solidly matches."""
    req_tokens = [ev.normalize_skill_tokens(s) for s in required]
    out = []
    for s in resume.get("skills", []):
        toks = ev.normalize_skill_tokens(s.get("name", ""))
        out.append([i + 1 for i, rt in enumerate(req_tokens) if _match_ok(toks, rt)])
    return out


@app.route("/")
def index():
    return PAGE


FIT_ORDER = ["Excellent", "Good", "Partial", "Poor", "Mismatch"]


@app.route("/api/jobs")
def api_jobs():
    items = []
    for jid in JOB_RESUMES:
        if jid not in JOBS:
            continue
        counts = dict.fromkeys(FIT_ORDER, 0)
        for it in JOB_RESUMES[jid]:
            if it.get("fit_level") in counts:
                counts[it["fit_level"]] += 1
        items.append(
            {
                "job_id": jid,
                "label": _job_label(JOBS[jid]),
                "n_resumes": len(JOB_RESUMES[jid]),
                "fits": [counts[f] for f in FIT_ORDER],
            }
        )
    items.sort(key=lambda x: x["label"])
    return jsonify(items)


@app.route("/api/job/<job_id>")
def api_job(job_id: str):
    if job_id not in JOBS:
        abort(404)
    job = JOBS[job_id]
    base = JOB_RESUMES.get(job_id, [])
    required = job.get("requirements", {}).get("required_skills", [])
    resumes = [
        {
            **it,
            "metrics": ev.analyze_pair(it["resume"], job),
            "skill_match": _skill_matches(it["resume"], required),
        }
        for it in base
    ]
    return jsonify({"job": job, "resumes": resumes, "norms": _norm_map(job, base)})


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Job / Resume Pairs</title>
<style>
  * { box-sizing: border-box; }
  html { font-size: 16px; }
  body { margin: 0; font-family: -apple-system, Segoe UI, Roboto, sans-serif; height: 100vh;
         display: flex; flex-direction: column; color: #1e293b; font-size: 0.9rem; }
  #toolbar { flex: 0 0 auto; display: flex; align-items: center; gap: 8px;
             padding: 6px 12px; border-bottom: 1px solid #e2e8f0; background: #fff; }
  #toolbar .title { font-weight: 700; }
  #toolbar .spacer { flex: 1; }
  #toolbar button { padding: 2px 10px; border: 1px solid #cbd5e1; background: #f1f5f9;
                    border-radius: 6px; cursor: pointer; }
  #toolbar button:hover { background: #e2e8f0; }
  #panes { flex: 1 1 auto; display: flex; min-height: 0; }
  .pane { height: 100%; overflow-y: auto; padding: 12px 16px; }
  #jobs   { width: 25%; background: #f8fafc; }
  #job    { width: 40%; }
  #resume { flex: 1 1 0; min-width: 180px; background: #f8fafc; }
  .gutter { flex: 0 0 6px; cursor: col-resize; background: #e2e8f0; }
  .gutter:hover { background: #94a3b8; }
  h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: .05em; color: #64748b;
       margin: 0 0 10px; position: sticky; top: -12px; background: inherit; padding: 6px 0; }
  .jobitem { padding: 8px 10px; border-radius: 6px; cursor: pointer; margin-bottom: 4px;
             border: 1px solid transparent; }
  .jobitem:hover { background: #eef2ff; }
  .jobitem.sel { background: #e0e7ff; border-color: #c7d2fe; }
  .jobitem small { color: #64748b; }
  .fitbar { display: flex; gap: 2px; margin-top: 4px; }
  .fitbox { flex: 1; text-align: center; font-size: 0.66rem; padding: 1px 0;
            border-radius: 3px; border: 1px solid #e2e8f0; }
  .fitbox.on { background: #dcfce7; border-color: #bbf7d0; color: #15803d; }
  .fitbox.off { background: #fef2f2; border-color: #fecaca; color: #b91c1c; }
  .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px;
          margin-bottom: 10px; }
  .k { color: #64748b; font-size: 0.78rem; text-transform: uppercase; letter-spacing: .04em; }
  ul, ol { margin: 4px 0 0; padding-left: 22px; }
  li { margin: 2px 0; }
  .norm { color: #dc2626; font-weight: 700; margin-left: 1.4em; font-size: 0.85em; }
  .norm.matched { color: #16a34a; }
  .mtag { color: #475569; font-weight: 600; }
  .metrics { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .metric { font-size: 0.78rem; padding: 1px 9px; border-radius: 999px;
            border: 1px solid #e2e8f0; background: #f8fafc; }
  .metric.bad { background: #fef2f2; border-color: #fecaca; color: #b91c1c; }
  .metric.ok { background: #f0fdf4; border-color: #bbf7d0; color: #15803d; }
  .reqhit { background: #dcfce7; border-radius: 4px; }
  .tid { font-family: ui-monospace, monospace; font-size: 0.72rem; color: #94a3b8;
         margin-top: 4px; word-break: break-all; }
  .copybtn { font-size: 0.68rem; padding: 0 6px; margin-left: 6px; border: 1px solid #cbd5e1;
             background: #f1f5f9; border-radius: 4px; cursor: pointer; }
  .copybtn:hover { background: #e2e8f0; }
  .navbar { display: flex; align-items: center; gap: 10px; position: sticky; top: -12px;
            background: #f8fafc; padding: 8px 0; z-index: 2; }
  .navbar button { padding: 4px 12px; border: 1px solid #c7d2fe; background: #eef2ff;
                   border-radius: 6px; cursor: pointer; font-size: 14px; }
  .navbar button:hover { background: #e0e7ff; }
  .pill { display: inline-block; background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 999px;
          padding: 1px 9px; font-size: 0.75rem; margin-right: 6px; }
  .muted { color: #94a3b8; }
</style></head>
<body>
  <div id="toolbar">
    <span class="title">Job / Resume Pairs</span>
    <span class="spacer"></span>
    <span>Font</span>
    <button id="fdec">A−</button>
    <button id="finc">A+</button>
    <button id="freset">Reset</button>
  </div>
  <div id="panes">
    <div id="jobs" class="pane"><h2>Jobs</h2><div id="joblist"></div></div>
    <div class="gutter"></div>
    <div id="job" class="pane"><h2>Job</h2><div id="jobdetail" class="muted">Select a job.</div></div>
    <div class="gutter"></div>
    <div id="resume" class="pane">
      <div class="navbar">
        <button id="prev">‹ Prev</button>
        <span id="counter" class="muted">—</span>
        <button id="next">Next ›</button>
        <button id="copypair">Copy pair</button>
      </div>
      <div id="resumedetail" class="muted">—</div>
    </div>
  </div>
<script>
let resumes = [], ridx = 0, NORMS = {}, curJob = null;

function esc(s){ return (s==null?'':String(s)).replace(/[&<>]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function copyText(text, btn){ navigator.clipboard.writeText(text).then(()=>{ if(btn){ const o=btn.textContent; btn.textContent='✓'; setTimeout(()=>btn.textContent=o,1000); } }); }
function list(arr){ return '<ul>'+(arr||[]).map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>'; }
function normLine(skill){ const n = NORMS[skill]||''; return n ? '<div class="norm">'+esc(n)+'</div>' : ''; }
function skillList(arr){ return '<ul>'+(arr||[]).map(x=>'<li>'+esc(x)+normLine(x)+'</li>').join('')+'</ul>'; }
function skillListNum(arr){ return '<ol>'+(arr||[]).map((x,i)=>'<li data-req="'+(i+1)+'">'+esc(x)+normLine(x)+'</li>').join('')+'</ol>'; }
function highlightReq(nums){ const set=new Set(nums); document.querySelectorAll('#jobdetail li[data-req]').forEach(li=>li.classList.toggle('reqhit', set.has(parseInt(li.dataset.req)))); }

const FIT_ABBR = ['Ex','Gd','Pa','Po','Mm'], FIT_NAME = ['Excellent','Good','Partial','Poor','Mismatch'];

async function loadJobs(){
  const jobs = await (await fetch('/api/jobs')).json();
  document.getElementById('joblist').innerHTML = jobs.map(j => {
    const bar = (j.fits||[]).map((n,i)=>`<div class="fitbox ${n>0?'on':'off'}" title="${FIT_NAME[i]}">${FIT_ABBR[i]} ${n}</div>`).join('');
    return `<div class="jobitem" data-id="${j.job_id}">${esc(j.label)}<br><small>${j.n_resumes} resume(s)</small><div class="fitbar">${bar}</div></div>`;
  }).join('');
  document.querySelectorAll('.jobitem').forEach(el =>
    el.onclick = () => selectJob(el.dataset.id, el));
}

async function selectJob(id, el){
  document.querySelectorAll('.jobitem').forEach(e => e.classList.remove('sel'));
  if (el) el.classList.add('sel');
  const data = await (await fetch('/api/job/'+id)).json();
  NORMS = data.norms || {};
  curJob = data.job;
  renderJob(data.job);
  resumes = data.resumes; ridx = 0; renderResume();
}

function renderJob(j){
  const c = j.company||{}, r = j.requirements||{}, d = j.description||{}, m = j.metadata||{};
  document.getElementById('jobdetail').innerHTML =
    `<div class="card"><div class="k">Company</div>${esc(c.name)} · ${esc(c.industry)} · ${esc(c.size)} · ${esc(c.location)}
       <div style="margin-top:6px"><span class="pill">${esc(r.experience_level)} · ${esc(r.experience_years)} yrs</span>
       <span class="pill">${m.is_niche_role?'niche':'standard'}</span></div>
       <div class="tid">job trace_id: ${esc(m.trace_id)}<button class="copybtn" onclick="copyText('${esc(m.trace_id)}', this)">copy</button></div></div>
     <div class="card"><div class="k">Summary</div>${esc(j.summary)}</div>
     <div class="card"><div class="k">Description</div>${esc(d.overview)}${list(d.responsibilities)}</div>
     <div class="card"><div class="k">Required skills</div>${skillListNum(r.required_skills)}
       <div class="k" style="margin-top:8px">Preferred</div>${skillList(r.preferred_skills)}
       <div class="k" style="margin-top:8px">Education</div>${esc(r.education)}</div>`;
}

function renderResume(){
  const counter = document.getElementById('counter');
  const box = document.getElementById('resumedetail');
  if (!resumes.length){ counter.textContent='—'; box.innerHTML='<span class="muted">No resumes.</span>'; return; }
  counter.textContent = `Resume ${ridx+1} of ${resumes.length}`;
  const item = resumes[ridx], r = item.resume||{}, ci = r.contact_info||{}, m = r.metadata||{};
  const mt = item.metrics||{}, sm = item.skill_match||[];
  const flag = (label, on) => `<span class="metric ${on?'bad':'ok'}">${label}: ${on?'yes':'no'}</span>`;
  const metricsHtml =
    `<div class="metrics">
       <span class="metric">Jaccard: <b>${mt.skills_overlap_jaccard!=null?mt.skills_overlap_jaccard:'—'}</b></span>
       ${flag('Exp mismatch', mt.experience_mismatch)}
       ${flag('Seniority mismatch', mt.seniority_mismatch)}
       ${flag('Missing core', mt.missing_core_skills)}
       ${flag('Hallucinated', mt.hallucinated_skills)}
       ${flag('Awkward lang', mt.awkward_language)}
     </div>`;
  box.innerHTML =
    `<div class="card"><span class="pill">${esc(item.fit_level)}</span><span class="pill">${esc(item.writing_style)}</span>
       ${metricsHtml}
       <div style="margin-top:6px"><b>${esc(ci.name)}</b> · ${esc(ci.location)} · ${esc(ci.email)} · ${esc(ci.phone)}</div>
       <div class="tid">resume trace_id: ${esc(m.trace_id)}<button class="copybtn" onclick="copyText('${esc(m.trace_id)}', this)">copy</button></div></div>
     <div class="card"><div class="k">Education</div>` +
       (r.education||[]).map(e=>`<div>• ${esc(e.degree)} — ${esc(e.institution)} (${esc(e.graduation_date)})${e.gpa!=null?' · GPA '+esc(e.gpa):''}</div>`).join('') + `</div>
     <div class="card"><div class="k">Experience</div>` +
       (r.experience||[]).map(x=>`<div style="margin-bottom:6px"><b>${esc(x.title)}</b> @ ${esc(x.company)} (${esc(x.start_date)} – ${esc(x.end_date||'present')})`
         + list(x.responsibilities) + (x.achievements||[]).map(a=>'<div class="muted">★ '+esc(a)+'</div>').join('') + `</div>`).join('') + `</div>
     <div class="card"><div class="k">Skills</div>` +
       (r.skills||[]).map((s,i)=>{
         const matched = sm[i]||[];
         const cls = matched.length ? 'norm matched' : 'norm';
         const tag = matched.length ? ' <span class="mtag">[→ '+matched.join(', ')+']</span>' : '';
         const nrm = NORMS[s.name]||'';
         return `<div>• ${esc(s.name)} (${esc(s.proficiency_level)}${s.years!=null?', '+esc(s.years)+'y':''})`
           + (nrm?`<div class="${cls}">${esc(nrm)}${tag}</div>`:'') + `</div>`;
       }).join('') + `</div>`;
  highlightReq([...new Set(sm.flat())]);
}

document.getElementById('prev').onclick = () => { if(resumes.length){ ridx=(ridx-1+resumes.length)%resumes.length; renderResume(); } };
document.getElementById('next').onclick = () => { if(resumes.length){ ridx=(ridx+1)%resumes.length; renderResume(); } };
document.getElementById('copypair').onclick = () => {
  if (!resumes.length || !curJob) return;
  const jid = (curJob.metadata||{}).trace_id||'';
  const rid = ((resumes[ridx].resume||{}).metadata||{}).trace_id||'';
  const b = document.getElementById('copypair');
  navigator.clipboard.writeText(`job_trace_id=${jid} resume_trace_id=${rid}`).then(()=>{
    const o = b.textContent; b.textContent='Copied!'; setTimeout(()=>b.textContent=o, 1200);
  });
};

// font size control
let fs = 16;
function applyFs(){ document.documentElement.style.fontSize = fs + 'px'; }
document.getElementById('finc').onclick = () => { fs = Math.min(30, fs+1); applyFs(); };
document.getElementById('fdec').onclick = () => { fs = Math.max(10, fs-1); applyFs(); };
document.getElementById('freset').onclick = () => { fs = 16; applyFs(); };

// draggable pane widths
document.querySelectorAll('.gutter').forEach(g => {
  g.addEventListener('mousedown', e => {
    e.preventDefault();
    const pane = g.previousElementSibling;
    const startX = e.clientX, startW = pane.getBoundingClientRect().width;
    function move(ev){ pane.style.width = Math.max(120, startW + ev.clientX - startX) + 'px'; }
    function up(){ document.removeEventListener('mousemove', move); document.removeEventListener('mouseup', up); document.body.style.userSelect=''; }
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
});

loadJobs();
</script>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=None, help="Path to a pairs_*.jsonl (default: latest)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")
    args = parser.parse_args()

    if args.pairs:
        pairs_file = Path(args.pairs).resolve()
    else:
        files = ev._find_pairs_files()
        if not files:
            sys.exit(f"No pairs_*.jsonl under {ev.RESUMES_DIR}. Generate resumes first.")
        pairs_file = files[0]
    if not pairs_file.is_file():
        sys.exit(f"Pairs file not found: {pairs_file}")

    resumes_file = pairs_file.with_name(pairs_file.name.replace("pairs_", "resumes_", 1))
    if not resumes_file.is_file():
        sys.exit(f"Sibling resumes file not found: {resumes_file}")

    JOBS.update(ev._build_job_index())
    resumes = ev._index_by_trace(ev._load_jsonl(resumes_file))
    for p in ev._load_jsonl(pairs_file):
        resume = resumes.get(p.get("resume_trace_id"))
        if resume is None or p.get("job_trace_id") not in JOBS:
            continue
        JOB_RESUMES.setdefault(p["job_trace_id"], []).append(
            {
                "resume_id": p.get("resume_trace_id"),
                "fit_level": p.get("fit_level"),
                "writing_style": p.get("writing_style"),
                "resume": resume,
            }
        )

    try:
        shown = pairs_file.relative_to(PROJECT_ROOT)
    except ValueError:
        shown = pairs_file
    url = f"http://127.0.0.1:{args.port}"
    print(f"Loaded {shown}: {len(JOB_RESUMES)} job(s) with pairs.")
    print(f"Open {url}")
    if not args.no_browser:
        # open once the server is up (app.run blocks, so fire on a short timer)
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
