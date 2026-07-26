# Conserto definitivo do Dropbox no ultimateENEM Visual Proxy

## O problema

O proxy estava usando `DROPBOX_ACCESS_TOKEN=sl...`. Esse token expira. Quando expira, o Dr. Imagem recebe:

```text
401 expired_access_token
```

## A solucao definitiva

O proxy foi atualizado para usar refresh token. Agora ele renova o access token automaticamente.

No Render, configure estas variaveis:

```text
DROPBOX_REFRESH_TOKEN=cole_o_refresh_token
DROPBOX_APP_KEY=cole_o_app_key
DROPBOX_APP_SECRET=cole_o_app_secret
VISUAL_PROXY_API_KEY=mantenha_a_chave_do_proxy
DROPBOX_OUTPUT_ROOT=/ENEM 2026 App/ULTIMATE_ENEM_DR_IMAGEM_PIPELINE/02_DR_IMAGEM_PARA_CODEX_PERFEITAS
DEFAULT_RENDER_DPI=220
```

`DROPBOX_ACCESS_TOKEN` pode ficar vazio. Se ficar preenchido e expirar, o proxy ainda tenta renovar usando o refresh token.

## Como gerar o refresh token uma unica vez

1. Pegue o `APP_KEY` e o `APP_SECRET` no Dropbox Developers.
2. Abra este link, trocando `APP_KEY_AQUI` pelo seu App key:

```text
https://www.dropbox.com/oauth2/authorize?client_id=APP_KEY_AQUI&response_type=code&token_access_type=offline
```

3. Autorize no Dropbox.
4. Copie o codigo gerado.
5. No Terminal do Mac, rode:

```bash
python3 /Users/CAV/dropbox_refresh_final.py
```

6. Cole `APP_KEY`, `APP_SECRET` e o codigo do Dropbox quando o script pedir.
7. Copie o valor exibido em `REFRESH_TOKEN NOVO`.
8. Cole esse valor no Render como `DROPBOX_REFRESH_TOKEN`.

## Depois de configurar no Render

1. Clique em `Manual Deploy`.
2. Escolha `Deploy latest commit`.
3. Abra:

```text
https://ultimateenem-visual-proxy.onrender.com/health
```

O esperado:

```json
{
  "ok": true,
  "dropbox_token_configured": true,
  "dropbox_refresh_configured": true
}
```

## Se aparecer `invalid_client`

Esse erro significa que o Dropbox recusou o par `DROPBOX_APP_KEY` + `DROPBOX_APP_SECRET` antes mesmo de renovar o token.

Confira no Render:

```text
DROPBOX_APP_KEY=App key do Dropbox Developers
DROPBOX_APP_SECRET=App secret do mesmo app Dropbox
DROPBOX_REFRESH_TOKEN=refresh token gerado com esse mesmo App key e App secret
```

Cuidados importantes:

- `DROPBOX_APP_KEY` nao comeca com `sl...`; `sl...` e access token antigo.
- `DROPBOX_REFRESH_TOKEN` geralmente nao e igual ao access token `sl...`.
- App key e App secret precisam ser do mesmo app Dropbox usado para gerar o refresh token.
- Ao colar no Render, apague espacos antes/depois do valor.
- Se houver duvida, gere um refresh token novo usando o script guiado e substitua os tres valores no Render.

## O que mudou no codigo

- O GitHub foi atualizado no reposititorio `CAV-create/ultimateenem-visual-proxy`.
- O proxy agora renova automaticamente quando o Dropbox devolve `401 expired_access_token`.
- O proxy tambem remove espacos invisiveis das variaveis e envia `client_id/client_secret` no formato aceito pelo OAuth do Dropbox.
- O GPT/Dr. Imagem continua usando apenas `VISUAL_PROXY_API_KEY`; ele nunca recebe token Dropbox.
