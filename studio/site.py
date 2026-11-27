"""制作確認サイト（静的HTML）の生成。

- runs/ の全履歴を読み、削除しない（過去の結果も全て掲載）。
- 非公開の入力（public_ok=false の画像）から派生した画像、および publish: false のランの画像は掲載しない。
- 参考画像は public_ok: true のものだけ掲載。
- 承認状態は approvals/approvals.yaml（ユーザーのみ編集）から表示。
"""
from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Any

from .allowlist import Allowlist
from .util import REPO_ROOT, load_json, load_yaml, now_iso

APPROVALS_FILE = REPO_ROOT / "approvals" / "approvals.yaml"


def collect(runs_dir: Path, al: Allowlist) -> dict[str, Any]:
    approvals = (load_yaml(APPROVALS_FILE, {}) or {}).get("approvals") or {}
    runs = []
    for rj in sorted(runs_dir.glob("*/run.json"), reverse=True):
        rd = rj.parent
        run = load_json(rj)
        state = load_json(rd / "state.json", {})
        stages = []
        for name, ss in (state.get("stages") or {}).items():
            private = bool(ss.get("private_inputs"))
            publishable = run.get("publish", True) and not private
            rounds = []
            for rr in ss.get("rounds", []):
                cands = []
                for c in rr.get("candidates", []):
                    meta = load_json((rd / c["image"]).with_suffix(".json"), {})
                    cands.append({"image": c["image"] if publishable else None, "score": c.get("score"),
                                  "params": meta.get("params"), "seconds": meta.get("seconds"),
                                  "evaluation": meta.get("evaluation"), "created_at": meta.get("created_at")})
                rounds.append({"round": rr.get("round"), "best": rr.get("best"), "best_score": rr.get("best_score"),
                               "changes": rr.get("next_changes", []), "vs_first": rr.get("vs_first"),
                               "candidates": cands})
            key = f"{run['run_id']}/{name}"
            ap = approvals.get(key, {})
            stages.append({
                "name": name, "status": ss.get("status"), "stop_reason": ss.get("stop_reason"),
                "best": (ss.get("best") or {}) if publishable else {"score": (ss.get("best") or {}).get("score")},
                "comparison": ss.get("comparison") if publishable else None,
                "publishable": publishable, "private_note": "非公開入力の派生物のため画像は非掲載" if private else None,
                "rounds": rounds, "approval": ap.get("status", "未承認"), "approval_note": ap.get("note"),
                "assigned_to": ap.get("assigned_to") or (run.get("assign_to") or {}).get("targets") or [],
            })
        timings = []
        for tf in sorted(rd.glob("timings-*.json")):
            tj = load_json(tf, {})
            timings.append({"actions_run": tj.get("actions_run"), "runtime": tj.get("runtime"),
                            "steps": [x for x in tj.get("steps", []) if x.get("seconds")],
                            "marks": tj.get("marks", []), "session": tj.get("session")})
        sessions = state.get("sessions") or []
        runs.append({**{k: run.get(k) for k in ("run_id", "job_id", "title", "status", "backend", "backend_info",
                                                 "created_at", "finished_at", "elapsed_min", "models",
                                                 "errors_recovered", "fatal_error", "assign_to", "timing")},
                     "runtime": run.get("runtime") or (sessions[-1].get("runtime") if sessions else None) or "native",
                     "actions_runs": [x.get("actions_run_url") for x in sessions if x.get("actions_run_url")]
                                     or run.get("actions_runs") or [],
                     "timings": timings,
                     "job": state.get("job"), "stages": stages,
                     "plan": (rd / "plan.md").read_text(encoding="utf-8") if (rd / "plan.md").exists() else ""})
    refs = [{"id": i.id, "path": i.raw.get("path"), "note": i.raw.get("note")}
            for i in al.images.values() if i.public_ok and i.raw.get("path")]
    return {"generated_at": now_iso(), "runs": runs, "references": refs}


