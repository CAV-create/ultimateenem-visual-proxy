# Politica de Privacidade - Dr. Imagem ENEM Premium

Esta politica descreve como o Dr. Imagem ENEM Premium usa o backend ultimateENEM Visual Proxy para localizar, renderizar e recortar recursos visuais de PDFs oficiais do ENEM armazenados no Dropbox do projeto.

## Dados processados

O sistema pode processar:

- caminhos de arquivos PDF no Dropbox;
- nomes de arquivos;
- numeros de paginas;
- coordenadas de recorte;
- imagens geradas a partir de paginas ou trechos dos PDFs;
- metadados tecnicos necessarios para auditoria, como tamanho, formato e caminho salvo.

## Dados nao coletados

O sistema nao foi projetado para coletar dados pessoais de alunos, professores ou visitantes. O fluxo atual trabalha com arquivos educacionais do projeto ultimateENEM e com ativos visuais das questoes.

## Uso do Dropbox

O backend acessa o Dropbox apenas por meio do token configurado no servidor Render. O token do Dropbox nao deve ser inserido no GPT Builder nem compartilhado em conversas. O GPT chama apenas o proxy, e o proxy executa as operacoes autorizadas no Dropbox.

## Finalidade

As operacoes sao usadas exclusivamente para:

- localizar PDFs oficiais;
- renderizar paginas para conferencia;
- recortar recursos visuais de questoes;
- salvar PNG/WebP para auditoria e uso no banco premium do ultimateENEM.

## Compartilhamento

Os arquivos gerados ficam nas pastas configuradas do Dropbox do projeto. O sistema nao vende dados, nao compartilha dados com terceiros para publicidade e nao utiliza os arquivos para fins fora do projeto educacional.

## Seguranca

O acesso ao proxy exige uma chave de autorizacao propria do projeto. O token do Dropbox fica armazenado apenas como variavel de ambiente no Render.

## Contato

Responsavel pelo projeto: Prof. CAV / ultimateENEM.
