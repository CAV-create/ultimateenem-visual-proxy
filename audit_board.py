from __future__ import annotations

import html as html_lib
import json
from typing import Any, Literal

from fastapi import Depends
from pydantic import BaseModel, Field

from main import app, clean_filename, dropbox_join, dropbox_temporary_link, dropbox_upload, require_proxy_auth

app.version = "1.2.0"


class AuditVisualCase(BaseModel):
    case_id: str = Field(..., description="Identificador curto do caso, como Q07.")
    title: str = Field(..., description="Titulo curto exibido na prancha.")
    original_path: str = Field(..., description="Caminho Dropbox da pagina/recorte bruto original.")
    treated_path: str | None = Field(None, description="Caminho Dropbox da imagem tratada final, se ja existir.")
    notes: str | None = Field(None, description="Observacao interna opcional.")


class AuditBoardRequest(BaseModel):
    audit_title: str = Field("AUDITORIA VISUAL", description="Titulo da prancha.")
    cases: list[AuditVisualCase] = Field(..., min_length=1, max_length=80)
    output_folder: str | None = Field(None, description="Pasta Dropbox de saida; se vazio usa DROPBOX_OUTPUT_ROOT.")
    output_name: str = Field(..., description="Nome base do HTML sem extensao.")


class AuditBoardResponse(BaseModel):
    status: Literal["ok"]
    audit_title: str
    case_count: int
    dropbox_path: str
    temporary_link: str


async def link_for_dropbox_image(path: str) -> dict[str, str]:
    link_data = await dropbox_temporary_link(path)
    return {"path": path, "link": link_data["link"]}


def build_audit_board_html(audit_title: str, cases: list[dict[str, Any]]) -> str:
    escaped_title = html_lib.escape(audit_title)
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
            else '<div class="missing">Imagem tratada ainda nao informada.</div>'
        )
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
                  <code>{html_lib.escape(treated["path"]) if treated else ""}</code>
                </section>
              </div>
              <label class="homologacao">
                <input type="checkbox" class="approved">
                <span>HOMOLOGADA</span>
              </label>
              <label class="reason-label">
                Motivo, caso nao seja homologada
                <textarea class="reason" placeholder="Descreva o ajuste necessario."></textarea>
              </label>
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
    :root {{ color-scheme: dark; --bg:#08090b; --panel:#111316; --panel2:#171a1f; --line:#343943; --text:#f5f7fb; --muted:#a8afb9; --gold:#ffc72c; --blue:#14a9d1; --ok:#8fd2bd; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width:min(1800px, calc(100vw - 32px)); margin:0 auto; padding:28px 0 40px; }}
    h1 {{ margin:0 0 8px; font-size:clamp(28px,3vw,44px); letter-spacing:0; }}
    .subtitle {{ margin:0 0 24px; color:var(--muted); font-size:18px; }}
    .case-card {{ border:1px solid var(--line); border-radius:8px; background:var(--panel); padding:20px; margin:0 0 22px; }}
    .case-card header {{ display:flex; gap:14px; align-items:flex-start; border-bottom:1px solid var(--line); padding-bottom:14px; margin-bottom:16px; }}
    .case-number {{ display:inline-grid; place-items:center; width:44px; height:44px; border-radius:8px; background:var(--gold); color:#101010; font-weight:900; flex:0 0 auto; }}
    h2 {{ margin:0; font-size:24px; letter-spacing:0; }}
    header p {{ margin:4px 0 0; color:var(--muted); }}
    .compare-grid {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:18px; align-items:start; }}
    h3 {{ margin:0 0 10px; color:#aee7ee; font-size:18px; letter-spacing:0; }}
    .image-frame {{ min-height:220px; display:grid; place-items:center; border:1px solid var(--line); border-radius:8px; background:#f8f8f8; overflow:auto; }}
    img {{ display:block; max-width:100%; height:auto; }}
    code {{ display:block; margin-top:8px; color:var(--muted); white-space:normal; word-break:break-word; font-size:12px; }}
    .missing {{ color:#333; padding:28px; text-align:center; font-weight:700; }}
    .homologacao {{ display:inline-flex; align-items:center; gap:10px; margin:16px 0 10px; color:var(--ok); font-size:20px; font-weight:800; }}
    .homologacao input {{ width:24px; height:24px; accent-color:var(--blue); }}
    .reason-label {{ display:block; color:var(--text); font-size:18px; }}
    textarea {{ display:block; width:100%; min-height:92px; margin-top:8px; border:1px solid var(--line); border-radius:8px; background:var(--panel2); color:var(--text); padding:14px; font:inherit; resize:vertical; }}
    .parecer {{ position:sticky; bottom:0; border:1px solid var(--line); border-radius:8px 8px 0 0; background:#0c0e11f2; padding:18px; backdrop-filter:blur(8px); }}
    #parecer {{ min-height:180px; white-space:pre-wrap; }}
    button {{ margin-top:10px; border:0; border-radius:8px; background:var(--gold); color:#111; padding:12px 18px; font-weight:900; cursor:pointer; }}
    @media (max-width:900px) {{ .compare-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>{escaped_title}</h1>
    <p class="subtitle">Compare o original/PDF bruto com a imagem tratada. Marque homologada ou escreva o motivo do ajuste.</p>
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
        const reason = card.querySelector('.reason').value.trim();
        if (approved) {{ lines.push(`${{id}} - ${{caseTitle}}: HOMOLOGADA`); }}
        else {{ lines.push(`${{id}} - ${{caseTitle}}: NAO HOMOLOGADA${{reason ? ' - ' + reason : ''}}`); }}
      }});
      document.getElementById('parecer').value = lines.join('\n');
    }}
    document.addEventListener('input', buildReport);
    document.addEventListener('change', buildReport);
    document.getElementById('copy').addEventListener('click', async () => {{ buildReport(); await navigator.clipboard.writeText(document.getElementById('parecer').value); }});
    buildReport();
  </script>
</body>
</html>"""


@app.post("/v1/audit/create-board", response_model=AuditBoardResponse, dependencies=[Depends(require_proxy_auth)])
async def create_audit_board(request: AuditBoardRequest) -> AuditBoardResponse:
    # Import here so the module reflects the current env/default from main at runtime.
    from main import DROPBOX_OUTPUT_ROOT

    output_folder = request.output_folder or DROPBOX_OUTPUT_ROOT
    linked_cases: list[dict[str, Any]] = []
    for case in request.cases:
        linked_cases.append(
            {
                "case_id": case.case_id,
                "title": case.title,
                "notes": case.notes,
                "original": await link_for_dropbox_image(case.original_path),
                "treated": await link_for_dropbox_image(case.treated_path) if case.treated_path else None,
            }
        )

    html_text = build_audit_board_html(request.audit_title, linked_cases)
    dropbox_path = dropbox_join(output_folder, f"{clean_filename(request.output_name)}.html")
    await dropbox_upload(dropbox_path, html_text.encode("utf-8"))
    link_data = await dropbox_temporary_link(dropbox_path)
    return AuditBoardResponse(
        status="ok",
        audit_title=request.audit_title,
        case_count=len(request.cases),
        dropbox_path=dropbox_path,
        temporary_link=link_data["link"],
    )
