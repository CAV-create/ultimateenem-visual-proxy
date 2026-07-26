# ultimateENEM Visual Proxy

Backend para o Dr. Imagem ENEM Premium chamar em vez de tentar manipular Dropbox/PDF diretamente dentro do GPT.

## O que resolve

O GPT externo consegue chamar Actions, mas nao consegue abrir o binario do PDF retornado pela Action Dropbox para recortar imagens. Este proxy faz a parte pesada:

1. recebe `pdf_path`, `page_number` e coordenadas;
2. baixa o PDF real do Dropbox;
3. renderiza a pagina com PyMuPDF;
4. recorta o recurso visual com sangria controlada;
5. salva PNG e WebP no Dropbox;
6. devolve links temporarios para auditoria.

## Variaveis de ambiente

```bash
DROPBOX_REFRESH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxx
DROPBOX_APP_KEY=xxxxxxxxxxxxxxx
DROPBOX_APP_SECRET=xxxxxxxxxxxxxxx
# Opcional/legado, apenas para teste rapido:
DROPBOX_ACCESS_TOKEN=
VISUAL_PROXY_API_KEY=uma-chave-longa-para-o-gpt
DROPBOX_OUTPUT_ROOT="/ENEM 2026 App/ULTIMATE_ENEM_DR_IMAGEM_PIPELINE/02_DR_IMAGEM_PARA_CODEX_PERFEITAS"
DEFAULT_RENDER_DPI=220
```

Para producao permanente, use `DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_KEY` e `DROPBOX_APP_SECRET`. O proxy renova o access token automaticamente quando o Dropbox retornar token expirado. O token `sl...` pode ficar vazio ou ser usado apenas como plano B de teste.

## Rodar localmente

```bash
cd /Users/CAV/Documents/Codex/2026-06-12/quero-escrever-um-app-de-produtividade/work/ultimateenem_visual_proxy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# preencher .env
uvicorn main:app --reload --port 8000
```

Teste:

```bash
curl http://127.0.0.1:8000/health
```

## Deploy recomendado

Use Render, Railway, Fly.io ou um VPS com Docker. Vercel nao e a melhor primeira opcao para este caso porque renderizacao de PDF com bibliotecas nativas costuma ser mais instavel em serverless.

O `Dockerfile` ja esta preparado para o Render, usando a variavel `PORT` automaticamente.

No Render:

1. Suba esta pasta para um repositorio GitHub.
2. Crie um Web Service com Docker.
3. Configure as variaveis de ambiente.
4. Copie a URL publica HTTPS.
5. No schema `openapi_gpt_action_visual_proxy.yaml`, confirme:

```yaml
servers:
  - url: https://ultimateenem-visual-proxy.onrender.com
```

## Configurar no GPT Builder

1. Adicione uma Action.
2. Autenticacao: `Chave API`.
3. Tipo/local da chave: header.
4. Nome do header: `Authorization`.
5. Valor: `Bearer SUA_VISUAL_PROXY_API_KEY`.
6. Cole o arquivo `openapi_gpt_action_visual_proxy.yaml`.

## Exemplo de recorte

Coordenadas normalizadas sao mais praticas para o GPT:

```json
{
  "pdf_path": "/ENEM 2026 App/ENEM/2025/2ª APLICAÇÃO - COP 30/1° DIA/2025_PV_impresso_D3_CD1.pdf",
  "page_number": 12,
  "bbox": { "x": 0.12, "y": 0.28, "w": 0.76, "h": 0.32 },
  "units": "normalized",
  "pad_px": 22,
  "output_basename": "bloco27_q07_texto_i_visual",
  "make_png": true,
  "make_webp": true,
  "webp_quality": 88
}
```

O retorno traz `temporary_link` e `dropbox_path` para cada imagem gerada.

## Regra do Dr. Imagem

O Dr. Imagem nao deve afirmar que recortou olhando o PDF se nao chamar este proxy. Para cada caso, ele deve:

1. localizar o PDF ou receber `pdf_path`;
2. renderizar pagina quando precisar conferir;
3. chamar `/v1/pdf/crop`;
4. mostrar link/preview do resultado;
5. aguardar homologacao do Prof. CAV;
6. informar o `dropbox_path` final para o Codex integrar no banco premium.

## Renovacao automatica do Dropbox

O proxy nao deve depender de um `DROPBOX_ACCESS_TOKEN=sl...` manual, porque esse token expira. Configure no Render:

```bash
DROPBOX_REFRESH_TOKEN=...
DROPBOX_APP_KEY=...
DROPBOX_APP_SECRET=...
```

Com essas tres variaveis, qualquer chamada ao Dropbox usa o token em cache; se o Dropbox devolver `401 expired_access_token`, o proxy renova e tenta a chamada novamente.
