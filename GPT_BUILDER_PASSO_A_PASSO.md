# Dr. Imagem ENEM Premium — Action do Proxy

Use este guia quando o backend `ultimateENEM Visual Proxy` ja estiver publicado em HTTPS.

## Ideia central

O Dr. Imagem NAO chama mais o Dropbox direto para abrir PDF.

Ele chama o nosso proxy:

```text
Dr. Imagem -> ultimateENEM Visual Proxy -> Dropbox -> PDF -> recorte -> Dropbox
```

Assim o GPT nao precisa manipular binario de PDF. O servidor faz isso e renova o token Dropbox automaticamente.

## Regra que nao pode ser quebrada

```text
NAO use OAuth no GPT Builder.
NAO use Dropbox OAuth.
NAO cole App key/App secret do Dropbox no GPT Builder.
```

Se aparecer erro `Dropbox OAuth 400 invalid_client`, o GPT esta chamando Dropbox direto. Apague essa action e recrie com `Chave API`.

## No GPT Builder

### 1. Action

Adicionar Action.

### 2. Autenticacao

Tipo:

```text
Chave API
```

Local:

```text
Header
```

Nome do header:

```text
Authorization
```

Valor da chave:

```text
Bearer COLE_AQUI_A_VISUAL_PROXY_API_KEY
```

Importante: nao cole token `sl...` do Dropbox aqui. O token Dropbox fica apenas no backend Render.

### 3. Schema

Cole o conteudo de:

```text
openapi_gpt_action_visual_proxy.yaml
```

A URL publica real ja deve estar no schema:

```text
https://ultimateenem-visual-proxy.onrender.com
```

## Teste obrigatorio antes do primeiro lote

```text
Use a action testar_oauth_dropbox_proxy. Retorne exatamente a resposta.
```

Resultado esperado:

```json
{
  "ok": true,
  "message": "Dropbox OAuth renovou access_token com sucesso pelo proxy.",
  "dropbox_refresh_configured": true
}
```

Se esse teste falhar com `invalid_client`, o problema esta nas variaveis do Render: `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` e `DROPBOX_REFRESH_TOKEN` precisam pertencer ao mesmo app Dropbox.

## O que o Dr. Imagem deve fazer

Quando receber um caso, ele deve:

1. usar `testar_oauth_dropbox_proxy` antes do primeiro lote do dia;
2. usar `buscar_pdf_dropbox` se nao tiver o caminho completo;
3. usar `renderizar_pagina_pdf` para ver a pagina inteira quando precisar conferir;
4. usar `recortar_recurso_visual_pdf` para gerar PNG/WebP;
5. devolver os links temporarios para o Prof. CAV auditar;
6. nunca afirmar que salvou arquivo sem o retorno real do proxy.

## Exemplo de comando para o Dr. Imagem

```text
Use o ultimateENEM Visual Proxy.
PDF: /ENEM 2026 App/ENEM/2025/2ª APLICAÇÃO - COP 30/1° DIA/2025_PV_impresso_D3_CD1.pdf
Renderize a pagina 12 para conferir.
Depois recorte o recurso visual da Q07 com coordenadas normalizadas aproximadas:
x=0.12, y=0.28, w=0.76, h=0.32.
Salve em:
/ENEM 2026 App/ULTIMATE_ENEM_DR_IMAGEM_PIPELINE/02_DR_IMAGEM_PARA_CODEX_PERFEITAS/bloco27_cti_repair_8
Nome base:
bloco27_q07_texto_i_visual
Gere PNG para auditoria e WebP leve para app.
Use pad_px entre 18 e 28 para evitar corte rente.
```

## Campos que importam

- `pdf_path`: caminho completo no Dropbox.
- `page_number`: pagina do PDF, comecando em 1.
- `bbox`: retangulo de recorte.
- `units`: use `normalized` quando as coordenadas forem de 0 a 1.
- `pad_px`: sangria uniforme; comece com 22.
- `output_folder`: pasta final no Dropbox.
- `output_basename`: nome base sem extensao.

## Pasta padrao do pipeline

```text
/ENEM 2026 App/ULTIMATE_ENEM_DR_IMAGEM_PIPELINE/02_DR_IMAGEM_PARA_CODEX_PERFEITAS
```

Para cada lote, criar subpasta:

```text
bloco27_cti_repair_8
bloco28_cti_repair
bloco29_cti_repair
```

## Regra de seguranca

O GPT Builder recebe apenas `VISUAL_PROXY_API_KEY`.

O servidor Render recebe:

```text
DROPBOX_REFRESH_TOKEN=...
DROPBOX_APP_KEY=...
DROPBOX_APP_SECRET=...
VISUAL_PROXY_API_KEY=...
```

`DROPBOX_ACCESS_TOKEN=sl...` e opcional/legado, apenas para teste. Para nao travar novamente por `expired_access_token`, use as tres variaveis definitivas acima. O GPT nao recebe token Dropbox.
