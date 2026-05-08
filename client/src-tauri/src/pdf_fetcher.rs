// Tauri Rust PDF fetcher — 2026-05-08 三通道扩展（sp-api 零本地 PDF 改造）。
//
// 历史 C10：rust 三层兜底直抓 OA 直链（A/B 类），失败 fallback sp-api。
// 现状（HK sp-api 不再落盘 PDF）→ 客户端 Rust 是唯一能写 PDF 到本地的人，
// 三类源各走不同通道：
//
// **A 类** — OA 直链（arxiv / openalex / europe_pmc / crossref / semantic_scholar）
//   `pdf_fetch_direct`：本地三层兜底
//     L1: 直接 GET pdf_url
//     L2: unpaywall(doi) → OA url → GET
//     L3: GET DOI / landing_url HTML → citation_pdf_url meta → GET
//   sp-api 完全不参与。失败时 layer_used='failed'，调用方可改走 resolve-url。
//
// **B 类** — landing-meta（pubmed / dblp / clinical_trials / openalex_zh）
//   `pdf_fetch_via_resolve_url`：调 sp-api `POST /api/fulltext/resolve-url` 拿 URL
//   → 客户端再 GET binary 写本地。sp-api 自己不下载 binary。
//
// **C 类** — 付费 token（patenthub / lens / epo_ops / bigquery_patents）
//   `pdf_fetch_via_proxy`：调 sp-api `POST /api/fulltext/proxy/{source}/{id}`
//   → sp-api 用 server-side token 调付费 API + httpx stream → chunked
//   StreamingResponse → 客户端边收边写本地（**sp-api 0 落盘**）。
//   client run_id + force flag 走 patenthub 预算守门（402 → 用户二次确认）。
//
// 反爬：A/B 类直抓走 Chrome 136 5 层 sec-ch-ua-* stealth headers；C 类走
// sp-api token，header 由 sp-api 控制，client 只附 Authorization。

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use once_cell::sync::Lazy;
use regex::Regex;
use reqwest::{header, Client};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tauri::{AppHandle, Manager};
use tokio::io::AsyncWriteExt;

// 与 backend fulltext_service.py 同步保持一个 Chrome 主版本号。
const CHROME_VERSION: &str = "136.0.7103.114";

