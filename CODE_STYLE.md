# Estilo

- Python/FastAPI, templates Jinja e CSS/JavaScript existentes. Dependências em [requirements.txt](requirements.txt).
- Siga nomes, indentação e organização do módulo vizinho; mudanças pequenas, sem reformatação geral ou abstração desnecessária.
- Interface em pt-BR, sem emojis, paleta azul e fontes locais Montserrat/Inter. Preserve foco, uso no celular, movimento reduzido e funcionamento local.
- Valide dados nas fronteiras; mantenha regras financeiras fora da apresentação e não duplique cálculos.
- Testes em `tests/`; comando `python -m pytest tests`. Use banco isolado e dados sintéticos, nunca banco real. Mudanças de autorização exigem cenários negados; dados exigem preservação e backup.
- Documente contratos e decisões na fonte principal, sem diário no contexto inicial.
