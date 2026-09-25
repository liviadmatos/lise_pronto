# Validação da entrega — 25/09/2026

## Banco real consultado, sem modificações

Projeto Supabase: **Lise**, referência `xlqtonspstoqidssioxn`, PostgreSQL 17.

- Foram comparadas as 12 tabelas atuais, colunas, tamanhos, restrições únicas e trigger de cadastro com os modelos do backend.
- Contagens por SQL: 264 termos, 8 áreas, 4 usuários e 4 contas Auth.
- Nenhum termo sem radicais; nenhum usuário Auth sem perfil; nenhum termo particular na consulta.
- As seis tabelas `lise_...` e as colunas `trilhas.descricao`/`trilhas.area` ainda precisam da migração incluída.
- As 12 tabelas estavam sem RLS. O Advisor também apontou search_path mutável em duas funções antigas, execução pública da função de cadastro e proteção contra senhas vazadas desativada.
- A migração ativa RLS, revoga os acessos públicos às tabelas e às duas funções antigas e substitui a trigger de cadastro por uma função privada com search_path fixo. As funções antigas permanecem no banco para evitar excluir objetos existentes. O aviso de search_path dessas funções legadas pode permanecer; esta aplicação não as utiliza.

Não foram acessadas senhas dos usuários, alteradas contas reais, aplicadas migrações ou modificadas configurações de e-mail no projeto hospedado.

## Backend

A suíte `python -m pytest -q` passou com **15 testes**. Executada com Python 3.12 e as dependências fixadas nos arquivos entregues.

Cobertura: páginas, login/logout, CSRF, cadastro e recuperação simulados, permissões de professor/aluno, isolamento de turmas e termos particulares, criação/vínculo de trilhas, matrícula sem duplicação, respostas dos jogos, pontuação idempotente, progresso, conquistas, flashcards, revisão repetida, expiração de partidas/sessões, limite de autenticação e tratamento de conteúdo potencialmente malicioso.

Os testes de aplicação usam SQLite temporário e Supabase Auth simulado. Isso valida as regras locais, mas não comprova entrega de e-mails ou configuração real do Render.

## Navegador

Verificação com Chromium e contas fictícias no modo local:

- Login de professor e aluno; saída pelo menu lateral.
- Abertura dos modais e criação de turma e trilha por cliques/formulários reais.
- Explorador: busca e abertura dos detalhes.
- Montagem correta, resultado e 10 XP.
- Decifrador correto, resultado e 15 XP.
- Revelação de flashcard e registro da revisão.
- Home do aluno em tela de 390 px, sem rolagem horizontal.
- Nenhum erro JavaScript capturado nesses fluxos.

Foi corrigido um erro estrutural no HTML: o modal de trilhas estava dentro do modal oculto de turmas. A data da turma também passou a aparecer no formato brasileiro. No celular, o campo do código e o botão Ingressar foram colocados em linhas separadas para evitar corte do botão.

## SQL

O SQL de migração foi executado em PostgreSQL embarcado de teste (PGlite), com a estrutura das 12 tabelas originais reconstruída localmente, dados fictícios e schema Auth mínimo.

Confirmados: preservação dos dados de teste, adição das tabelas e colunas, reexecução sem duplicação, criação de perfil pela trigger, 18 tabelas com RLS e ausência de privilégio SELECT de `anon` em usuários/EXECUTE na função privada de cadastro.

Essa simulação não equivale a aplicar a migração no projeto hospedado. O script `start.sh` executa `check-db` no Render antes de iniciar o serviço para detectar colunas ou tabelas ausentes na conexão real.

## O que ainda depende da publicação

Conexão PostgreSQL a partir do Render, aplicação do SQL no projeto, chave publishable, remetente SMTP, confirmação real de cadastro e redefinição por e-mail. Não há serviço Render publicado por esta entrega.

As funcionalidades verificadas correspondem às telas recebidas. O pacote não inclui a imagem original do mascote, que não foi fornecida. Há um ícone substituto.

Referências de segurança: [RLS desativado](https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public), [search_path](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable), [funções SECURITY DEFINER públicas](https://supabase.com/docs/guides/database/database-linter?lint=0028_anon_security_definer_function_executable), [segurança de senhas](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).