def build(runs_dir: Path, out: Path, al: Allowlist) -> dict[str, Any]:
    data = collect(runs_dir, al)
    if out.exists():
        shutil.rmtree(out)
    (out / "runs").mkdir(parents=True)
    # 掲載可能な画像だけコピー
    for run in data["runs"]:
        for st in run["stages"]:
            if not st["publishable"]:
                continue
            files = {st["best"].get("image"), st.get("comparison")}
            for rr in st["rounds"]:
                files.update(c["image"] for c in rr["candidates"])
            for f in filter(None, files):
                src = runs_dir / run["run_id"] / f
                if src.exists():
                    dst = out / "runs" / run["run_id"] / f
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
    for r in data["references"]:
        src = REPO_ROOT / r["path"]
        if src.exists():
            dst = out / "refs" / Path(r["path"]).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            r["site_path"] = f"refs/{dst.name}"
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (out / "index.html").write_text(PAGE.replace("__DATA__", blob), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return {"runs": len(data["runs"]), "out": str(out)}


PAGE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Illustration AI Studio — 制作確認</title>
<style>
:root{--bg:#14151a;--panel:#1d1f26;--line:#2c2f3a;--fg:#e8e8ec;--mute:#9a9caa;--acc:#7cc4ff;--ok:#6fd49a;--ng:#ff8a8a;--warn:#f3c969}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,"Hiragino Sans","Noto Sans JP",sans-serif}
header{padding:16px 24px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:18px;margin:0}small,.mute{color:var(--mute)}main{display:grid;grid-template-columns:300px 1fr;min-height:calc(100vh - 60px)}
nav{border-right:1px solid var(--line);overflow:auto;max-height:calc(100vh - 60px)}
nav input{width:calc(100% - 24px);margin:12px;padding:8px;background:var(--panel);border:1px solid var(--line);color:var(--fg);border-radius:6px}
.run{padding:10px 14px;border-bottom:1px solid var(--line);cursor:pointer}.run:hover,.run.on{background:var(--panel)}
.run b{display:block}section{padding:20px 28px;overflow:auto;max-height:calc(100vh - 60px)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin:0 0 18px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.grid figure{margin:0;background:#0f1014;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.grid img,.best img,.cmp img{width:100%;display:block;background:repeating-conic-gradient(#222 0 25%,#2a2a2a 0 50%) 0 0/16px 16px}
figcaption{padding:6px 8px;font-size:12px;color:var(--mute)}.best{display:grid;grid-template-columns:minmax(220px,360px) 1fr;gap:18px}
.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line);margin-right:6px}
.ap-承認{color:var(--ok);border-color:var(--ok)}.ap-却下{color:var(--ng);border-color:var(--ng)}.ap-未承認{color:var(--warn);border-color:var(--warn)}
pre{white-space:pre-wrap;background:#0f1014;padding:10px;border-radius:6px;border:1px solid var(--line);font-size:12px;max-height:260px;overflow:auto}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
button{background:transparent;color:var(--acc);border:1px solid var(--acc);border-radius:6px;padding:3px 10px;cursor:pointer}
details summary{cursor:pointer;color:var(--acc)}.empty{padding:40px;color:var(--mute)}
@media(max-width:800px){main{grid-template-columns:1fr}nav{max-height:240px}.best{grid-template-columns:1fr}}
</style></head><body>
<header><h1>Illustration AI Studio — 制作確認</h1><small id="gen"></small>
<small>自動評価は制作途中の参考値です。採用はユーザーが判断します。</small></header>
<main><nav><input id="q" placeholder="検索（ジョブ・プロンプト・モデル）"><div id="list"></div></nav><section id="view"></section></main>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('#gen').textContent='更新: '+D.generated_at+' / '+D.runs.length+' ラン';
function list(){const q=$('#q').value.toLowerCase();$('#list').innerHTML=D.runs.filter(r=>JSON.stringify(r).toLowerCase().includes(q)).map(r=>
`<div class="run" data-id="${esc(r.run_id)}"><b>${esc(r.title||r.job_id)}</b><small>${esc(r.run_id)}<br>${esc(r.status)} · ${esc(r.backend)} · ${r.elapsed_min??'-'}分</small></div>`).join('')||'<div class="empty">該当なし</div>';
document.querySelectorAll('.run').forEach(e=>e.onclick=()=>show(e.dataset.id));}
function img(run,p){return p?`runs/${encodeURIComponent(run)}/${p}`:''}
function evalTable(e){if(!e)return'';return `<table><tr><th>指標</th><th>スコア</th><th>根拠</th><th>限界</th></tr>`+Object.entries(e.metrics||{}).map(([k,v])=>
`<tr><td>${esc(k)}</td><td>${v.score??'—'}</td><td>${esc(v.rationale)}</td><td class="mute">${esc(v.limitations)}</td></tr>`).join('')+`</table><p class="mute">${esc(e.note)}</p>`}
const CLIP=[];function copy(t){navigator.clipboard&&navigator.clipboard.writeText(t)}
function btn(label,t){CLIP.push(t);return `<button onclick="copy(CLIP[${CLIP.length-1}])">${label}</button>`}
function show(id){const r=D.runs.find(x=>x.run_id===id);document.querySelectorAll('.run').forEach(e=>e.classList.toggle('on',e.dataset.id===id));
let h=`<div class="card"><h2 style="margin:0 0 6px">${esc(r.title||r.job_id)}</h2><span class="tag">${esc(r.status)}</span><span class="tag">${esc(r.backend)}</span>
<span class="tag">${r.elapsed_min??'-'} 分</span><span class="tag">復旧 ${r.errors_recovered??0} 回</span><span class="tag">${esc(r.runtime)}</span>
${(r.actions_runs||[]).map((u,i)=>`<a class="tag" href="${esc(u)}" target="_blank" rel="noopener">Actions #${i+1}</a>`).join('')}
${r.timing&&r.timing.first_generation_seconds?`<p class="mute">モデル読込 ${r.timing.model_load_seconds_total}s · 1枚目 ${Math.round(r.timing.first_generation_seconds)}s · 2枚目以降平均 ${r.timing.later_generation_seconds_avg??'—'}s</p>`:''}
${(r.timings||[]).length?`<details><summary>実行時間の内訳</summary>${r.timings.map(t=>`<p><a href="${esc(t.actions_run)}" target="_blank" rel="noopener">${esc(t.actions_run)}</a></p><table>${t.steps.map(s=>`<tr><td>${esc(s.name)}</td><td>${s.seconds}s</td></tr>`).join('')}${(t.marks||[]).filter(m=>m.seconds!=null).map(m=>`<tr><td class="mute">${esc(m.mark)}</td><td>${m.seconds}s</td></tr>`).join('')}</table>`).join('')}</details>`:''}
<p class="mute">${esc(r.created_at)} → ${esc(r.finished_at)}</p>
<p>使用モデル: ${(r.models||[]).map(m=>`<span class="tag">${esc(m.kind)}: ${esc(m.name||m.id)}</span>`).join('')||'<span class="mute">なし</span>'}</p>
${r.fatal_error?`<pre>${esc(JSON.stringify(r.fatal_error,null,1))}</pre>`:''}
<details><summary>制作計画</summary><pre>${esc(r.plan)}</pre></details>
<details><summary>制作指示（ジョブ）</summary><pre>${esc(JSON.stringify(r.job,null,1))}</pre>${btn('ジョブをコピー（再利用）',JSON.stringify(r.job,null,1))}</details></div>`;
for(const s of r.stages){const best=s.rounds.flatMap(x=>x.candidates).find(c=>c.image===s.best.image)||{};const p=best.params||{};
h+=`<div class="card"><h3 style="margin:0 0 8px">${esc(s.name)} <span class="tag ap-${esc(s.approval)}">${esc(s.approval)}</span>
<span class="tag">${esc(s.stop_reason)}</span>${(s.assigned_to||[]).map(a=>`<span class="tag">→ ${esc(a)}</span>`).join('')}</h3>
${s.private_note?`<p class="mute">${esc(s.private_note)}</p>`:''}
<div class="best"><div>${s.best.image?`<img src="${img(r.run_id,s.best.image)}" alt="best">`:'<div class="empty">画像なし</div>'}
<small>ベスト score ${s.best.score??'—'}</small></div><div>
<table><tr><th>プロンプト</th><td>${esc(p.prompt)}</td></tr><tr><th>ネガティブ</th><td>${esc(p.negative_prompt)}</td></tr>
<tr><th>モデル</th><td>${esc(p.model)}</td></tr><tr><th>LoRA</th><td>${esc((p.loras||[]).map(l=>l.id+':'+l.weight).join(', '))}</td></tr>
<tr><th>シード</th><td>${esc(p.seed)}</td></tr><tr><th>設定</th><td>${esc(['steps','cfg','scheduler','width','height','denoise'].map(k=>k+'='+p[k]).join(' '))}</td></tr>
<tr><th>生成時間</th><td>${best.seconds??'—'} 秒</td></tr></table>
${btn('設定をコピー',JSON.stringify(p,null,1))}
<details><summary>評価結果</summary>${evalTable(best.evaluation)}</details></div></div>
${s.comparison?`<h4>改善前後</h4><div class="cmp"><img src="${img(r.run_id,s.comparison)}" alt="比較"></div>`:''}
<details><summary>制作履歴（${s.rounds.length} ラウンド）</summary>`+s.rounds.map(rr=>`<h4>ラウンド ${rr.round} — ベスト ${rr.best_score??'—'}
${rr.vs_first&&rr.vs_first.overall_delta!=null?`<small>（初回比 ${rr.vs_first.overall_delta>=0?'+':''}${rr.vs_first.overall_delta}）</small>`:''}</h4>
${rr.changes.length?`<p class="mute">次の調整: ${esc(rr.changes.join(' / '))}</p>`:''}
<div class="grid">${rr.candidates.map(c=>`<figure>${c.image?`<img loading="lazy" src="${img(r.run_id,c.image)}">`:''}<figcaption>score ${c.score??'—'} · seed ${esc(c.params&&c.params.seed)} · ${c.seconds??'-'}s</figcaption></figure>`).join('')}</div>`).join('')+`</details></div>`;}
if(D.references.length)h+=`<div class="card"><h3>公開許可済み参考画像</h3><div class="grid">${D.references.map(x=>`<figure><img src="${esc(x.site_path)}"><figcaption>${esc(x.id)}</figcaption></figure>`).join('')}</div></div>`;
$('#view').innerHTML=h;}
$('#q').oninput=list;list();if(D.runs.length)show(D.runs[0].run_id);else $('#view').innerHTML='<div class="empty">まだ制作結果がありません。</div>';
</script></body></html>
"""
