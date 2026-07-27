from __future__ import annotations

import html as html_lib
import json
from typing import Any, Literal

from fastapi import Body, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from main import (
    DROPBOX_OUTPUT_ROOT,
    app,
    clean_filename,
    dropbox_join,
    dropbox_temporary_link,
    dropbox_upload,
    require_proxy_auth,
)

app.version = "1.3.0"


@app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy_policy() -> str:
    return """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Politica de Privacidade - ultimateENEM Visual Proxy</title>
  <style>
    :root { color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { max-width: 860px; margin: 0 auto; padding: 40px 20px; line-height: 1.6; }
    code { background: rgba(127,127,127,.15); padding: 2px 5px; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>Politica de Privacidade - ultimateENEM Visual Proxy</h1>
  <p><strong>Ultima atualizacao:</strong> 26 de julho de 2026.</p>
  <p>Este servico privado apoia o pipeline ultimateENEM para localizar PDFs autorizados no Dropbox, renderizar paginas, recortar recursos visuais e criar pranchas de auditoria.</p>
  <h2>Dados processados</h2>
  <p>Processamos caminhos de arquivos, nomes de saida, coordenadas de recorte e metadados enviados por operadores autorizados ou por uma Action configurada com chave do proxy.</p>
  <h2>Dropbox</h2>
  <p>O Dropbox e usado apenas para ler arquivos-fonte do projeto e salvar pre-visualizacoes, imagens tratadas e HTMLs de auditoria nas pastas configuradas do pipeline.</p>
  <h2>Credenciais</h2>
  <p>Tokens e chaves ficam em variaveis de ambiente no Render. O GPT deve chamar o proxy com <code>Authorization: Bearer</code> usando a chave do proxy.</p>
  <h2>Compartilhamento</h2>
  <p>Nao vendemos dados e nao usamos arquivos do projeto para publicidade.</p>
</body>
</html>"""


class AuditBoardResponse(BaseModel):
    status: Literal["ok"]
    audit_title: str
    board_kind: Literal["localizacao", "final"]
    case_count: int
    expected_case_count: int
    dropbox_path: str
    temporary_link: str


def pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def coerce_path(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return pick(value, "path", "dropbox_path", "path_display", "link", "temporary_link")
    return str(value).strip()


def path_has_any(path: str | None, parts: list[str]) -> bool:
    if not path:
        return False
    low = path.lower()
    return any(part.lower() in low for part in parts)


def expected_count_from(payload: dict[str, Any]) -> int:
    raw = pick(payload, "expected_case_count", "expected_count", "total_esperado", "total_cases")
    if raw in (None, ""):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EXPECTED_CASE_COUNT_REQUIRED",
                "message": "Informe expected_case_count. Pranchas parciais nao podem parecer lote completo.",
            },
        )
    try:
        count = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="expected_case_count precisa ser numero inteiro.")
    if count <= 0:
        raise HTTPException(status_code=400, detail="expected_case_count precisa ser maior que zero.")
    return count


def normalize_cases(payload: dict[str, Any]) -> list[dict[str, str | None]]:
    raw_cases = pick(payload, "cases", "casos", "items", "questoes")
    if isinstance(raw_cases, dict):
        raw_cases = list(raw_cases.values())
    if not isinstance(raw_cases, list) or not raw_cases:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "CASES_REQUIRED",
                "message": "Envie uma lista de casos em cases/casos/items.",
            },
        )

    normalized: list[dict[str, str | None]] = []
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"Caso {index} nao e objeto.")
        case_id = str(pick(item, "case_id", "id", "questao", "q", "numero", default=f"Q{index:02d}")).strip()
        title = str(pick(item, "title", "titulo", "descricao", "description", default=case_id)).strip()
        original_path = coerce_path(
            pick(
                item,
                "original_path",
                "original",
                "original_dropbox_path",
                "pdf_bruto_path",
                "bruto_path",
                "raw_path",
                "source_path",
            )
        )
        treated_path = coerce_path(
            pick(
                item,
                "treated_path",
                "treated",
                "tratada_path",
                "imagem_tratada_path",
                "final_path",
                "processed_path",
            )
        )
        notes = pick(item, "notes", "observacoes", "nota", "comentario", "comment")
        normalized.append(
            {
                "case_id": case_id,
                "title": title,
                "original_path": original_path,
                "treated_path": treated_path,
                "notes": str(notes).strip() if notes not in (None, "") else None,
            }
        )
    return normalized