/// 完整 Chrome 136 真实指纹 headers（5 层反爬）：
///   1. UA / Accept-Language / Accept-Encoding 基础三件套
///   2. sec-ch-ua + sec-ch-ua-full-version-list（Chromium 120+ 关键字段，
///      Cloudflare/MDPI 不带就识破）
///   3. sec-ch-ua-mobile / -platform / -platform-version 设备指纹
///   4. Sec-Fetch-Dest/-Mode/-Site/-User 行为指纹
///   5. Upgrade-Insecure-Requests / Cache-Control / Priority HTTP/2 hint
fn build_browser_headers() -> header::HeaderMap {
    let mut h = header::HeaderMap::new();
    macro_rules! ins {
        ($k:expr, $v:expr) => {
            if let Ok(val) = header::HeaderValue::from_str($v) {
                h.insert($k, val);
            }
        };
    }
    ins!(
        header::USER_AGENT,
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
         (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    );
    ins!(
        header::ACCEPT_LANGUAGE,
        "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
    );
    // reqwest 自动按 features 注入 Accept-Encoding；显式写也无害。
    ins!(header::ACCEPT_ENCODING, "gzip, deflate, br, zstd");
    ins!(
        "sec-ch-ua",
        "\"Chromium\";v=\"136\", \"Google Chrome\";v=\"136\", \"Not.A/Brand\";v=\"99\""
    );
    let full_ver = format!(
        "\"Chromium\";v=\"{v}\", \"Google Chrome\";v=\"{v}\", \"Not.A/Brand\";v=\"99.0.0.0\"",
        v = CHROME_VERSION
    );
    ins!("sec-ch-ua-full-version-list", &full_ver);
    ins!("sec-ch-ua-mobile", "?0");
    ins!("sec-ch-ua-platform", "\"Windows\"");
    ins!("sec-ch-ua-platform-version", "\"19.0.0\"");
    ins!("Sec-Fetch-Dest", "document");
    ins!("Sec-Fetch-Mode", "navigate");
    ins!("Sec-Fetch-Site", "none");
    ins!("Sec-Fetch-User", "?1");
    ins!(header::UPGRADE_INSECURE_REQUESTS, "1");
    ins!(header::CACHE_CONTROL, "max-age=0");
    ins!("Priority", "u=0, i");
    h
}

fn build_client(timeout_secs: u64) -> Result<Client, String> {
    Client::builder()
        .default_headers(build_browser_headers())
        .timeout(Duration::from_secs(timeout_secs))
        .cookie_store(true)
        .redirect(reqwest::redirect::Policy::limited(8))
        .build()
        .map_err(|e| format!("client build failed: {e}"))
}

/// TS 端通过 invoke('pdf_fetch_direct', { req: ... }) 调过来的入参。
/// camelCase 自动 → snake_case（serde 默认匹配 struct 字段）— TS 端必须传 snake_case。
#[derive(Debug, Deserialize)]
pub struct PdfFetchRequest {
    pub doc_id: String,
    #[allow(dead_code)]
    pub source: String,
    #[allow(dead_code)]
    pub external_id: Option<String>,
    pub doi: Option<String>,
    pub pdf_url: Option<String>,
    pub landing_url: Option<String>,
    pub project_id: String,
    /// 单层超时（秒），默认 5
    pub timeout_secs: Option<u64>,
}

/// `layer_used` 取值：'direct' / 'unpaywall' / 'doi-meta' / 'failed'
#[derive(Debug, Serialize)]
pub struct PdfFetchResult {
    pub success: bool,
    pub local_path: Option<String>,
    pub size_bytes: Option<u64>,
    pub error: Option<String>,
    pub layer_used: Option<String>,
}

#[tauri::command]
pub async fn pdf_fetch_direct(
    app: AppHandle,
    req: PdfFetchRequest,
) -> Result<PdfFetchResult, String> {
    let timeout = req.timeout_secs.unwrap_or(5);
    let client = build_client(timeout)?;
    let normalized_doi = normalize_doi(req.doi.as_deref());

    // ── L1: 直接 pdf_url ────────────────────────────────────────────
    if let Some(pdf_url) = req.pdf_url.as_deref().filter(|s| !s.is_empty()) {
        if let Ok(bytes) = try_fetch_pdf(&client, pdf_url).await {
            let path =
                save_pdf(&app, &req.project_id, &req.doc_id, &bytes).await?;
            return Ok(PdfFetchResult {
                success: true,
                local_path: Some(path),
                size_bytes: Some(bytes.len() as u64),
                error: None,
                layer_used: Some("direct".into()),
            });
        }
    }

    // ── L2: unpaywall(doi) ─────────────────────────────────────────
    if let Some(doi) = normalized_doi.as_deref() {
        if let Ok(unpaywall_url) = unpaywall_lookup(&client, doi).await {
            if let Ok(bytes) = try_fetch_pdf(&client, &unpaywall_url).await {
                let path = save_pdf(&app, &req.project_id, &req.doc_id, &bytes)
                    .await?;
                return Ok(PdfFetchResult {
                    success: true,
                    local_path: Some(path),
                    size_bytes: Some(bytes.len() as u64),
                    error: None,
                    layer_used: Some("unpaywall".into()),
                });
            }
        }
    }

    // ── L3: DOI / landing → HTML → citation_pdf_url meta ────────────
    let landing_candidate: Option<String> = req
        .landing_url
        .as_deref()
        .filter(|s| !s.is_empty())
        .map(String::from)
        .or_else(|| normalized_doi.as_deref().map(|d| format!("https://doi.org/{d}")));
    if let Some(url) = landing_candidate {
        if let Ok(html) = try_fetch_text(&client, &url).await {
            if let Some(pdf_url) = extract_citation_pdf_url(&html) {
                let resolved = resolve_url(&url, &pdf_url);
                if let Ok(bytes) = try_fetch_pdf(&client, &resolved).await {
                    let path =
                        save_pdf(&app, &req.project_id, &req.doc_id, &bytes)
                            .await?;
                    return Ok(PdfFetchResult {
                        success: true,
                        local_path: Some(path),
                        size_bytes: Some(bytes.len() as u64),
                        error: None,
                        layer_used: Some("doi-meta".into()),
                    });
                }
            }
        }
    }

    Ok(PdfFetchResult {
        success: false,
        local_path: None,
        size_bytes: None,
        error: Some("All 3 layers failed; will fallback to sp-api".into()),
        layer_used: Some("failed".into()),
    })
}

// ─── helpers ───────────────────────────────────────────────────────

/// 剥掉 doi 字符串可能带的多种 URL 前缀（`https://doi.org/`, `doi:` 等）。
/// 与 backend `_normalize_doi` 行为对齐。
fn normalize_doi(raw: Option<&str>) -> Option<String> {
    let mut s = raw?.trim().to_owned();
    if s.is_empty() {
        return None;
    }
    for _ in 0..3 {
        let lower = s.to_lowercase();
        let mut stripped = false;
        for prefix in [
            "https://doi.org/",
            "http://doi.org/",
            "doi.org/",
            "doi:",
        ] {
            if lower.starts_with(prefix) {
                s = s[prefix.len()..].trim().to_owned();
                stripped = true;
                break;
            }
        }
        if !stripped {
            break;
        }
    }
    if s.is_empty() {
        None
    } else {
        Some(s)
    }
}

async fn try_fetch_pdf(client: &Client, url: &str) -> Result<Vec<u8>, String> {
    let resp = client
        .get(url)
        .header(header::ACCEPT, "application/pdf,application/octet-stream,*/*;q=0.8")
        .header("Sec-Fetch-Dest", "embed")
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("status {}", resp.status()));
    }
    // 校验 content-type 或 PDF magic bytes（避免拿到 HTML 错误页）。
    let ct_is_pdf = resp
        .headers()
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_lowercase().contains("pdf"))
        .unwrap_or(false);
    let bytes = resp.bytes().await.map_err(|e| e.to_string())?.to_vec();
    if bytes.len() > 4 && &bytes[0..4] == b"%PDF" {
        Ok(bytes)
    } else if ct_is_pdf && !bytes.is_empty() {
        Ok(bytes) // 偶有 PDF 不是以 %PDF 开头但 ct 正确（很罕见）
    } else {
        Err("not a PDF (magic bytes / content-type mismatch)".into())
    }
}

