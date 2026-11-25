# Auditoria de segurança — claude-code-crm

Data/base/escopo: ver THREAT_MODEL.md. Comprovado = visto no código/teste; não verificado = sem evidência suficiente. Prioridade por impacto × probabilidade × exposição. Não há alegação de cobertura integral nem conformidade ASVS.

## Achados com correção preparada
| ID | Nível | Problema | Evidência, correção e exploração plausível |
|---|---|---|---|
| CRM-01 | Alta | Cache de dados privados | `app/main.py:portaria`: antes sem Cache-Control geral; agora no-store inclusive 403, exportações e SSE. Impacto alto, probabilidade média, exposição em todo acesso autorizado; esforço baixo. |
| CRM-02 | Média | CSRF e verbos futuros | `app/acesso.py:motivo_bloqueio`: antes só POST; local sem Origin/Referer era aceito mesmo marcado cross-site. Agora cross-site é recusado e PUT/PATCH/DELETE recebem mesma proteção. Scripts locais sem cabeçalhos continuam aceitos. Esforço baixo. |
| CRM-03 | Média | Variantes de segredo/dados | `.gitignore`/`.dockerignore` antes cobriam .env e *.db; agora incluem variantes, SQLite e chaves. Não remove arquivos já rastreados; scanner complementar. |

Comum: `.github/workflows/secret-scanning.yml` adiciona Gitleaks com action por commit, histórico completo, token somente leitura e sem comentários/artefatos públicos. `.github/dependabot.yml` acompanha dependências e actions. Não há segredos novos nem mudança de produção.

## Matriz T01–T30
| Ameaça | Estado | Evidência/limite |
|---|---|---|
| T01 | Não se aplica ao fluxo atual | CRM administrativo sem assinatura premium/gateway neste repositório. |
| T02 | Não se aplica ao fluxo atual | CRM administrativo sem assinatura premium/gateway neste repositório. |
| T03 | Parcialmente verificado | Portaria valida JWT em todas as rotas privadas; sem modelo multi-tenant. Política de quem recebe JWT no Access não verificada. |
| T04 | Não se aplica ao fluxo atual | CRM administrativo sem assinatura premium/gateway neste repositório. |
| T05 | Não se aplica ao fluxo atual | CRM administrativo sem assinatura premium/gateway neste repositório. |
| T06 | Parcialmente verificado | JWT assinado com RS256, issuer, audience e exp; revogação e duração do Access não verificadas. |
| T07 | Scanner executado | Gitleaks 8.24.3: zero detecções no histórico; não prova inexistência de segredos. CI acrescentado. |
| T08 | Parcialmente corrigido | Branch principal para publicação é main; autoatualização do PC e do Render dependem da integridade dela. Proteção externa não verificada. |
| T09 | Parcialmente verificado | pip-audit sem vulnerabilidades conhecidas na resolução local; requirements usa limites abertos, sem lock completo. |
| T10 | Sem SW encontrado | Não há PWA/offline no CRM; respostas privadas agora usam no-store. |
| T11 | Sem SW encontrado | Não há PWA/offline no CRM; respostas privadas agora usam no-store. |
| T12 | Não se aplica ao fluxo atual | CRM administrativo sem assinatura premium/gateway neste repositório. |
| T13 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T14 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T15 | Exposição confirmada | Repositório público; nenhum bloqueio de DevTools foi inserido. |
| T16 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T17 | Parcialmente verificado | Jinja2 e headers defensivos existentes/adicionados; sem auditoria completa de todos os contextos de saída. |
| T18 | Lacuna corrigida | Fetch Metadata cross-site e todos os métodos inseguros; scripts locais sem Origin continuam permitidos. |
| T19 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T20 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T21 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T22 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T23 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T24 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T25 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T26 | Não verificado | Código tem backup/restauração; criptografia, permissões e restore real pendentes. |
| T27 | Não verificado | Exige ambiente/provedor ou revisão adicional; ausência de evidência não comprova segurança. |
| T28 | Não se aplica ao fluxo atual | CRM administrativo sem assinatura premium/gateway neste repositório. |
| T29 | Inventariado parcialmente | Snapshot de metadados de licenças em DEPENDENCY_LICENSES.json; revisão jurídica de obrigações e ativos pendente. |
| T30 | Não verificado | Contratos de autoria/cessão não disponibilizados. |

## Validação e risco residual
`python -m pytest -q` inclui `tests/test_security_hardening.py`; `pip-audit -r requirements.txt` sem vulnerabilidades conhecidas na resolução local. Testes novos cobrem respostas 200/403 e todos os métodos de alteração. Headers anti-frame/nosniff/base-uri não substituem revisão XSS. CSP foi limitada a diretivas compatíveis; nenhum unsafe-inline/eval adicionado.

Gitleaks 8.24.3 executado no histórico local: zero detecções. Nenhuma credencial foi testada contra provedores. Novos testes verificam o comportamento antes ausente; não foi executado ataque em produção. CI remoto deve validar a última versão da branch. Resultado: 1.271 testes passaram, 1 ignorado; duas advertências de depreciação de cookies do TestClient. Ambiente local Python 3.12; CI usa 3.13, execução no Windows não realizada.

Actions existentes de checkout/setup/upload fixadas por SHA obtido das respectivas tags oficiais; Dependabot acompanha atualizações.
