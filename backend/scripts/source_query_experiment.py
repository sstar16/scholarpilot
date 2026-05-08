#!/usr/bin/env python3
"""
全数据源查询语法实测（2026-04-24）。

目的：把"LLM 能不能用 AND/OR/短语/字段限定"从"历史踩坑记忆"升级成当前实测数据。
对 10 个源跑 ~6 种 query 变体，记录 (total, elapsed, first_title, status)，
结果写进 tmp/source_query_experiment.json 供后续 markdown 报告用。

成本：
- 免费源（8 个）：0 元
- PatentHub：5 次 × ¥0.1 = ¥0.5（详情/搜索共享计费，2026-04-24 工作人员确认）
- Lens / EPO：有 token 配额，不花钱

跑法：python backend/scripts/source_query_experiment.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ─────────────── 环境 ───────────────
ROOT = Path(__file__).resolve().parent.parent.parent
ENV_PATH = ROOT / ".env"


def load_env(p: Path) -> dict:
    env = {}
    if p.exists():
        for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, _, v = ln.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env(ENV_PATH)
LENS_TOKEN = ENV.get("LENS_API_TOKEN", "")
EPO_KEY = ENV.get("EPO_CONSUMER_KEY", "")
EPO_SECRET = ENV.get("EPO_CONSUMER_SECRET", "")
PATENTHUB_TOKEN = ENV.get("PATENTHUB_API_TOKEN", "") or "89a9671a07c9904d04574a062859ac794ff5a2ac"
UA = "ScholarPilot/2.0 (experiment; scholarpilot@example.com)"


def _fetch(url: str, headers: dict | None = None, method: str = "GET",
           data: bytes | None = None, timeout: int = 20) -> dict:
    hdrs = {"User-Agent": UA}
    if headers:
        hdrs.update(headers)
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers=hdrs, method=method, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            dt = time.time() - t0
            ct = r.headers.get("Content-Type", "")
            try:
                if "json" in ct.lower():
                    return {"ok": True, "status": r.status, "elapsed": dt,
                            "data": json.loads(body.decode("utf-8", errors="replace"))}
                return {"ok": True, "status": r.status, "elapsed": dt,
                        "text": body.decode("utf-8", errors="replace")}
            except json.JSONDecodeError:
                return {"ok": True, "status": r.status, "elapsed": dt,
                        "text": body.decode("utf-8", errors="replace")[:500]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "elapsed": time.time() - t0,
                "err": e.read().decode("utf-8", errors="replace")[:300]}
    except Exception as e:
        return {"ok": False, "elapsed": time.time() - t0, "err": repr(e)}


SOURCES = {}


def register(sid: str):
    def deco(fn):
        SOURCES[sid] = fn
        return fn
    return deco


def _line(name: str, v: dict):
    total = v.get("total")
    total_s = f"{total:>8}" if isinstance(total, int) else f"{str(total):>8}"
    print(f"  [{name:16s}] total={total_s} "
          f"elapsed={v.get('elapsed', 0):5.2f}s status={v.get('status','?')} | "
          f"{(v.get('first') or v.get('err') or '')[:70]}")


# ─────────────── 各源 ───────────────

@register("openalex")
def _openalex():
    base = "https://api.openalex.org/works"
    mail = "scholarpilot@example.com"
    variants = {
        "baseline_3w": "lithium battery cathode",
        "baseline_5w": "lithium battery cathode coating stability",
        "phrase": '"lithium battery" cathode coating',
        "boolean_AND": "lithium AND battery AND cathode",
        "boolean_OR": "lithium OR sodium cathode",
        "boolean_NOT": "lithium battery cathode NOT polymer",
    }
    out = {}
    for name, q in variants.items():
        url = f"{base}?search={urllib.parse.quote(q)}&per_page=3&mailto={mail}"
        r = _fetch(url)
        d = r.get("data") or {}
        total = (d.get("meta") or {}).get("count") if r["ok"] else None
        results = d.get("results") or []
        first = results[0].get("title") if results else None
        out[name] = {"q": q, "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.4)
    return out


@register("europe_pmc")
def _europe_pmc():
    base = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    variants = {
        "baseline_3w": "lithium battery cathode",
        "baseline_5w": "lithium battery cathode coating stability",
        "phrase": '"lithium battery" cathode coating',
        "field_TITLE": 'TITLE:"lithium" AND TITLE:"cathode"',
        "field_ABSTRACT_title_combo": 'TITLE:"lithium battery" AND ABSTRACT:"cathode"',
        "boolean_AND_explicit": "lithium AND battery AND cathode",
        "boolean_OR": "lithium OR sodium cathode",
        "date_range": "lithium battery cathode AND FIRST_PDATE:[2020-01-01 TO 2024-12-31]",
    }
    out = {}
    for name, q in variants.items():
        url = f"{base}?query={urllib.parse.quote(q)}&format=json&pageSize=3&resultType=core"
        r = _fetch(url)
        d = r.get("data") or {}
        total = d.get("hitCount") if r["ok"] else None
        results = (d.get("resultList") or {}).get("result") or []
        first = results[0].get("title") if results else None
        out[name] = {"q": q, "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.4)
    return out


@register("crossref")
def _crossref():
    base = "https://api.crossref.org/works"
    variants = {
        "baseline_3w": ("query", "lithium battery cathode"),
        "baseline_5w": ("query", "lithium battery cathode coating stability"),
        "title_field": ("query.title", "lithium battery cathode"),
        "bibliographic": ("query.bibliographic", "lithium battery cathode"),
        "boolean_AND": ("query", "lithium AND battery AND cathode"),
    }
    out = {}
    for name, (param, q) in variants.items():
        url = f"{base}?{param}={urllib.parse.quote(q)}&rows=3"
        r = _fetch(url)
        d = r.get("data") or {}
        total = ((d.get("message") or {}).get("total-results")) if r["ok"] else None
        items = (d.get("message") or {}).get("items") or []
        first = (items[0].get("title") or [None])[0] if items else None
        out[name] = {"q": f"{param}={q}", "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.4)
    return out


@register("dblp")
def _dblp():
    base = "https://dblp.org/search/publ/api"
    variants = {
        "baseline_2w": "transformer attention",
        "baseline_3w": "transformer attention efficient",
        "pipe_OR": "transformer|attention",
        "dollar_fuzzy": "transform$ attention",
        "quote_phrase": '"attention is all you need"',
    }
    out = {}
    for name, q in variants.items():
        url = f"{base}?q={urllib.parse.quote(q)}&format=json&h=3"
        r = _fetch(url)
        d = r.get("data") or {}
        hits = ((d.get("result") or {}).get("hits") or {})
        total = hits.get("@total")
        if total is not None:
            try:
                total = int(total)
            except Exception:
                pass
        hit_list = hits.get("hit") or []
        first = hit_list[0].get("info", {}).get("title") if hit_list else None
        out[name] = {"q": q, "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.4)
    return out


@register("arxiv")
def _arxiv():
    base = "http://export.arxiv.org/api/query"
    variants = {
        "baseline_3w_all": "all:lithium battery cathode",
        "baseline_4w_AND": "all:lithium+AND+all:battery+AND+all:cathode+AND+all:coating",
        "field_ti": "ti:lithium AND ti:battery AND ti:cathode",
        "field_abs": "abs:lithium AND abs:cathode",
        "field_ti_abs_combo": "ti:lithium AND abs:cathode",
        "boolean_ANDNOT": "all:lithium AND all:cathode ANDNOT all:polymer",
        "phrase": 'ti:"lithium battery" AND abs:cathode',
    }
    out = {}
    ns = {"atom": "http://www.w3.org/2005/Atom", "opensearch": "http://a9.com/-/spec/opensearch/1.1/"}
    for name, q in variants.items():
        # arxiv 用 + 代替空格（+ 也是 URL 安全字符）
        url = f"{base}?search_query={urllib.parse.quote(q, safe=':+=')}&max_results=3"
        r = _fetch(url)
        total = None
        first = None
        if r["ok"] and r.get("text"):
            try:
                root = ET.fromstring(r["text"])
                tot_el = root.find("opensearch:totalResults", ns)
                if tot_el is not None and tot_el.text:
                    total = int(tot_el.text)
                first_entry = root.find("atom:entry", ns)
                if first_entry is not None:
                    t = first_entry.findtext("atom:title", "", ns)
                    first = t.strip().replace("\n", " ")[:80]
            except Exception as e:
                r["err"] = f"xml_parse: {e}"
        out[name] = {"q": q, "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.8)
    return out


@register("pubmed")
def _pubmed():
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    variants = {
        "baseline_3w": "lithium battery cathode",
        "baseline_5w": "lithium battery cathode coating stability",
        "phrase": '"lithium battery" cathode',
        "field_Title": "lithium[Title] AND battery[Title]",
        "field_Abstract": "cathode[Abstract] AND lithium[Title]",
        "field_dp": "lithium battery cathode AND 2020:2024[dp]",
        "boolean_AND": "lithium AND battery AND cathode",
        "boolean_OR": "lithium OR sodium AND cathode",
    }
    out = {}
    for name, q in variants.items():
        url = f"{base}?db=pubmed&term={urllib.parse.quote(q)}&retmode=json&retmax=3"
        r = _fetch(url)
        d = r.get("data") or {}
        total = None
        first = None
        if r["ok"]:
            try:
                total = int((d.get("esearchresult") or {}).get("count") or 0)
            except Exception:
                pass
        out[name] = {"q": q, "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.4)
    return out


@register("clinical_trials")
def _clinical_trials():
    # v2 API（官方；v1 已废弃）
    base = "https://clinicaltrials.gov/api/v2/studies"
    variants = {
        "baseline_query_term": ("query.term", "lithium battery"),
        "cond_only": ("query.cond", "diabetes type 2"),
        "field_intr": ("query.intr", "semaglutide"),
        "boolean_AND_term": ("query.term", "semaglutide AND diabetes"),
    }
    out = {}
    for name, (param, q) in variants.items():
        url = f"{base}?{param}={urllib.parse.quote(q)}&pageSize=3&countTotal=true&format=json"
        r = _fetch(url)
        d = r.get("data") or {}
        total = d.get("totalCount") if r["ok"] else None
        studies = d.get("studies") or []
        first = None
        if studies:
            ps = (studies[0].get("protocolSection") or {}).get("identificationModule") or {}
            first = ps.get("briefTitle") or ps.get("officialTitle")
        out[name] = {"q": f"{param}={q}", "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.4)
    return out


@register("patenthub")
def _patenthub():
    # 为省钱每个变体只 ps=1，总共 5 次 × ¥0.1 = ¥0.5
    base = "https://www.patenthub.cn/api/s"
    variants = {
        "baseline_cn": ("cn", "锂电池 正极"),
        "baseline_en_all": ("all", "lithium battery cathode"),
        "field_ti_cn": ("cn", "ti=锂电池"),
        "field_type_AND": ("cn", "ti=锂电池 AND type=发明授权"),
        "date_range_AND": ("cn", "(锂电池) AND ad=[20230101 TO 20241231]"),
    }
    out = {}
    for name, (ds, q) in variants.items():
        params = {"t": PATENTHUB_TOKEN, "v": "1", "q": q, "ds": ds, "ps": "1"}
        url = base + "?" + urllib.parse.urlencode(params)
        r = _fetch(url)
        d = r.get("data") or {}
        total = d.get("total") if (r["ok"] and d.get("success")) else None
        pats = d.get("patents") or []
        first = pats[0].get("title") if pats else None
        out[name] = {"q": f"ds={ds} q={q}", "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.5)
    return out


@register("lens_patent")
def _lens():
    if not LENS_TOKEN:
        return {"_skipped": {"err": "LENS_API_TOKEN 未配置，跳过"}}
    base = "https://api.lens.org/patent/search"  # 如果有 scholarly token 用 scholarly endpoint
    # 构造 POST JSON
    variants = {
        "plain_query": {"query": "lithium battery cathode", "size": 1},
        "must_bool": {
            "query": {
                "bool": {
                    "must": [
                        {"match": {"title": "lithium battery"}},
                        {"match": {"abstract": "cathode"}},
                    ]
                }
            },
            "size": 1,
        },
        "date_filter": {
            "query": {
                "bool": {
                    "must": [{"match": {"title": "lithium battery"}}],
                    "filter": [{"range": {"date_published": {"gte": "2020-01-01", "lte": "2024-12-31"}}}],
                }
            },
            "size": 1,
        },
    }
    out = {}
    for name, body in variants.items():
        data = json.dumps(body).encode("utf-8")
        r = _fetch(base, headers={
            "Authorization": f"Bearer {LENS_TOKEN}",
            "Content-Type": "application/json",
        }, method="POST", data=data, timeout=30)
        d = r.get("data") or {}
        total = d.get("total") if r["ok"] else None
        hits = d.get("data") or []
        first = hits[0].get("biblio", {}).get("invention_title", [{}])[0].get("text") if hits else None
        out[name] = {"q": json.dumps(body)[:90], "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(1.0)
    return out


@register("epo_ops")
def _epo_ops():
    if not (EPO_KEY and EPO_SECRET):
        return {"_skipped": {"err": "EPO_CONSUMER_KEY/SECRET 未配置，跳过"}}
    # Step 1: OAuth2 拿 access token
    auth = base64.b64encode(f"{EPO_KEY}:{EPO_SECRET}".encode()).decode()
    tok_r = _fetch("https://ops.epo.org/3.2/auth/accesstoken",
                   headers={"Authorization": f"Basic {auth}",
                            "Content-Type": "application/x-www-form-urlencoded"},
                   method="POST", data=b"grant_type=client_credentials", timeout=30)
    if not tok_r["ok"]:
        return {"_oauth_fail": tok_r}
    access = (tok_r.get("data") or {}).get("access_token")
    if not access:
        return {"_oauth_fail": {"err": "no access_token in response", "raw": tok_r.get("text", "")[:200]}}

    base = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"
    variants = {
        "plain_kw": "lithium battery cathode",
        "field_ti": 'ti="lithium battery"',
        "ti_AND_ab": 'ti=lithium AND ab=cathode',
        "ti_OR_ab": 'ti=lithium OR ab=cathode',
        "date_range": 'ti=lithium AND pd within "20200101 20241231"',
    }
    out = {}
    for name, q in variants.items():
        url = f"{base}?q={urllib.parse.quote(q)}&Range=1-2"
        r = _fetch(url, headers={"Authorization": f"Bearer {access}",
                                  "Accept": "application/json"}, timeout=30)
        total = None
        first = None
        if r["ok"]:
            try:
                biblio = (r.get("data") or {}).get("ops:world-patent-data", {}).get("ops:biblio-search", {})
                total = biblio.get("@total-result-count")
                if total is not None:
                    total = int(total)
            except Exception:
                pass
        out[name] = {"q": q, "total": total, "status": r.get("status"),
                     "elapsed": r["elapsed"], "first": first, "err": r.get("err")}
        _line(name, out[name])
        time.sleep(0.6)
    return out


# ─────────────── 主循环 ───────────────

def main():
    print(f"ROOT = {ROOT}")
    print(f".env tokens: LENS={'Y' if LENS_TOKEN else 'N'}, "
          f"EPO={'Y' if EPO_KEY and EPO_SECRET else 'N'}, "
          f"PATENTHUB={'Y' if PATENTHUB_TOKEN else 'N'}")
    print()

    results = {}
    selected = sys.argv[1:] if len(sys.argv) > 1 else list(SOURCES.keys())

    for sid in selected:
        if sid not in SOURCES:
            print(f"[skip] 未知源: {sid}")
            continue
        print(f"=== {sid} ===")
        try:
            results[sid] = SOURCES[sid]()
        except Exception as e:
            results[sid] = {"_error": {"err": repr(e)}}
            print(f"  ERROR: {e!r}")
        print()

    out_path = ROOT / "tmp" / "source_query_experiment.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 结果已保存：{out_path}")


if __name__ == "__main__":
    main()