async fn try_fetch_text(client: &Client, url: &str) -> Result<String, String> {
    let resp = client
        .get(url)
        .header(
            header::ACCEPT,
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        )
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("status {}", resp.status()));
    }
    resp.text().await.map_err(|e| e.to_string())
}

async fn unpaywall_lookup(client: &Client, doi: &str) -> Result<String, String> {
    // 公共邮箱要求 — Unpaywall 文档说明 email 必填用于 rate-limit。
    let url = format!(
        "https://api.unpaywall.org/v2/{}?email=scholarpilot@example.com",
        urlencoding_encode(doi)
    );
    let resp = client
        .get(&url)
        .header(header::ACCEPT, "application/json")
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("unpaywall status {}", resp.status()));
    }
    let data: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
    if let Some(loc) = data["best_oa_location"]["url_for_pdf"].as_str() {
        if !loc.is_empty() {
            return Ok(loc.to_string());
        }
    }
    Err("no OA pdf url".into())
}

/// 极简 url-encode，只对 doi 中允许出现但 URL path 不安全的少量字符做处理。
/// reqwest 不暴露内部 percent-encoding，引第三方 crate 太重；DOI 多数 ASCII 安全。
fn urlencoding_encode(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b' ' => "%20".into(),
            b'#' => "%23".into(),
            b'?' => "%3F".into(),
            _ => (b as char).to_string(),
        })
        .collect()
}