def validate_audit_board_payload(payload: dict[str, Any], cases: list[dict[str, str | None]]) -> tuple[Literal["localizacao", "final"], int]:
    board_kind = str(pick(payload, "board_kind", "tipo_prancha", default="final")).strip().lower()
    if board_kind not in {"localizacao", "final"}:
        raise HTTPException(status_code=400, detail="board_kind deve ser 'localizacao' ou 'final'.")
    expected = expected_count_from(payload)
    if len(cases) != expected:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "ENTREGA_INCOMPLETA",
                "message": f"A prancha recebeu {len(cases)} casos, mas expected_case_count={expected}.",
            },
        )

    seen: set[str] = set()
    errors: list[dict[str, Any]] = []
    for case in cases:
        case_id = case["case_id"] or "sem_id"
        if case_id in seen:
            errors.append({"case_id": case_id, "error": "DUPLICATE_CASE_ID"})
        seen.add(case_id)

        original_path = case.get("original_path")
        treated_path = case.get("treated_path")
        if not original_path:
            errors.append({"case_id": case_id, "error": "MISSING_ORIGINAL_PATH"})
        if path_has_any(original_path, ["/tratadas/", "/recortes/", "/perfeitas/"]):
            errors.append({"case_id": case_id, "error": "ORIGINAL_LOOKS_TREATED", "path": original_path})

        if board_kind == "final":
            if not treated_path:
                errors.append({"case_id": case_id, "error": "MISSING_TREATED_PATH"})
            elif not treated_path.startswith("http"):
                if path_has_any(treated_path, ["/_candidatas/", "/brutos/", "/originais/"]):
                    errors.append({"case_id": case_id, "error": "TREATED_LOOKS_RAW", "path": treated_path})
                if not path_has_any(treated_path, ["/tratadas/", "/recortes/", "/perfeitas/"]):
                    errors.append({"case_id": case_id, "error": "TREATED_PATH_OUTSIDE_FINAL_FOLDERS", "path": treated_path})

    if errors:
        raise HTTPException(status_code=400, detail={"code": "AUDIT_BOARD_VALIDATION_FAILED", "errors": errors})
    return board_kind, expected


async def link_for_visual(value: str) -> dict[str, str]:
    if value.startswith("http://") or value.startswith("https://"):
        return {"path": value, "link": value}
    link_data = await dropbox_temporary_link(value)
    return {"path": value, "link": link_data["link"]}


def issue_checkbox(issue_id: str, label: str) -> str:
    safe_id = html_lib.escape(issue_id, quote=True)
    safe_label = html_lib.escape(label)
    return f'<label><input type="checkbox" class="issue" value="{safe_label}" data-issue="{safe_id}"> {safe_label}</label>'


