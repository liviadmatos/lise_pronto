# Funções e organização da LISE

Esta versão atende às telas recebidas na conversa. Não tem API REST própria: usa páginas Flask/Jinja e formulários. O Supabase continua responsável pela autenticação e pelo PostgreSQL.

| Tela/fluxo | Implementação |
| --- | --- |
| Cadastro | Aluno/Professor, validação e confirmação pelo Supabase Auth |
| Login e saída | Sessões no banco, lembrar acesso, logout por formulário |
| Recuperação | E-mail, link com TokenHash, nova senha e revogação das sessões da conta |
| Professor | Painel, criação de turmas, código de ingresso, alunos e atividades |
| Trilhas | Seleção de termos, descrição, área, vínculo às turmas do próprio professor |
| Aluno | Ingresso por código, trilhas atribuídas, progresso, XP, nível e conquistas |
| Explorador | Busca textual, filtro por área, definição, radicais e botão de prática |
| Termos particulares | Cadastro com radicais e compartilhamento nas turmas escolhidas |
| Montagem | Seleção por clique ou arrastar, ordem validada no servidor |
| Decifrador | Letras embaralhadas, dica e validação ignorando acentos/maiúsculas |
| Flashcards | Desbloqueio por acertos e revisão por autoavaliação |
| Segurança | CSRF, autorização por proprietário/matrícula, limite de login e prevenção de pontos duplicados |

O HTML original foi adaptado aos nomes e rotas do backend. Não substitua os templates deste pacote pelos antigos sem adaptar os formulários. O `config.js` da API antiga não é necessário.

## Regras adotadas

- Montagem: 10 XP por termo/dia. Decifrador: 15 XP por termo/dia.
- Flashcard: “Lembrei” concede até 5 XP por termo/dia e agenda revisão em três dias. “Preciso revisar” agenda para uma hora e não dá XP.
- Reenviar a mesma partida não duplica pontos, progresso ou flashcards.
- O aluno conclui um termo da trilha acertando montagem ou decifrador dentro daquela trilha.
- Jogar fora de uma trilha conta para o histórico pessoal, sem atribuir atividade a uma turma arbitrária.
- O nível sobe a cada 100 XP. Sequência de dias usa o fuso America/Sao_Paulo.
- Conquistas: primeiro acerto, dez acertos, 100 XP, três dias seguidos e primeira trilha concluída.
- Professor só gerencia suas próprias turmas e trilhas. O autocadastro de Professor não verifica profissão; esse é o comportamento das telas originais.
- As métricas do novo painel vêm das partidas desta versão. Pontuações antigas no banco são preservadas, mas não inventamos um histórico de jogadas a partir desses totais.

## Arquivos do backend

`backend/application.py` configura Flask e as rotas. `backend/models.py` mapeia as tabelas. `backend/services.py` concentra acesso, pontuação, conquistas e progresso. `backend/demo.py` contém dados fictícios usados somente na demonstração local.

`frontend/templates/` contém as telas e `frontend/static/` contém CSS/ícones. O CSS já está pronto. O Render não precisa executar Node ou Tailwind.

## Teste local opcional

Com Python 3.12, abra um terminal dentro de `lise_pronto`. No Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe run_demo.py
```

No Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python run_demo.py
```

Abra http://127.0.0.1:5000. Contas fictícias: `professor@lise.demo` e `aluno@lise.demo`. Senha de ambas: `LiseDemo123!`. Código da turma: `LISE26`. Cadastro e envio de e-mail ficam desativados na demonstração. Não publique DEMO_MODE=true.

## Verificação e manutenção

Com as bibliotecas instaladas:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Com as variáveis reais configuradas:

```bash
python -m flask --app app:create_app check-db
python -m flask --app app:create_app cleanup
```

`check-db` somente lê as tabelas/colunas. `cleanup` remove sessões vencidas, limites antigos e desafios abandonados; mantém as partidas respondidas.

Para recompilar o CSS após mudar classes das telas, entre em `frontend/` e execute `npm ci` e `npm run build:css`. Envie o CSS compilado ao GitHub.

As sessões Flask duram até 12 horas ou 30 dias com lembrar acesso. Logout remove a sessão atual. Recuperação de senha pela LISE remove todas as sessões da conta. Revogação feita somente no painel Auth do Supabase não revoga automaticamente essas sessões próprias: remova também as linhas correspondentes em `lise_sessoes` quando precisar encerrar o acesso imediatamente.

Esta entrega não inclui pagamentos, assinatura, aplicativo móvel nem jogos além de Montagem, Decifrador e Flashcards. Não havia telas/requisitos completos dessas outras funções no front-end analisado.