/// HTML 中的 `<meta name="citation_pdf_url" content="...">` —
/// 也兼容 `name='citation_pdf_url'` 单引号、属性顺序倒置。
fn extract_citation_pdf_url(html: &str) -> Option<String> {
    static RE_NAME_FIRST: Lazy<Regex> = Lazy::new(|| {
        Regex::new(
            r#"(?i)<meta[^>]+name=["']citation_pdf_url["'][^>]+content=["']([^"']+)["']"#,
        )
        .unwrap()
    });
    static RE_CONTENT_FIRST: Lazy<Regex> = Lazy::new(|| {
        Regex::new(
            r#"(?i)<meta[^>]+content=["']([^"']+)["'][^>]+name=["']citation_pdf_url["']"#,
        )
        .unwrap()
    });
    RE_NAME_FIRST
        .captures(html)
        .and_then(|c| c.get(1).map(|m| m.as_str().to_string()))
        .or_else(|| {
            RE_CONTENT_FIRST
                .captures(html)
                .and_then(|c| c.get(1).map(|m| m.as_str().to_string()))
        })
}

/// 把 citation_pdf_url 里可能出现的相对路径解析成绝对 URL。
fn resolve_url(base: &str, maybe_relative: &str) -> String {
    if maybe_relative.starts_with("http://") || maybe_relative.starts_with("https://") {
        return maybe_relative.to_string();
    }
    match url::Url::parse(base).and_then(|b| b.join(maybe_relative)) {
        Ok(u) => u.to_string(),
        Err(_) => maybe_relative.to_string(),
    }
}

/// 落盘到 `<AppData>/scholarpilot/projects/<pid>/library/pdfs/<docId>.pdf`。
/// **注意**：客户端 TS 侧约定的 PDF 子目录是 `pdfs/`（见 `client/src/data/fs/paths.ts`），
/// 不是 `library/pdfs/`，所以这里跟它对齐避免 `silentPdfReconciler.filterPending`
/// 已经写过本地的 doc 又被当成"缺失"重抓。
async fn save_pdf(
    app: &AppHandle,
    project_id: &str,
    doc_id: &str,
    bytes: &[u8],
) -> Result<String, String> {
    if !is_safe_id(project_id) || !is_safe_id(doc_id) {
        return Err(format!(
            "unsafe id (project_id={project_id}, doc_id={doc_id})"
        ));
    }
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?;
    let pdf_dir = app_data_dir
        .join("projects")
        .join(project_id)
        .join("pdfs");
    tokio::fs::create_dir_all(&pdf_dir)
        .await
        .map_err(|e| format!("mkdir {:?} failed: {}", pdf_dir, e))?;
    let pdf_path = pdf_dir.join(format!("{doc_id}.pdf"));
    let tmp_path = pdf_dir.join(format!("{doc_id}.pdf.tmp"));
    tokio::fs::write(&tmp_path, bytes)
        .await
        .map_err(|e| format!("write tmp failed: {e}"))?;
    tokio::fs::rename(&tmp_path, &pdf_path)
        .await
        .map_err(|e| format!("rename failed: {e}"))?;
    Ok(pdf_path.to_string_lossy().into_owned())
}

/// 与 client/src/data/fs/paths.ts 的 `isSafeId` 对齐 — 防止跨目录注入。
fn is_safe_id(id: &str) -> bool {
    !id.is_empty()
        && id.bytes().all(|b| {
            b.is_ascii_alphanumeric() || b == b'.' || b == b'-' || b == b'_'
        })
}

// 仅为本模块未来可能复用的 base64 调试钩子，当前未直接用到；保留消除 unused_import 风险。
#[allow(dead_code)]
fn _b64_for_debug(bytes: &[u8]) -> String {
    B64.encode(bytes)
}

// ─── B 类: pdf_fetch_via_resolve_url（sp-api resolve URL → 客户端自抓） ───
//
// 客户端拿不到 citation_pdf_url meta 的源（pubmed / dblp / clinical_trials /
// openalex_zh）走这条：sp-api 服务端用 stealth headers 抓 landing HTML 解析
// citation_pdf_url，**只返回 URL 字符串**，binary 由客户端 reqwest 自抓。
// 这样 sp-api 不落盘，客户端写 disk 跟 A 类一致。

#[derive(Debug, Deserialize)]
pub struct ResolveUrlRequest {
    pub doc_id: String,
    pub source: String,
    pub external_id: Option<String>,
    pub doi: Option<String>,
    pub pdf_url: Option<String>,
    pub landing_url: Option<String>,
    pub project_id: String,
    /// sp-api base URL（含协议 + host），由 TS 调用方注入避免 rust 写死生产域名
    pub sp_api_base: String,
    /// 客户端 access token（用 Bearer）
    pub auth_token: String,
    /// 请求 sp-api 的超时（秒）；默认 25
    pub timeout_secs: Option<u64>,
}

