# Recriar Action do Dr. Imagem sem OAuth

## Diagnostico

Se apareceu:

```text
Dropbox OAuth 400 — invalid_client: Invalid client_id or client_secret
```

entao o Dr. Imagem ainda esta tentando autenticar direto no Dropbox.

Isso esta errado para o fluxo novo.

## Regra definitiva

O Dr. Imagem nao usa Dropbox OAuth.

O Dr. Imagem usa:

```text
Chave API -> Header -> Authorization -> Bearer VISUAL_PROXY_API_KEY
```

Quem usa Dropbox OAuth/refresh token e o servidor Render:

```text
ultimateENEM Visual Proxy -> Dropbox
```

## Passo a passo no GPT Builder

1. Abra o GPT Builder do `Dr. Imagem ENEM Premium`.
2. Va em `Configure`.
3. Va em `Actions`.
4. Apague qualquer action antiga que use Dropbox direto ou OAuth.
5. Clique em criar nova action.
6. Em autenticacao, escolha:

```text
Chave API
```

7. Local:

```text
Header
```

8. Nome do header:

```text
Authorization
```

9. Valor:

```text
Bearer COLE_AQUI_A_VISUAL_PROXY_API_KEY_DO_RENDER
```

10. Cole o schema:

```text
openapi_gpt_action_visual_proxy.yaml
```

## Primeiro teste obrigatorio

Antes de buscar PDF, mande ao Dr. Imagem:

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

## Segundo teste

```text
Use buscar_pdf_dropbox para localizar 2025_PV_impresso_D3_CD1.pdf dentro de /ENEM 2026 App. Retorne apenas os caminhos encontrados.
```

## Terceiro teste

```text
Use renderizar_pagina_pdf no caminho encontrado. Renderize a pagina 1 em PNG, dpi 220, com output_name teste_proxy_pagina_001. Retorne o dropbox_path e o temporary_link.
```

## Se der erro

- `401 Chave do proxy ausente ou invalida`: o valor do header Authorization no GPT Builder esta errado.
- `502 dropbox_oauth_status invalid_client`: as variaveis do Render `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET` e `DROPBOX_REFRESH_TOKEN` nao pertencem ao mesmo app Dropbox.
- `Dropbox OAuth 400 invalid_client` na tela do GPT: a action esta em OAuth; apague e recrie com Chave API.
