# LISE — comece por aqui

Este é o pacote organizado da LISE. **Publique todo o conteúdo desta pasta como um único Web Service no Render.** O front-end e o backend estão separados em pastas, mas trabalham juntos: o Flask preenche os HTMLs e entrega as páginas prontas.

Não é necessário editar os arquivos Python ou HTML para publicar. As credenciais são preenchidas no painel do Render. O SQL e o template de e-mail são copiados para o painel do Supabase nos passos abaixo.

## 1. Entenda a pasta que você recebeu

Ao extrair `LISE_PRONTO.zip`, você encontrará **uma pasta chamada `lise_pronto`**. Abra essa pasta.

| Item dentro de `lise_pronto` | Para que serve | O que fazer |
| --- | --- | --- |
| `backend/` | Login, turmas, trilhas, jogos, pontuação e banco | Enviar inteira, sem editar |
| `frontend/` | Seus HTMLs adaptados, estilos e ícones | Enviar inteira, sem editar |
| `supabase/` | SQL de atualização e template do e-mail | Enviar inteira; usar no passo 3 e no passo 6 |
| `docs/` | Regras e relatório de validação | Enviar inteira |
| `tests/` | Testes automatizados | Enviar inteira |
| `app.py` | Entrada da aplicação | Enviar sem editar |
| `start.sh` | Confere o banco e inicia o site | Enviar sem editar |
| `requirements.txt`, `requirements.lock`, `requirements-dev.txt` | Bibliotecas necessárias | Enviar sem editar |
| `render.yaml` | Configuração de referência do Render | Enviar sem editar |
| `run_demo.py`, `pytest.ini`, `README.md` | Demonstração, testes e este guia | Enviar sem editar |

**Não publique apenas `backend/`.** O servidor precisa também de `frontend/` e dos arquivos da pasta principal. Não misture estes arquivos com o pacote anterior.

## 2. Envie ao GitHub

Para não misturar com as tentativas anteriores, use um repositório novo chamado **`lise-organizado`**. Você pode manter o repositório `lise` anterior guardado.

1. No GitHub, clique em **New repository**.
2. Nome: `lise-organizado`. Pode ser privado, desde que você dê acesso ao Render.
3. Crie o repositório e abra **uploading an existing file** (ou **Add file → Upload files**).
4. No seu computador, abra a pasta `lise_pronto`.
5. Selecione **todo o conteúdo que está dentro dela** e arraste para a tela de upload. As subpastas devem continuar sendo pastas.
6. Clique em **Commit changes** e espere terminar.

**Conferência:** na página principal do repositório, você deve ver `app.py`, `start.sh`, `requirements.lock`, `backend/` e `frontend/` sem abrir outra pasta. Seguindo isso, o campo **Root Directory** do Render ficará vazio.

Se a página principal mostrar somente a pasta `lise_pronto`, isso também pode funcionar: nesse caso o Root Directory precisa ser `lise_pronto`. Use o caminho da pasta que realmente contém `app.py` e `start.sh`. Não use `backend` nesse campo.

Não envie o ZIP como um único arquivo ao GitHub. Extraia-o primeiro. Não envie senhas ou arquivos de banco de demonstração.

## 3. Prepare o projeto Lise no Supabase

Projeto conferido: **Lise**, referência `xlqtonspstoqidssioxn`.

Na consulta de 25/09/2026, havia **264 termos, 8 áreas, 4 usuários da aplicação e 4 contas Auth**. Todos os termos tinham radicais. O pacote aproveita essas tabelas e esse conteúdo.

**Antes de executar o SQL:** guarde um backup do banco atual. Esta atualização preserva registros, mas muda as permissões: o acesso às tabelas passa a ser feito pelo backend Flask. Se a versão antiga ainda estiver em uso e depender da Data API com chave `anon`, execute a atualização no momento de trocar para este novo site. A estrutura e as permissões antigas não são restauradas automaticamente.