#[derive(Debug, Serialize, Deserialize)]
struct ResolveUrlSpApiBody {
    source: String,
    external_id: Option<String>,
    doi: Option<String>,
    landing_url: Option<String>,
    pdf_url: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ResolveUrlSpApiResponse {
    pdf_url: Option<String>,
    source_layer: Option<String>,
}

#[tauri::command]
pub async fn pdf_fetch_via_resolve_url(
    app: AppHandle,
    req: ResolveUrlRequest,
) -> Result<PdfFetchResult, String> {
    let timeout = req.timeout_secs.unwrap_or(25);
    let client = build_client(timeout)?;

    // Step 1: 调 sp-api /api/fulltext/resolve-url 拿 URL
    let body = ResolveUrlSpApiBody {
        source: req.source.clone(),
        external_id: req.external_id.clone(),
        doi: req.doi.clone(),
        landing_url: req.landing_url.clone(),
        pdf_url: req.pdf_url.clone(),
    };
    let endpoint = format!("{}/api/fulltext/resolve-url", trim_slash(&req.sp_api_base));
    let resp = client
        .post(&endpoint)
        .bearer_auth(&req.auth_token)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("resolve-url request failed: {e}"))?;
    if !resp.status().is_success() {
        let status = resp.status();
        let body_snip = resp.text().await.unwrap_or_default();
        return Ok(PdfFetchResult {
            success: false,
            local_path: None,
            size_bytes: None,
            error: Some(format!(
                "sp-api resolve-url {}: {}",
                status,
                truncate(&body_snip, 200)
            )),
            layer_used: Some("failed".into()),
        });
    }
    let parsed: ResolveUrlSpApiResponse = resp
        .json()
        .await
        .map_err(|e| format!("resolve-url JSON parse failed: {e}"))?;
    let target_url = match parsed.pdf_url {
        Some(u) if !u.is_empty() => u,
        _ => {
            return Ok(PdfFetchResult {
                success: false,
                local_path: None,
                size_bytes: None,
                error: Some("sp-api resolve-url returned null pdf_url".into()),
                layer_used: Some("failed".into()),
            });
        }
    };

    // Step 2: 客户端 reqwest 自抓 binary
    let bytes = try_fetch_pdf(&client, &target_url)
        .await
        .map_err(|e| format!("fetch resolved pdf_url failed: {e}"))?;
    let path = save_pdf(&app, &req.project_id, &req.doc_id, &bytes).await?;
    Ok(PdfFetchResult {
        success: true,
        local_path: Some(path),
        size_bytes: Some(bytes.len() as u64),
        error: None,
        layer_used: parsed.source_layer.or_else(|| Some("resolve-url".into())),
    })
}

// ─── C 类: pdf_fetch_via_proxy（sp-api stream PDF chunks → 客户端写盘） ───
//
// 付费源（patenthub / lens / epo_ops / bigquery_patents）token 在 sp-api 不能
// 给客户端，sp-api 用 token 调付费 API + httpx stream，**chunked 转发** 给
// 客户端，客户端边收边写本地。sp-api 内存占用 < 1MB（chunk 64KB），不落盘。
//
// 预算守门：sp-api 内部 try_consume → 软超额返 402，stream 异常时 refund。

#[derive(Debug, Deserialize)]
pub struct ProxyRequest {
    pub doc_id: String,
    pub source: String,
    pub external_id: String,
    pub doi: Option<String>,
    pub pdf_url: Option<String>,
    pub project_id: String,
    /// patenthub 预算守门 key 维度
    pub client_run_id: String,
    /// 用户二次确认越权（前端弹窗后传 true）
    pub force: bool,
    pub sp_api_base: String,
    pub auth_token: String,
    pub timeout_secs: Option<u64>,
}

#[derive(Debug, Serialize)]
struct ProxySpApiBody {
    client_run_id: String,
    force: bool,
    doi: Option<String>,
    pdf_url: Option<String>,
}

