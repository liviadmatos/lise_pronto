"""LISE: Flask + Jinja + PostgreSQL/Supabase. Páginas HTML, sem API própria."""
import hashlib
import os
import random
import re
import secrets
import uuid
from datetime import timedelta
from functools import wraps
from pathlib import Path
from types import SimpleNamespace

import click
from dotenv import load_dotenv
from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFProtect, CSRFError
from sqlalchemy import create_engine, select, delete, text, event
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from supabase import create_client, ClientOptions
from supabase_auth.errors import AuthApiError

from .models import *
from .services import *

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / '.env')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_app(config=None):
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / 'frontend' / 'templates'),
                static_folder=str(PROJECT_ROOT / 'frontend' / 'static'), static_url_path='/static')
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY'),
        DATABASE_URL=os.getenv('DATABASE_URL'),
        SUPABASE_URL=os.getenv('SUPABASE_URL'),
        SUPABASE_PUBLISHABLE_KEY=os.getenv('SUPABASE_PUBLISHABLE_KEY'),
        APP_BASE_URL=os.getenv('APP_BASE_URL', 'http://127.0.0.1:5000').rstrip('/'),
        DEMO_MODE=os.getenv('DEMO_MODE', 'false').lower() == 'true',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'true').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=128 * 1024,
        WTF_CSRF_TIME_LIMIT=7200,
        PROXY_HOPS=int(os.getenv('PROXY_HOPS', '0')),
        MASCOT_FILE='img/lex_mascote.png',
    )
    if config:
        app.config.update(config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32 or app.config['SECRET_KEY'].startswith('SUBSTITUA'):
        raise RuntimeError('Defina SECRET_KEY com pelo menos 32 caracteres aleatórios. Consulte o README.')
    db_url = app.config['DATABASE_URL']
    if not db_url:
        raise RuntimeError('Defina DATABASE_URL. Consulte .env.example e README.')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    if not app.config['TESTING'] and not app.config['DEMO_MODE']:
        if not db_url.startswith('postgresql+psycopg://'):
            raise RuntimeError('Use PostgreSQL em produção; SQLite é reservado ao modo demonstração/testes.')
        if not app.config['SUPABASE_URL'] or not app.config['SUPABASE_PUBLISHABLE_KEY']:
            raise RuntimeError('Defina SUPABASE_URL e SUPABASE_PUBLISHABLE_KEY para autenticação.')
    if app.config['DEMO_MODE'] and not db_url.startswith('sqlite'):
        raise RuntimeError('DEMO_MODE só pode usar SQLite local.')
    args = dict(pool_pre_ping=True)
    if db_url.startswith('sqlite'):
        args['connect_args'] = {'check_same_thread': False}
        if ':memory:' in db_url:
            args['poolclass'] = StaticPool
    else:
        args.update(pool_size=3, max_overflow=2, pool_timeout=15,
                    connect_args={'sslmode': 'require', 'connect_timeout': 10, 'prepare_threshold': None})
    engine = create_engine(db_url, **args)
    if db_url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def sqlite_fk(connection, record):
            connection.execute('PRAGMA foreign_keys=ON')
    app.extensions['engine'] = engine
    csrf = CSRFProtect(app)
    if app.config['PROXY_HOPS']:
        hops = app.config['PROXY_HOPS']
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops)

    def auth_client():
        factory = app.config.get('AUTH_FACTORY')
        if factory:
            return factory()
        return create_client(app.config['SUPABASE_URL'], app.config['SUPABASE_PUBLISHABLE_KEY'],
                             options=ClientOptions(persist_session=False, auto_refresh_token=False))

    @app.before_request
    def load_user():
        g.user = None
        if request.endpoint == 'static':
            return
        g.db = Session(engine)
        sid = session.get('sid')
        if sid:
            row = g.db.get(Sessao, digest(sid))
            if row and aware(row.expira_em) > utcnow():
                g.user = g.db.get(Usuario, row.fk_usuario)
            else:
                session.clear()

    @app.teardown_request
    def close_db(error=None):
        db = g.pop('db', None)
        if db:
            db.close()  # Também desfaz alterações não confirmadas.

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.context_processor
    def common():
        u = getattr(g, 'user', None)
        return dict(current_user=SimpleNamespace(is_authenticated=bool(u), is_professor=bool(u and u.perfil == 'Professor')),
                    is_professor=bool(u and u.perfil == 'Professor'),
                    demo_mode=app.config['DEMO_MODE'],
                    mascot_available=(Path(app.static_folder) / app.config['MASCOT_FILE']).is_file())

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                flash('Entre na sua conta para continuar.', 'info')
                return redirect(url_for('login'))
            return fn(*a, **kw)
        return wrapper

    def professor_required(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if g.user.perfil != 'Professor':
                abort(403)
            return fn(*a, **kw)
        return wrapper

    def lock_user():
        # Serializa respostas concorrentes do mesmo aluno, inclusive em workers diferentes.
        g.db.scalar(select(Usuario).where(Usuario.id_usuario == g.user.id_usuario).with_for_update())

    def field(name, maximum=150, required=True):
        value = request.form.get(name, '').strip()
        if (required and not value) or len(value) > maximum:
            abort(400, description=f'Confira o campo {name}.')
        return value

    def integer(value):
        try:
            result = int(value)
            if result < 1: raise ValueError
            return result
        except (TypeError, ValueError):
            abort(400, description='Identificador inválido.')

    def auth_limit():
        # Limite persistente, compartilhado entre processos. Não armazena e-mail/IP em claro.
        key = digest(f'{app.config["SECRET_KEY"]}:{request.remote_addr}:{request.endpoint}')
        now = utcnow()
        with Session(engine) as db:
            # Inserção com savepoint protege a primeira requisição concorrente.
            row = db.scalar(select(LimiteAuth).where(LimiteAuth.chave == key).with_for_update())
            if not row:
                try:
                    with db.begin_nested():
                        db.add(LimiteAuth(chave=key, tentativas=0, inicio=now))
                        db.flush()
                except IntegrityError:
                    pass
                row = db.scalar(select(LimiteAuth).where(LimiteAuth.chave == key).with_for_update())
            if aware(row.inicio) < now - timedelta(minutes=15):
                row.inicio, row.tentativas = now, 0
            if row.tentativas >= 15:
                abort(429, description='Muitas tentativas. Aguarde 15 minutos e tente novamente.')
            row.tentativas += 1
            db.commit()

    def start_session(user, remember):
        old = session.get('sid')
        if old:
            g.db.execute(delete(Sessao).where(Sessao.id == digest(old)))
        session.clear()
        sid = secrets.token_urlsafe(32)
        lifetime = timedelta(days=30) if remember else timedelta(hours=12)
        g.db.add(Sessao(id=digest(sid), fk_usuario=user.id_usuario, expira_em=utcnow() + lifetime))
        g.db.commit()
        session['sid'] = sid
        session.permanent = bool(remember)

    @app.get('/')
    def index():
        return redirect(url_for('dashboard' if g.user and g.user.perfil == 'Professor' else ('home' if g.user else 'login')))

    @app.route('/login', methods=['GET', 'POST'])
    @csrf.exempt
    def login():
        if request.method == 'GET':
            return render_template('login.html', mode=request.args.get('mode', 'login'), full_width=True)
        auth_limit()
        email, password = field('email', 255).lower(), request.form.get('password', '')
        if app.config['DEMO_MODE']:
            if password != 'LiseDemo123!':
                user = None
            else:
                user = g.db.scalar(select(Usuario).where(Usuario.email == email))
        else:
            try:
                response = auth_client().auth.sign_in_with_password({'email': email, 'password': password})
                user = g.db.get(Usuario, str(response.user.id)) if response.user else None
            except AuthApiError:
                user = None
            if not user:
                flash('Não foi possível entrar. Confira suas credenciais e a confirmação do e-mail.', 'error')
                return redirect(url_for('login'), code=303)
        if not user:
            flash('E-mail ou senha inválidos.', 'error')
            return redirect(url_for('login'), code=303)
        start_session(user, request.form.get('remember_me') == 'on')
        return redirect(url_for('dashboard' if user.perfil == 'Professor' else 'home'), code=303)

    @app.route('/register', methods=['GET', 'POST'])
    @csrf.exempt
    def register():
        if request.method == 'GET':
            return render_template('login.html', mode='register', full_width=True)
        auth_limit()
        if app.config['DEMO_MODE']:
            flash('Use as contas de demonstração indicadas no README.', 'info')
            return redirect(url_for('login'), code=303)
        name, email = field('name'), field('email', 255).lower()
        password = request.form.get('password', '')
        role = {'ALUNO': 'Aluno', 'PROFESSOR': 'Professor'}.get(request.form.get('role'))
        if not role or len(password) < 8 or len(password) > 128 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            flash('Confira o e-mail, o perfil e a senha (mínimo de 8 caracteres).', 'error')
            return redirect(url_for('register'), code=303)
        try:
            auth_client().auth.sign_up({'email': email, 'password': password, 'options': {
                'data': {'nome': name, 'perfil': role},
                'email_redirect_to': app.config['APP_BASE_URL'] + '/login'}})
            # A trigger do banco cria usuarios. Não há fallback que troque o perfil.
            flash('Se o cadastro puder ser concluído, você receberá as instruções por e-mail. Se a confirmação estiver desativada, já pode entrar.', 'success')
            return redirect(url_for('login'), code=303)
        except AuthApiError:
            flash('Não foi possível concluir o cadastro. Confira os dados e tente novamente.', 'error')
            return redirect(url_for('register'), code=303)

    @app.post('/logout')
    @login_required
    def logout():
        g.db.execute(delete(Sessao).where(Sessao.id == digest(session['sid'])))
        g.db.commit()
        session.clear()
        return redirect(url_for('login'), code=303)

    @app.route('/recuperar-senha', methods=['GET', 'POST'])
    @csrf.exempt
    def recuperar_senha():
        if request.method == 'POST':
            auth_limit()
            if app.config['DEMO_MODE']:
                flash('A recuperação por e-mail está disponível na configuração com Supabase.', 'info')
            else:
                email = field('email', 255).lower()
                try:
                    auth_client().auth.reset_password_for_email(email, {'redirect_to': app.config['APP_BASE_URL'] + '/nova-senha'})
                except AuthApiError:
                    pass  # Mesma resposta para contas existentes e inexistentes.
                flash('Se houver uma conta com esse e-mail, enviaremos um link para redefinir a senha.', 'success')
            return redirect(url_for('recuperar_senha'), code=303)
        return render_template('recuperar_senha.html')

    @app.route('/nova-senha', methods=['GET', 'POST'])
    @csrf.exempt
    def nova_senha():
        if request.method == 'POST':
            auth_limit()
            password = request.form.get('password', '')
            token = field('token_hash', 512)
            if not 8 <= len(password) <= 128 or password != request.form.get('confirm_password'):
                flash('As senhas devem ser iguais e ter entre 8 e 128 caracteres.', 'error')
                return render_template('nova_senha.html', token_hash=token), 400
            if app.config['DEMO_MODE']:
                abort(400, description='Recuperação desativada na demonstração.')
            try:
                client = auth_client()
                response = client.auth.verify_otp({'token_hash': token, 'type': 'recovery'})
                if not response.user or not response.session:
                    abort(400)
                client.auth.update_user({'password': password})
                g.db.execute(delete(Sessao).where(Sessao.fk_usuario == str(response.user.id)))
                g.db.commit()
                session.clear()
                flash('Senha atualizada. Entre novamente.', 'success')
                return redirect(url_for('login'), code=303)
            except AuthApiError:
                flash('Link inválido ou expirado. Solicite outro e-mail.', 'error')
                return redirect(url_for('recuperar_senha'), code=303)
        return render_template('nova_senha.html', token_hash=request.args.get('token_hash', ''))

    @app.get('/home')
    @login_required
    def home():
        if g.user.perfil == 'Professor':
            return redirect(url_for('dashboard'))
        uid = g.user.id_usuario
        classes = g.db.scalars(select(Turma).join(Matricula).where(Matricula.fk_usuario == uid)).all()
        ids = [c.id_turma for c in classes]
        links = g.db.scalars(select(TurmaTrilha).where(TurmaTrilha.fk_turma.in_(ids))).all() if ids else []
        trails = []
        for link in links:
            trail = trail_views(g.db, [g.db.get(Trilha, link.fk_trilha)])[0]
            trail.update(vinculo_id=link.id, progresso_percentual=progress_percent(g.db, uid, link))
            trails.append(trail)
        rows = g.db.scalars(select(Partida).where(Partida.fk_usuario == uid, Partida.respondida.is_(True))).all()
        feed = []
        if links:
            recent = g.db.execute(select(Partida, Usuario).join(Usuario, Usuario.id_usuario == Partida.fk_usuario).where(Partida.fk_turma_trilha.in_([l.id for l in links]), Partida.respondida.is_(True)).order_by(Partida.respondida_em.desc()).limit(15)).all()
            for p, u in recent:
                feed.append(dict(colega_nome=u.nome.split()[0], correto=p.correto, jogo=p.jogo, hora=aware(p.respondida_em).astimezone(TZ).strftime('%d/%m %H:%M')))
        badges = [dict(icon=ACHIEVEMENTS[c.codigo][0], name=ACHIEVEMENTS[c.codigo][1], earned_at=c.criada_em.isoformat()) for c in g.db.scalars(select(Conquista).where(Conquista.fk_usuario == uid)) if c.codigo in ACHIEVEMENTS]
        return render_template('home.html', user=dict(name=g.user.nome), turmas=class_views(g.db, classes), user_trilhas=trails, feed=feed, conquistas=badges, stats=stats(rows))

    @app.get('/dashboard')
    @professor_required
    def dashboard():
        uid = g.user.id_usuario
        classes = g.db.scalars(select(Turma).where(Turma.fk_professor == uid).order_by(Turma.criado_em.desc())).all()
        trails = g.db.scalars(select(Trilha).where(Trilha.fk_professor == uid).order_by(Trilha.criado_em.desc())).all()
        terms = g.db.scalars(visible_terms(uid).order_by(Termo.palavra_completa)).all()
        return render_template('dashboard.html', turmas=class_views(g.db, classes), trilhas=trail_views(g.db, trails), termos_disponiveis=term_views(g.db, terms), areas=g.db.scalars(select(Area.nome).order_by(Area.nome)).all())

    @app.post('/turmas/criar')
    @professor_required
    def criar_turma():
        name = field('name')
        # Colisão improvável, mas tratada pela restrição UNIQUE e savepoint.
        for _ in range(5):
            try:
                with g.db.begin_nested():
                    turma = Turma(nome=name, codigo=''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6)), fk_professor=g.user.id_usuario)
                    g.db.add(turma)
                    g.db.flush()
                g.db.commit()
                flash('Turma criada. Compartilhe o código com seus alunos.', 'success')
                return redirect(url_for('ver_turma', turma_id=turma.id_turma), code=303)
            except IntegrityError:
                continue
        abort(503, description='Não foi possível gerar o código. Tente novamente.')

    @app.post('/turmas/entrar')
    @login_required
    def entrar_turma():
        if g.user.perfil != 'Aluno': abort(403)
        code = field('codigo', 6).upper()
        turma = g.db.scalar(select(Turma).where(Turma.codigo == code))
        if not turma:
            flash('Código de turma não encontrado.', 'error')
        else:
            lock_user()
            exists = g.db.scalar(select(Matricula.id).where(Matricula.fk_usuario == g.user.id_usuario, Matricula.fk_turma == turma.id_turma))
            if exists:
                flash('Você já faz parte desta turma.', 'info')
            else:
                g.db.add(Matricula(fk_usuario=g.user.id_usuario, fk_turma=turma.id_turma))
                g.db.commit()
                flash('Você entrou na turma!', 'success')
        return redirect(url_for('home'), code=303)

    def bind_trail(turma, trail):
        existing = g.db.scalar(select(TurmaTrilha).where(TurmaTrilha.fk_turma == turma.id_turma, TurmaTrilha.fk_trilha == trail.id_trilha))
        if not existing:
            g.db.add(TurmaTrilha(fk_turma=turma.id_turma, fk_trilha=trail.id_trilha))
        terms = g.db.scalars(select(Termo).join(TrilhaTermo).where(TrilhaTermo.fk_trilha == trail.id_trilha)).all()
        for term in terms:
            if term.criado_pelo_professor:
                if term.criado_por != g.user.id_usuario: abort(403)
                shared = g.db.scalar(select(TermoTurma.id).where(TermoTurma.fk_termo == term.id_termo, TermoTurma.fk_turma == turma.id_turma))
                if not shared:
                    g.db.add(TermoTurma(fk_termo=term.id_termo, fk_turma=turma.id_turma))

    @app.post('/trilhas/criar')
    @professor_required
    def criar_trilha():
        lock_user()
        name = field('name')
        area, description = field('area', 100, False), field('description', 3000, False)
        ids = list(dict.fromkeys(integer(x) for x in request.form.getlist('termos')))
        if not ids or len(ids) > 100:
            abort(400, description='Selecione entre 1 e 100 termos para a trilha.')
        for ident in ids:
            term = visible_term(g.db, g.user.id_usuario, ident)
            if not g.db.scalar(select(TermoRadical.id).where(TermoRadical.fk_termo == ident)):
                abort(400, description=f'O termo {term.palavra_completa} não possui radicais para a montagem.')
        turma = owned_class(g.db, g.user.id_usuario, integer(request.form['turma_id'])) if request.form.get('turma_id') else None
        trail = Trilha(nome=name, area=area, descricao=description, fk_professor=g.user.id_usuario)
        g.db.add(trail)
        g.db.flush()
        g.db.add_all([TrilhaTermo(fk_trilha=trail.id_trilha, fk_termo=i) for i in ids])
        g.db.flush()
        if turma: bind_trail(turma, trail)
        g.db.commit()
        flash('Trilha criada com os termos selecionados.', 'success')
        return redirect(url_for('dashboard'), code=303)

    @app.post('/turmas/<int:turma_id>/trilhas')
    @professor_required
    def vincular_trilha(turma_id):
        lock_user()
        turma = owned_class(g.db, g.user.id_usuario, turma_id)
        trail = owned_trail(g.db, g.user.id_usuario, integer(request.form.get('trilha_id')))
        bind_trail(turma, trail)
        g.db.commit()
        flash('Trilha vinculada à turma.', 'success')
        return redirect(url_for('ver_turma', turma_id=turma_id), code=303)

    @app.get('/turmas/<int:turma_id>')
    @professor_required
    def ver_turma(turma_id):
        turma = owned_class(g.db, g.user.id_usuario, turma_id)
        users = g.db.scalars(select(Usuario).join(Matricula, Matricula.fk_usuario == Usuario.id_usuario).where(Matricula.fk_turma == turma_id)).all()
        rows = g.db.scalars(select(Partida).join(TurmaTrilha).where(TurmaTrilha.fk_turma == turma_id, Partida.respondida.is_(True))).all()
        students = []
        for user in users:
            s = stats([p for p in rows if p.fk_usuario == user.id_usuario])
            s['last_activity'] = s['last_activity'].astimezone(TZ).strftime('%d/%m/%Y %H:%M') if s['last_activity'] else 'Nunca'
            s.update(name=user.nome, email=user.email)
            students.append(s)
        students.sort(key=lambda x: x['xp'], reverse=True)
        trails = g.db.scalars(select(Trilha).where(Trilha.fk_professor == g.user.id_usuario)).all()
        return render_template('ver_turma.html', turma=class_views(g.db, [turma])[0], alunos_dados=students, professor_trilhas=trail_views(g.db, trails))

    @app.route('/termos/novo', methods=['GET', 'POST'])
    @professor_required
    def novo_termo():
        if request.method == 'POST':
            name, definition = field('palavra', 200), field('definicao', 5000)
            area_id = integer(request.form.get('area_id'))
            if not g.db.get(Area, area_id): abort(400)
            classes = list(dict.fromkeys(integer(x) for x in request.form.getlist('turmas')))
            if not classes: abort(400, description='Escolha pelo menos uma turma para o termo.')
            for ident in classes: owned_class(g.db, g.user.id_usuario, ident)
            # Cada linha: texto | significado | PREFIXO/RADICAL/SUFIXO. Ordem preservada.
            pieces = []
            for line in field('radicais', 6000).splitlines():
                if not line.strip(): continue
                fields = [x.strip() for x in line.split('|')]
                if len(fields) != 3 or not fields[0] or len(fields[0]) > 100 or not fields[1] or fields[2].upper() not in ('PREFIXO', 'RADICAL', 'SUFIXO'):
                    abort(400, description='Use um radical por linha: texto | significado | classificação.')
                pieces.append(fields)
            if not 1 <= len(pieces) <= 10: abort(400, description='Informe entre 1 e 10 radicais.')
            term = Termo(palavra_completa=name, definicao_biologica=definition, fk_area=area_id, criado_por=g.user.id_usuario, criado_pelo_professor=True)
            g.db.add(term)
            g.db.flush()
            for order, (word, meaning, kind) in enumerate(pieces, 1):
                # Sem alteração de radicais compartilhados existentes.
                rad = Radical(nome=word, significado=meaning, classificacao=kind.upper(), fk_area=area_id)
                g.db.add(rad)
                g.db.flush()
                g.db.add(TermoRadical(fk_termo=term.id_termo, fk_radical=rad.id_radical, ordem=order))
            g.db.add_all([TermoTurma(fk_termo=term.id_termo, fk_turma=i) for i in classes])
            g.db.commit()
            flash('Termo adicionado para as turmas escolhidas.', 'success')
            return redirect(url_for('explorador'), code=303)
        return render_template('novo_termo.html', areas=g.db.scalars(select(Area).order_by(Area.nome)).all(), turmas=g.db.scalars(select(Turma).where(Turma.fk_professor == g.user.id_usuario)).all())

    @app.get('/explorador')
    @login_required
    def explorador():
        area, busca = request.args.get('area', ''), request.args.get('busca', '').strip()[:150]
        query = visible_terms(g.user.id_usuario)
        if area: query = query.join(Area).where(Area.nome == area)
        if busca: query = query.where(func.lower(Termo.palavra_completa).contains(busca.lower(), autoescape=True))
        terms = term_views(g.db, g.db.scalars(query.order_by(Termo.palavra_completa)).all())
        return render_template('explorador.html', terms=terms, terms_data={str(t['id']): t for t in terms}, area_selecionada=area, busca=busca, areas=g.db.scalars(select(Area.nome).order_by(Area.nome)).all())

    @app.get('/jogos')
    @login_required
    def jogos():
        return render_template('jogos.html')

    def game_page(kind):
        area = request.args.get('area', '')
        link = assignment(g.db, g.user, integer(request.args['vinculo_id'])) if request.args.get('vinculo_id') else None
        query = visible_terms(g.user.id_usuario)
        if kind == 'montagem':
            query = query.where(Termo.id_termo.in_(select(TermoRadical.fk_termo)))
        if link:
            query = query.where(Termo.id_termo.in_(select(TrilhaTermo.fk_termo).where(TrilhaTermo.fk_trilha == link.fk_trilha)))
        elif area:
            query = query.join(Area).where(Area.nome == area)
        if request.args.get('termo_id'):
            query = query.where(Termo.id_termo == integer(request.args['termo_id']))
        terms = g.db.scalars(query).all()
        if not terms:
            return render_template('vazio.html', title='Nenhum termo disponível', message='Não há termos acessíveis para este jogo e filtro. Confira o explorador ou peça uma trilha ao professor.')
        if link:
            done = set(g.db.scalars(select(Progresso.fk_termo).where(Progresso.fk_usuario == g.user.id_usuario, Progresso.fk_turma_trilha == link.id, Progresso.acertou.is_(True))))
            terms = [t for t in terms if t.id_termo not in done] or terms
        term = random.SystemRandom().choice(terms)
        view = term_views(g.db, [term])[0]
        expected = [r['id'] for r in view['radical_list']] if kind == 'montagem' else normalize(term.palavra_completa)
        game = Partida(id=str(uuid.uuid4()), fk_usuario=g.user.id_usuario, fk_termo=term.id_termo, fk_turma_trilha=link.id if link else None, jogo=kind, resposta_esperada=expected)
        g.db.add(game)
        g.db.commit()
        options = view['radical_list'][:]
        random.SystemRandom().shuffle(options)
        letters = list(term.palavra_completa.upper().replace(' ', ''))
        random.SystemRandom().shuffle(letters)
        next_url = url_for(kind, **({'vinculo_id': link.id} if link else {'area': area}))
        # Não coloca a solução nem ordem correta no JavaScript da montagem.
        return render_template(kind + '.html', term=view, radicals=view['radical_list'] if kind == 'decifrador' else [], options=options, scrambled=letters, partida=game, next_url=next_url, area_selecionada=area, vinculo_id=link.id if link else None, areas=g.db.scalars(select(Area.nome).order_by(Area.nome)).all())

    @app.get('/jogos/montagem')
    @login_required
    def montagem():
        return game_page('montagem')

    @app.get('/jogos/decifrador')
    @login_required
    def decifrador():
        return game_page('decifrador')

    @app.get('/flashcards')
    @login_required
    def flashcard():
        now, uid = utcnow(), g.user.id_usuario
        area = request.args.get('area', '')
        query = select(Flashcard).where(Flashcard.fk_usuario == uid, Flashcard.ativo.is_(True), or_(Flashcard.proxima_revisao_em <= now, Flashcard.proxima_revisao_em.is_(None)), Flashcard.fk_termo.in_(visible_terms(uid).with_only_columns(Termo.id_termo)))
        if area: query = query.join(Termo).join(Area).where(Area.nome == area)
        cards = g.db.scalars(query.order_by(Flashcard.proxima_revisao_em)).all()
        if not cards:
            next_date = g.db.scalar(select(func.min(Flashcard.proxima_revisao_em)).where(Flashcard.fk_usuario == uid, Flashcard.ativo.is_(True), Flashcard.fk_termo.in_(visible_terms(uid).with_only_columns(Termo.id_termo))))
            message = 'Acerte termos na montagem ou no decifrador para desbloquear flashcards.'
            if next_date and aware(next_date) > now:
                message = 'Revisões em dia! Próxima revisão: ' + aware(next_date).astimezone(TZ).strftime('%d/%m/%Y às %H:%M') + '.'
            elif area: message = 'Nenhuma revisão disponível nessa área. Tente remover o filtro.'
            return render_template('vazio.html', title='Flashcards', message=message)
        card = cards[0]
        term = visible_term(g.db, uid, card.fk_termo)
        game = Partida(id=str(uuid.uuid4()), fk_usuario=uid, fk_termo=term.id_termo, jogo='flashcard', resposta_esperada={'card_id': card.id_flashcard})
        g.db.add(game)
        g.db.commit()
        return render_template('flashcard.html', term=term_views(g.db, [term])[0], partida=game, restantes=len(cards), area_selecionada=area, areas=g.db.scalars(select(Area.nome).order_by(Area.nome)).all())

    @app.post('/partidas/<uuid:partida_id>/responder')
    @login_required
    def responder(partida_id):
        lock_user()
        game = g.db.scalar(select(Partida).where(Partida.id == str(partida_id), Partida.fk_usuario == g.user.id_usuario).with_for_update())
        if not game: abort(404)
        if game.respondida:
            return redirect(url_for('resultado', partida_id=game.id), code=303)
        if aware(game.criada_em) < utcnow() - timedelta(hours=2):
            abort(400, description='Este desafio expirou. Abra uma nova partida.')
        visible_term(g.db, g.user.id_usuario, game.fk_termo)
        if game.fk_turma_trilha:
            link = assignment(g.db, g.user, game.fk_turma_trilha)
            if not g.db.scalar(select(TrilhaTermo.id).where(TrilhaTermo.fk_trilha == link.fk_trilha, TrilhaTermo.fk_termo == game.fk_termo)):
                abort(400, description='A trilha foi alterada. Abra outra partida.')
        if game.jogo == 'montagem':
            raw = field('ordem', 2000)
            answer = [integer(x) for x in raw.split(',')]
            correct = answer == game.resposta_esperada
        elif game.jogo == 'decifrador':
            correct = normalize(field('resposta', 200)) == game.resposta_esperada
        else:
            value = request.form.get('acertou')
            if value not in ('sim', 'nao'): abort(400)
            card = g.db.scalar(select(Flashcard).where(Flashcard.id_flashcard == game.resposta_esperada['card_id'], Flashcard.fk_usuario == g.user.id_usuario, Flashcard.ativo.is_(True)).with_for_update())
            if not card: abort(404)
            if card.proxima_revisao_em and aware(card.proxima_revisao_em) > utcnow():
                abort(409, description='Este cartão já foi revisado. Abra a próxima revisão.')
            correct = value == 'sim'
            card.dificuldade = 'fácil' if correct else 'difícil'
            card.proxima_revisao_em = utcnow() + (timedelta(days=3) if correct else timedelta(hours=1))
        save_result(g.db, g.user, game, correct)
        g.db.commit()
        return redirect(url_for('resultado', partida_id=game.id), code=303)

    @app.get('/partidas/<uuid:partida_id>/resultado')
    @login_required
    def resultado(partida_id):
        game = g.db.scalar(select(Partida).where(Partida.id == str(partida_id), Partida.fk_usuario == g.user.id_usuario, Partida.respondida.is_(True)))
        if not game: abort(404)
        term = visible_term(g.db, g.user.id_usuario, game.fk_termo)
        args = {}
        if game.fk_turma_trilha:
            assignment(g.db, g.user, game.fk_turma_trilha)
            args['vinculo_id'] = game.fk_turma_trilha
        view = term_views(g.db, [term])[0]
        return render_template('resultado.html', partida=game, term=view, next_url=url_for(game.jogo if game.jogo != 'flashcard' else 'flashcard', **args))

    @app.get('/healthz')
    def healthz():
        g.db.execute(text('SELECT 1'))
        return 'LISE online', 200, {'Content-Type': 'text/plain; charset=utf-8'}

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template('erro.html', code=400, message='O formulário expirou. Volte, atualize a página e tente novamente.'), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {403: 'Você não tem permissão para acessar esta página.', 404: 'Página ou conteúdo não encontrado.', 413: 'O formulário enviado é muito grande.'}
        return render_template('erro.html', code=error.code, message=messages.get(error.code, error.description)), error.code

    @app.errorhandler(Exception)
    def server_error(error):
        if app.testing:
            raise error
        if hasattr(g, 'db'): g.db.rollback()
        # Não registra payloads, credenciais nem parâmetros SQL.
        app.logger.error('Falha em %s: %s', request.endpoint, type(error).__name__)
        return render_template('erro.html', code=503, message='Não foi possível concluir a operação. Tente novamente em instantes.'), 503

    @app.cli.command('demo-init')
    def demo_init():
        """Cria banco LOCAL de demonstração; nunca executa em PostgreSQL."""
        if not app.config['DEMO_MODE']:
            raise click.ClickException('Defina DEMO_MODE=true e DATABASE_URL=sqlite:///demo.db.')
        from .demo import seed
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            seed(db)
            db.commit()
        click.echo('Demonstração pronta. Contas e senha no README.')

    @app.cli.command('check-db')
    def check_db():
        """Verifica conexão e colunas, sem alterar dados."""
        with Session(engine) as db:
            for table in Base.metadata.sorted_tables:
                db.execute(select(table).limit(0))
        click.echo('Conexão e todas as tabelas/colunas verificadas.')

    @app.cli.command('cleanup')
    def cleanup():
        """Remove sessões vencidas, desafios abandonados e limites antigos."""
        with Session(engine) as db:
            db.execute(delete(Sessao).where(Sessao.expira_em < utcnow()))
            db.execute(delete(Partida).where(Partida.respondida.is_(False), Partida.criada_em < utcnow() - timedelta(days=1)))
            db.execute(delete(LimiteAuth).where(LimiteAuth.inicio < utcnow() - timedelta(days=1)))
            db.commit()
        click.echo('Limpeza concluída; histórico de partidas respondidas preservado.')

    return app