1. Abra [o projeto Lise](https://supabase.com/dashboard/project/xlqtonspstoqidssioxn).
2. Entre em **SQL Editor → New query**.
3. No pacote, abra `supabase/migrations/20260918171455_lise_flask_integrado.sql` em um editor de texto. No GitHub, também é possível abrir o arquivo e copiar seu conteúdo usando **Raw**.
4. Copie **todo o conteúdo do arquivo**, do começo ao fim, para a consulta.
5. Clique em **Run** e aguarde a confirmação de sucesso.

O SQL adiciona as tabelas de sessões, partidas, recompensas, conquistas, limites de login e compartilhamento de termos. Acrescenta descrição e área às trilhas, prepara o cadastro e ativa RLS. Não é necessário apagar ou recriar as 12 tabelas antigas. Não execute `demo.py` no Supabase.

As 12 tabelas atuais estavam sem RLS na inspeção. Essa situação foi confirmada pelo Security Advisor. O SQL incluído fecha o acesso direto por `anon`/`authenticated`; o novo backend aplica as permissões de aluno/professor no servidor. [Explicação oficial do alerta](https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public).

**A inspeção foi somente de leitura: esse SQL ainda não foi aplicado ao seu projeto.**

## 4. Crie o serviço no Render

No [Render](https://dashboard.render.com), clique em **New → Web Service**. Conecte seu GitHub e selecione `lise-organizado`.

Preencha:

| Campo do Render | Valor |
| --- | --- |
| Name | `lise-organizado` (ou outro nome disponível) |
| Language / Runtime | `Python 3` |
| Branch | A branch com seus arquivos, normalmente `main` |
| Root Directory | Deixe vazio se `app.py` aparece na página principal do GitHub |
| Build Command | `pip install -r requirements.lock` |
| Start Command | `bash start.sh` |
| Instance Type | `Free`, se quiser começar sem plano pago |
| Health Check Path, nas opções avançadas | `/healthz` |

Use **Web Service**, pois o Flask precisa executar no servidor. O arquivo `render.yaml` é uma alternativa para quem usa Blueprints; neste guia você está preenchendo os campos manualmente.

O plano Free pode suspender o serviço após inatividade e demorar a responder no primeiro acesso. Os dados ficam no Supabase e não dependem do disco temporário do Render.

## 5. Preencha Environment no Render

Adicione uma variável por linha. Não coloque aspas em volta dos valores.

| Key | Value |
| --- | --- |
| `PYTHON_VERSION` | `3.12.14` |
| `SECRET_KEY` | Uma chave aleatória com pelo menos 32 caracteres; veja abaixo |
| `DATABASE_URL` | A conexão **Session pooler** copiada do Supabase, com a senha do banco preenchida |
| `SUPABASE_URL` | `https://xlqtonspstoqidssioxn.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | A chave **publishable** do projeto Lise; a chave **anon** legada também é aceita |
| `APP_BASE_URL` | A URL HTTPS exata atribuída pelo Render, sem barra no final |
| `COOKIE_SECURE` | `true` em HTTPS/Render; use `false` para desenvolvimento local em `http://127.0.0.1:5000` |
| `PROXY_HOPS` | `1` |
| `DEMO_MODE` | `false` |

**Onde obter DATABASE_URL:** no projeto Lise, clique em **Connect**, escolha **Session pooler** e copie a conexão PostgreSQL. Substitua `[YOUR-PASSWORD]` pela senha do banco. Essa senha é diferente da senha de login no site do Supabase. Copie o host do painel; não tente adivinhar o endereço pela região.

Se a senha tiver caracteres reservados, eles precisam ser codificados dentro da URL: por exemplo, `@` vira `%40`, `#` vira `%23`, `/` vira `%2F` e `%` vira `%25`. Não altere o restante da conexão.

**Onde obter a chave publishable:** abra **Project Settings → API Keys** no Supabase e copie a chave publishable. Se o painel mostrar somente as chaves legadas, use **anon**. Não use `service_role` ou uma chave secret neste campo.

**Como gerar SECRET_KEY:** se houver um botão de gerar valor no Render, use-o. Também é possível gerar localmente com Python:

```text
python -c "import secrets; print(secrets.token_hex(32))"
```

Copie o resultado para o campo. Mantenha a mesma chave nos próximos deploys.

**Se a URL do Render ainda não aparecer:** use provisoriamente `https://example.invalid` em `APP_BASE_URL`. Assim que o serviço for criado e mostrar seu endereço real, substitua o valor em **Environment → Save and deploy**, antes de cadastrar usuários ou solicitar e-mails. O valor provisório não serve para os links de confirmação.

Clique em **Deploy Web Service**. O início executa `check-db`: ele confere se todas as tabelas e colunas necessárias existem. Caso falte o SQL do passo 3, o deploy para e mostra o erro nos logs.

## 6. Configure os e-mails no Supabase

Primeiro confirme que `APP_BASE_URL` no Render já contém o endereço real do site.

Em **Authentication → URL Configuration**:

- **Site URL:** o mesmo endereço de `APP_BASE_URL`, sem barra no final.
- **Redirect URLs:** adicione o endereço real seguido de `/login` e outra entrada terminando em `/nova-senha`.

Em **Authentication → Email / SMTP Settings**, configure um remetente SMTP para enviar mensagens aos alunos. Preencha os dados fornecidos pelo seu serviço de e-mail: remetente, nome do remetente, host, porta, usuário e senha SMTP. Esses dados não vêm do código ou da senha do banco.

O SMTP padrão do Supabase tem restrições e não envia livremente para todos os alunos. Em projetos Free novos a partir de 03/06/2026, a edição dos templates também requer SMTP próprio. O projeto Lise foi criado depois dessa data. Não é necessário contratar um plano pago do Supabase só para usar SMTP próprio; observe os limites do provedor de e-mail escolhido.

Em **Authentication → Email Templates → Reset Password**:

1. Abra o arquivo `supabase/email_recuperacao.html` como texto.
2. Copie seu conteúdo para o corpo do template de recuperação.
3. Salve. Mantenha `{{ .SiteURL }}` e `{{ .TokenHash }}` exatamente como estão.

O template de confirmação de cadastro pode continuar com o padrão do Supabase. Depois de confirmar o e-mail, a pessoa entra usando e-mail e senha. A recuperação precisa do template fornecido para o Flask receber o código do link.

## 7. Confira se está funcionando

1. Abra o endereço do Render: a tela de login deve aparecer.
2. Abra esse endereço seguido de `/healthz`: deve aparecer **LISE online**. Isso confirma a conexão básica com o banco; os passos seguintes conferem as funções.
3. Cadastre uma conta Professor com um e-mail seu e confirme a mensagem recebida.
4. Entre, crie uma turma, copie seu código e crie uma trilha com termos, atribuindo-a à turma.
5. Em outra janela, cadastre uma conta Aluno, confirme o e-mail e entre na turma usando o código.
6. Abra a trilha, acerte uma montagem e confira XP/progresso. Teste o decifrador e a revisão de flashcard.
7. Volte ao professor e confira a atividade do aluno dentro da turma.
8. Saia e teste **Esqueci minha senha** com uma conta sua.

Se houver erro, copie as últimas linhas da aba **Logs** do Render, ocultando senhas e chaves. Exemplos: `requirements.lock not found` indica Root Directory errado; `relation ... does not exist` indica SQL pendente; `password authentication failed` indica credenciais PostgreSQL incorretas.

## O que você precisa editar nos arquivos?

Para hospedar no Render, **nenhum arquivo do código precisa receber suas senhas**. Os exemplos podem permanecer como foram entregues. O único conteúdo copiado e salvo em outro lugar é o SQL (passo 3) e o template de e-mail (passo 6). As variáveis são preenchidas no Render (passo 5).

O pacote não inclui a imagem original do mascote porque ela não estava nos arquivos recebidos. A tela usa um ícone de planta. Se você tiver a imagem, coloque-a em `frontend/static/img/lex_mascote.png`.

Para testes locais e detalhes das funções, leia [docs/FUNCIONALIDADES.md](docs/FUNCIONALIDADES.md). O que foi verificado está em [docs/VALIDACAO.md](docs/VALIDACAO.md).

Referências oficiais: [Render Flask](https://render.com/docs/deploy-flask), [Root Directory](https://render.com/docs/monorepo-support), [variáveis](https://render.com/docs/configure-environment-variables), [plano Free](https://render.com/docs/free), [conexão Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres), [SMTP](https://supabase.com/docs/guides/auth/auth-smtp), [templates](https://supabase.com/docs/guides/auth/auth-email-templates), [mudança nos templates Free](https://supabase.com/changelog/46599-changes-to-email-template-customisation-on-free-tier).