#[tauri::command]
pub async fn pdf_fetch_via_proxy(
    app: AppHandle,
    req: ProxyRequest,
) -> Result<PdfFetchResult, String> {
    if !is_safe_id(&req.project_id) || !is_safe_id(&req.doc_id) {
        return Err(format!(
            "unsafe id (project_id={} doc_id={})",
            req.project_id, req.doc_id
        ));
    }
    let timeout = req.timeout_secs.unwrap_or(120); // 付费源 PDF 可能 > 30 MB
    let client = build_client(timeout)?;
    let body = ProxySpApiBody {
        client_run_id: req.client_run_id.clone(),
        force: req.force,
        doi: req.doi.clone(),
        pdf_url: req.pdf_url.clone(),
    };
    let endpoint = format!(
        "{}/api/fulltext/proxy/{}/{}",
        trim_slash(&req.sp_api_base),
        urlencoding_encode(&req.source),
        urlencoding_encode(&req.external_id),
    );
    let resp = client
        .post(&endpoint)
        .bearer_auth(&req.auth_token)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("proxy request failed: {e}"))?;

    let status = resp.status();
    if status.as_u16() == 402 {
        // 软超额，前端弹二次确认；带原始 detail 让 TS 解析 used/max
        let body_snip = resp.text().await.unwrap_or_default();
        return Ok(PdfFetchResult {
            success: false,
            local_path: None,
            size_bytes: None,
            error: Some(format!("BUDGET_EXCEEDED:{}", truncate(&body_snip, 1024))),
            layer_used: Some("budget".into()),
        });
    }
    if !status.is_success() {
        let body_snip = resp.text().await.unwrap_or_default();
        return Ok(PdfFetchResult {
            success: false,
            local_path: None,
            size_bytes: None,
            error: Some(format!("sp-api proxy {}: {}", status, truncate(&body_snip, 200))),
            layer_used: Some("failed".into()),
        });
    }

    // 写入流：先 .tmp，全部 stream 完后 rename。stream 中断时 .tmp 会被
    // 下次重抓覆盖（save_pdf 的 rename 是原子的）。
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?;
    let pdf_dir = app_data_dir
        .join("projects")
        .join(&req.project_id)
        .join("pdfs");
    tokio::fs::create_dir_all(&pdf_dir)
        .await
        .map_err(|e| format!("mkdir failed: {e}"))?;
    let pdf_path = pdf_dir.join(format!("{}.pdf", req.doc_id));
    let tmp_path = pdf_dir.join(format!("{}.pdf.tmp", req.doc_id));

    let mut file = tokio::fs::File::create(&tmp_path)
        .await
        .map_err(|e| format!("create tmp failed: {e}"))?;

    let mut total: u64 = 0;
    let mut magic_checked = false;
    let mut stream = resp.bytes_stream();
    use futures_util::StreamExt;
    while let Some(chunk) = stream.next().await {
        let bytes = chunk.map_err(|e| format!("stream chunk failed: {e}"))?;
        if !magic_checked {
            // 第一段必须是 %PDF- magic — sp-api 端也有这个校验，但 reverse
            // proxy / cf-tunnel 偶发会注入 HTML 错误页，client 也再确认一次。
            if bytes.len() >= 4 && &bytes[0..4] == b"%PDF" {
                magic_checked = true;
            } else if bytes.len() >= 4 {
                let _ = tokio::fs::remove_file(&tmp_path).await;
                return Ok(PdfFetchResult {
                    success: false,
                    local_path: None,
                    size_bytes: None,
                    error: Some(format!(
                        "proxy stream first chunk not PDF magic: {:?}",
                        &bytes[0..bytes.len().min(16)]
                    )),
                    layer_used: Some("failed".into()),
                });
            }
            // 极端：第一个 chunk < 4 字节 — 不少见，下个 chunk 来再校验
        }
        file.write_all(&bytes)
            .await
            .map_err(|e| format!("write tmp failed: {e}"))?;
        total += bytes.len() as u64;
    }
    file.flush()
        .await
        .map_err(|e| format!("flush failed: {e}"))?;
    drop(file);

    if total == 0 {
        let _ = tokio::fs::remove_file(&tmp_path).await;
        return Ok(PdfFetchResult {
            success: false,
            local_path: None,
            size_bytes: None,
            error: Some("proxy stream returned 0 bytes".into()),
            layer_used: Some("failed".into()),
        });
    }

    tokio::fs::rename(&tmp_path, &pdf_path)
        .await
        .map_err(|e| format!("rename failed: {e}"))?;

    Ok(PdfFetchResult {
        success: true,
        local_path: Some(pdf_path.to_string_lossy().into_owned()),
        size_bytes: Some(total),
        error: None,
        layer_used: Some("paid-stream".into()),
    })
}

