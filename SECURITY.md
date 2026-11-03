# Segurança e operação do E-pizzaria

**Atualizado em 2026-11-03.** Este documento descreve as alterações introduzidas pelo [PR #1](https://github.com/Bianchi613/E-pizzaria/pull/1), já mesclado à `main`. É um registro de alterações e um roteiro de verificação, **não uma certificação de segurança**. Os testes não foram executados neste atendimento.

## O que foi corrigido

| Área | Alteração | Arquivo |
| --- | --- | --- |
| Entrada do webhook | Exige um segredo no cabeçalho `X-Webhook-Token`, comparado com `hmac.compare_digest` | `evolution.py` |
| Falha de configuração | Sem `WEBHOOK_SHARED_SECRET` retorna HTTP 503; token incorreto retorna 401 | `evolution.py` |
| Tipo e tamanho de entrada | Exige JSON válido (HTTP 415/400) e limita o corpo a 256 KiB | `evolution.py` |
| Privacidade | Deixa de gravar automaticamente conteúdo integral em `payload_debug.txt`, `ultimo_payload.json` e saídas de depuração | `evolution.py` |
| Erros | Evita devolver detalhes da exceção ao requisitante; erros internos recebem HTTP 500 | `evolution.py` |
| Comunicação externa | Define timeout de 20 segundos no envio de mensagens e trata respostas HTTP de erro | `evolution.py` |
| Inicialização | O Flask só é iniciado ao executar `python evolution.py`; endereço padrão `127.0.0.1` | `evolution.py` |
| Higiene do repositório | Ignora `.env`, logs, memórias e novos payloads locais | `.gitignore` |
| Testes | Cobertura inicial para token ausente/incorreto, tipo de conteúdo e evento ignorado | `tests/test_webhook_security.py` |

**A lógica de cardápio, preços, confirmação e persistência de pedidos não foi redesenhada por este PR.**

## Configuração obrigatória após atualizar

1. Copie `.env.example` para `.env` e mantenha o arquivo fora do Git.
2. Defina um `WEBHOOK_SHARED_SECRET` forte, aleatório e exclusivo, sem usar o texto de exemplo como segredo.
3. Configure a Evolution API **ou um gateway/proxy confiável** para acrescentar `X-Webhook-Token` com exatamente o mesmo valor em cada solicitação encaminhada.
4. Se o seu gateway não permite cabeçalhos customizados, use um proxy que **autentique a origem antes** de acrescentar o cabeçalho. Não use um proxy público que injete o segredo para qualquer remetente.
5. Mantenha `IGNORE_FROM_ME=true` em produção para evitar resposta a mensagens enviadas pelo próprio número.
6. Por padrão o Flask só escuta em `127.0.0.1:5000`. Exponha o endpoint usando HTTPS e proxy reverso com proteção de rede; não exponha diretamente o servidor de desenvolvimento.

Exemplo **sem segredos reais** de variáveis relevantes:

```dotenv
WEBHOOK_SHARED_SECRET=<valor_aleatorio_longo>
IGNORE_FROM_ME=true
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
```

O endereço do webhook continua sendo `/webhook/messages-upsert`. Um evento autenticado com tipo diferente de `messages.upsert` é ignorado.

## Verificações antes do uso real

No diretório do projeto, instale as dependências que o código utiliza e execute:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m py_compile evolution.py app.py llm_api.py llm_ollama.py
```

Depois faça uma validação integrada, de preferência em homologação:

- Sem segredo configurado, o webhook deve responder 503.
- Com segredo configurado mas sem cabeçalho correto, deve responder 401, sem chamar a IA.
- Com o cabeçalho correto, confirme que a Evolution API entrega `messages.upsert`.
- Verifique atendimento, identificação do cliente, carrinho, total calculado pelo código, confirmação explícita e gravação de pedido em PostgreSQL.
- Envie novamente o mesmo evento e verifique a deduplicação; repita o teste após reiniciar o processo.
- Force falha/timeout da Evolution API e confira se não aparecem mensagens completas nem segredos nos logs.
- Verifique que os novos arquivos de memória local e o `.env` não entram no Git.

**Os testes automatizados fornecem apenas cobertura inicial; não substituem o teste ponta a ponta com WhatsApp, banco e provedor de IA.**

## Dados fictícios versus dados pessoais

Os arquivos `payload_debug.txt` e `ultimo_payload.json` já estavam versionados antes da correção. **Não foi comprovado que seus conteúdos sejam dados pessoais reais.** Foram preservados para revisão e não são regravados automaticamente pelo webhook atualizado. O `.gitignore` impede novos acréscimos acidentais, mas **não exclui arquivos já rastreados nem os remove de commits antigos**.

Antes de publicar ou compartilhar dumps, confirme que nomes, telefones, mensagens, identificadores e eventuais credenciais são fictícios ou estão sanitizados. Se encontrar uma credencial real, faça a rotação; remover apenas o arquivo atual não apaga o histórico.

## Limitações e cuidados pendentes

- O segredo exige configurar a integração; **um deploy sem essa etapa interrompe o recebimento de mensagens**.
- O controle de eventos duplicados é em memória, não persistente entre reinícios/instâncias.
- A memória das conversas usa arquivos por telefone; defina retenção, controle de acesso, backup e exclusão apropriada para uso real.
- Acrescente limitação de taxa, filas/retries, observabilidade sem dados pessoais e controles de rede.
- Um segredo compartilhado só protege a origem do webhook se o canal e o gateway forem confiáveis.
- O mecanismo de proteção exige revisão periódica de dependências e testes com a versão efetivamente implantada.

## Reversão e histórico

A mudança foi incorporada pelo [PR #1](https://github.com/Bianchi613/E-pizzaria/pull/1). Em caso de falha, prefira corrigir a configuração e validar novamente; qualquer reversão deve preservar os registros de pedidos e ser feita com controle de versão. Não publique valores de `.env` em issues ou logs.