def build_audit_board_html(audit_title: str, board_kind: str, cases: list[dict[str, Any]]) -> str:
    escaped_title = html_lib.escape(audit_title)
    issue_labels = [
        ("faltou_imagem", "Faltou imagem/recurso visual"),
        ("fonte_ausente", "Fonte ausente"),
        ("fonte_misturada", "Fonte misturada com pergunta"),
        ("texto_cortado", "Texto/enunciado incompleto"),
        ("paragrafo", "Paragrafo ou quebra de texto"),
        ("numero_errado", "Questao duplicada ou numero errado"),
        ("recorte_rente", "Recorte muito rente"),
        ("lixo_ocr", "Sobrou OCR/lixo"),
        ("conferir_original", "Conferir original"),
    ]
    issue_html = "".join(issue_checkbox(issue_id, label) for issue_id, label in issue_labels)
    cards: list[str] = []
    for index, case in enumerate(cases, start=1):
        case_id = html_lib.escape(case["case_id"])
        title = html_lib.escape(case["title"])
        notes = html_lib.escape(case.get("notes") or "")
        original = case["original"]
        treated = case.get("treated")
        original_img = f'<img src="{html_lib.escape(original["link"], quote=True)}" alt="Original {case_id}" loading="lazy">'
        treated_img = (
            f'<img src="{html_lib.escape(treated["link"], quote=True)}" alt="Tratada {case_id}" loading="lazy">'
            if treated
            else '<div class="missing">Prancha de localizacao: imagem tratada ainda nao informada.</div>'
        )
        treated_code = html_lib.escape(treated["path"]) if treated else ""
        cards.append(
            f"""
            <article class="case-card" data-case="{case_id}" data-title="{title}">
              <header>
                <span class="case-number">{index:02d}</span>
                <div>
                  <h2>{case_id} - {title}</h2>
                  <p>{notes}</p>
                </div>
              </header>
              <div class="compare-grid">
                <section>
                  <h3>Original / PDF bruto</h3>
                  <div class="image-frame">{original_img}</div>
                  <code>{html_lib.escape(original["path"])}</code>
                </section>
                <section>
                  <h3>Imagem tratada</h3>
                  <div class="image-frame">{treated_img}</div>
                  <code>{treated_code}</code>
                </section>
              </div>
              <div class="audit-controls">
                <label class="homologacao"><input type="checkbox" class="approved"><span>HOMOLOGADA</span></label>
                <div class="issue-grid">{issue_html}</div>
                <label class="reason-label">Motivo, caso nao seja homologada<textarea class="reason" placeholder="Descreva o ajuste necessario."></textarea></label>
              </div>
            </article>
            """
        )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{ color-scheme: dark; --bg:#08090b; --panel:#111316; --panel2:#171a1f; --line:#343943; --text:#f5f7fb; --muted:#a8afb9; --gold:#ffc72c; --blue:#14a9d1; --ok:#8fd2bd; --bad:#ff6b6b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width:min(1880px, calc(100vw - 28px)); margin:0 auto; padding:24px 0 40px; }}
    h1 {{ margin:0 0 6px; font-size:clamp(28px,3vw,42px); letter-spacing:0; }}
    .subtitle {{ margin:0 0 20px; color:var(--muted); font-size:17px; }}
    .case-card {{ border:1px solid var(--line); border-radius:8px; background:var(--panel); padding:18px; margin:0 0 22px; }}
    .case-card header {{ display:flex; gap:14px; align-items:flex-start; border-bottom:1px solid var(--line); padding-bottom:12px; margin-bottom:14px; }}
    .case-number {{ display:inline-grid; place-items:center; width:42px; height:42px; border-radius:8px; background:var(--gold); color:#101010; font-weight:900; flex:0 0 auto; }}
    h2 {{ margin:0; font-size:22px; letter-spacing:0; }}
    header p {{ margin:4px 0 0; color:var(--muted); }}
    .compare-grid {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; align-items:start; }}
    h3 {{ margin:0 0 8px; color:#aee7ee; font-size:17px; letter-spacing:0; }}
    .image-frame {{ min-height:240px; max-height:82vh; display:grid; place-items:start center; border:1px solid var(--line); border-radius:8px; background:#f8f8f8; overflow:auto; padding:8px; }}
    img {{ display:block; max-width:100%; height:auto; }}
    code {{ display:block; margin-top:8px; color:var(--muted); white-space:normal; word-break:break-word; font-size:12px; }}
    .missing {{ color:#333; padding:28px; text-align:center; font-weight:800; place-self:center; }}
    .audit-controls {{ margin-top:14px; border-top:1px solid var(--line); padding-top:12px; }}
    .homologacao {{ display:inline-flex; align-items:center; gap:10px; margin:0 0 10px; color:var(--ok); font-size:20px; font-weight:900; }}
    input[type="checkbox"] {{ width:22px; height:22px; accent-color:var(--blue); vertical-align:middle; }}
    .issue-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px 14px; margin:6px 0 12px; color:var(--muted); }}
    .issue-grid label {{ display:flex; align-items:center; gap:8px; min-width:0; }}
    .reason-label {{ display:block; color:var(--text); font-size:17px; }}
    textarea {{ display:block; width:100%; min-height:86px; margin-top:8px; border:1px solid var(--line); border-radius:8px; background:var(--panel2); color:var(--text); padding:12px; font:inherit; resize:vertical; }}
    .parecer {{ position:sticky; bottom:0; border:1px solid var(--line); border-radius:8px 8px 0 0; background:#0c0e11f2; padding:16px; backdrop-filter:blur(8px); }}
    #parecer {{ min-height:170px; white-space:pre-wrap; }}
    button {{ margin-top:10px; border:0; border-radius:8px; background:var(--gold); color:#111; padding:12px 18px; font-weight:900; cursor:pointer; }}
    @media (max-width:980px) {{ .compare-grid {{ grid-template-columns:1fr; }} .issue-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>{escaped_title}</h1>
    <p class="subtitle">Tipo: {html_lib.escape(board_kind)}. Compare lado a lado, marque homologada ou selecione os erros e escreva o motivo.</p>
    {''.join(cards)}
    <section class="parecer">
      <h2>Parecer para enviar no chat</h2>
      <textarea id="parecer" readonly></textarea>
      <button type="button" id="copy">Copiar parecer</button>
    </section>
  </main>
  <script>
    const title = {json.dumps(audit_title, ensure_ascii=False)};
    function buildReport() {{
      const lines = [title];
      document.querySelectorAll('.case-card').forEach(card => {{
        const id = card.dataset.case;
        const caseTitle = card.dataset.title;
        const approved = card.querySelector('.approved').checked;
        const selected = Array.from(card.querySelectorAll('.issue:checked')).map(item => item.value);
        const reason = card.querySelector('.reason').value.trim();
        if (approved) {{
          lines.push(`${{id}} - ${{caseTitle}}: HOMOLOGADA`);
        }} else {{
          const chunks = [];
          if (selected.length) chunks.push(selected.join(', '));
          if (reason) chunks.push(reason);
          lines.push(`${{id}} - ${{caseTitle}}: NAO HOMOLOGADA${{chunks.length ? ' - ' + chunks.join(' | ') : ''}}`);
        }}
      }});
      document.getElementById('parecer').value = lines.join('\n');
    }}
    document.addEventListener('input', buildReport);
    document.addEventListener('change', buildReport);
    document.getElementById('copy').addEventListener('click', async () => {{
      buildReport();
      await navigator.clipboard.writeText(document.getElementById('parecer').value);
    }});
    buildReport();
  </script>
</body>
</html>"""


@app.post("/v1/audit/create-board", response_model=AuditBoardResponse, dependencies=[Depends(require_proxy_auth)])
async def create_audit_board(payload: dict[str, Any] = Body(...)) -> AuditBoardResponse:
    audit_title = str(pick(payload, "audit_title", "title", "titulo", default="AUDITORIA VISUAL")).strip()
    output_folder = pick(payload, "output_folder", "folder", "pasta", default=None) or DROPBOX_OUTPUT_ROOT
    output_name = str(pick(payload, "output_name", "name", "nome", "nome_arquivo", default=clean_filename(audit_title))).strip()
    if not output_name:
        output_name = clean_filename(audit_title)

    normalized_cases = normalize_cases(payload)
    board_kind, expected_count = validate_audit_board_payload(payload, normalized_cases)

    linked_cases: list[dict[str, Any]] = []
    for case in normalized_cases:
        treated_path = case.get("treated_path")
        linked_cases.append(
            {
                "case_id": case["case_id"],
                "title": case["title"],
                "notes": case.get("notes"),
                "original": await link_for_visual(case["original_path"] or ""),
                "treated": await link_for_visual(treated_path) if treated_path else None,
            }
        )

    html_text = build_audit_board_html(audit_title, board_kind, linked_cases)
    dropbox_path = dropbox_join(str(output_folder), f"{clean_filename(output_name)}.html")
    await dropbox_upload(dropbox_path, html_text.encode("utf-8"))
    link_data = await dropbox_temporary_link(dropbox_path)
    return AuditBoardResponse(
        status="ok",
        audit_title=audit_title,
        board_kind=board_kind,
        case_count=len(normalized_cases),
        expected_case_count=expected_count,
        dropbox_path=dropbox_path,
        temporary_link=link_data["link"],
    )