// ─── shared helpers for new commands ─────────────────────────────────

fn trim_slash(s: &str) -> &str {
    s.trim_end_matches('/')
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max { s.to_string() } else { s[..max].to_string() }
}

// ─── unit tests ────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_citation_pdf_url_basic() {
        let html = r#"<html><head>
            <meta name="citation_pdf_url" content="https://example.org/file.pdf">
            </head></html>"#;
        assert_eq!(
            extract_citation_pdf_url(html).as_deref(),
            Some("https://example.org/file.pdf")
        );
    }

    #[test]
    fn extract_citation_pdf_url_single_quote() {
        let html = "<meta name='citation_pdf_url' content='/files/x.pdf'>";
        assert_eq!(
            extract_citation_pdf_url(html).as_deref(),
            Some("/files/x.pdf")
        );
    }

    #[test]
    fn extract_citation_pdf_url_attr_order_swapped() {
        let html = r#"<meta content="https://e.com/a.pdf" name="citation_pdf_url">"#;
        assert_eq!(
            extract_citation_pdf_url(html).as_deref(),
            Some("https://e.com/a.pdf")
        );
    }

    #[test]
    fn extract_citation_pdf_url_case_insensitive() {
        let html = r#"<META NAME="Citation_Pdf_Url" CONTENT="https://e.com/y.pdf">"#;
        assert_eq!(
            extract_citation_pdf_url(html).as_deref(),
            Some("https://e.com/y.pdf")
        );
    }

    #[test]
    fn extract_citation_pdf_url_missing() {
        assert!(extract_citation_pdf_url("<html>nothing here</html>").is_none());
    }

    #[test]
    fn extract_citation_pdf_url_other_meta_ignored() {
        let html = r#"<meta name="description" content="abc">
                      <meta name="not_pdf_url" content="https://e.com/wrong.pdf">"#;
        assert!(extract_citation_pdf_url(html).is_none());
    }

    #[test]
    fn normalize_doi_strips_url_prefix() {
        assert_eq!(
            normalize_doi(Some("https://doi.org/10.1038/abc")).as_deref(),
            Some("10.1038/abc")
        );
        assert_eq!(
            normalize_doi(Some("doi:10.1234/xyz")).as_deref(),
            Some("10.1234/xyz")
        );
        // 嵌套双重前缀也应剥掉
        assert_eq!(
            normalize_doi(Some("https://doi.org/https://doi.org/10.1/a")).as_deref(),
            Some("10.1/a")
        );
        assert_eq!(normalize_doi(Some("")), None);
        assert_eq!(normalize_doi(None), None);
    }

    #[test]
    fn resolve_url_absolute_passthrough() {
        assert_eq!(
            resolve_url("https://e.com/a", "https://other.com/b.pdf"),
            "https://other.com/b.pdf"
        );
    }

    #[test]
    fn resolve_url_relative_join() {
        assert_eq!(
            resolve_url("https://e.com/landing/x", "/files/a.pdf"),
            "https://e.com/files/a.pdf"
        );
        assert_eq!(
            resolve_url("https://e.com/landing/", "a.pdf"),
            "https://e.com/landing/a.pdf"
        );
    }

    #[test]
    fn is_safe_id_basic() {
        assert!(is_safe_id("abc-123_DEF.456"));
        assert!(!is_safe_id("../etc/passwd"));
        assert!(!is_safe_id("a/b"));
        assert!(!is_safe_id(""));
    }

    #[test]
    fn urlencoding_encode_minimal() {
        assert_eq!(urlencoding_encode("10.1234/abc"), "10.1234/abc");
        assert_eq!(urlencoding_encode("10/with space"), "10/with%20space");
        assert_eq!(urlencoding_encode("a#b?c"), "a%23b%3Fc");
    }
}
