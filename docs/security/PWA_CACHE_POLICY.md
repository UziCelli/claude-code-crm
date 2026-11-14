# Política de cache

O CRM não registra Service Worker nem oferece modo offline. Cache API/IndexedDB e concessão premium não se aplicam ao produto atual.

| Conteúdo | Estratégia |
|---|---|
| HTML, finanças, cadastros, conversas e exportações | Network Only, Cache-Control: no-store |
| Respostas 403, redirects, saúde e estáticos autenticados | no-store por padrão conservador |
| SSE do assistente | no-store; não guardar conteúdo das conversas no proxy |
| Banco e backups | Arquivos privados do servidor/PC; nunca assets públicos |

O middleware aplica no-store a todas as respostas normais, inclusive erros tratados. Exceções não tratadas podem passar pelo manipulador 500 do framework; não devem carregar dados privados. CDN deve respeitar no-store e nunca habilitar Cache Everything para o CRM. Validar no painel do provedor.

no-store não apaga cópias já recebidas nem páginas de histórico de todos os navegadores. Fechar abas ao sair; configurar logout/revogação no Access. Não há estratégia de atualização de SW porque não existe worker neste repositório.
