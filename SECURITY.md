# Segurança do webhook / Security

O E-pizzaria utiliza um webhook Flask. A branch de segurança exige um token
privado em cada requisição, no cabeçalho `X-Webhook-Token`.

## Configuração
1. Gere um valor aleatório longo localmente (não o publique).
2. Defina `WEBHOOK_SHARED_SECRET` no `.env` do servidor.
3. Configure o gateway ou proxy HTTPS para incluir o cabeçalho
   `X-Webhook-Token` com esse mesmo valor ao encaminhar mensagens da Evolution API.
4. Deixe `IGNORE_FROM_ME=true` em produção. O valor padrão agora é verdadeiro.
5. O Flask escuta em 127.0.0.1 por padrão. Para exposição externa, use um
   proxy reverso autenticado com HTTPS e controles de acesso; não exponha
   diretamente o servidor de desenvolvimento.
6. Faça backup das credenciais e valide o envio/recepção em homologação antes
   da implantação.

Sem `WEBHOOK_SHARED_SECRET`, o endpoint retorna HTTP 503. Requisições
sem token válido retornam HTTP 401. Tokens inválidos não fazem chamadas de IA
nem registram dados.

## Arquivos de demonstração
`payload_debug.txt` e `ultimo_payload.json` já existem no histórico.
Eles foram preservados para revisão, **sem presumir que sejam dados reais**.
O código não grava mais esses arquivos; o `.gitignore` previne novos
arquivos locais, mas não remove cópias já versionadas.

Revise manualmente nomes, telefones, mensagens, tokens e identificadores nesses
artefatos antes de publicar exemplos. Caso algum valor tenha sido real, substitua
o arquivo por exemplo sanitizado, considere limpeza de histórico e faça rotação
das credenciais afetadas. Não confunda um exemplo de API com vazamento confirmado.

## Antes de produzir
Adicione controle de taxa e filas, persistência de idempotência entre reinícios,
limpeza programada de históricos de clientes e testes de recuperação de falhas.
