"""Fluxos reais Flask/SQLAlchemy; Supabase Auth substituído apenas nos testes."""
import re
import uuid
from datetime import timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from app import create_app
from backend.application import digest
from backend.models import *
from backend.demo import seed, PROFESSOR_ID, ALUNO_ID


@pytest.fixture
def app():
    app = create_app({'TESTING': True, 'DEMO_MODE': True, 'DATABASE_URL': 'sqlite:///:memory:', 'SECRET_KEY': 'test-secret-with-more-than-thirty-two-characters', 'SESSION_COOKIE_SECURE': False})
    Base.metadata.create_all(app.extensions['engine'])
    with Session(app.extensions['engine']) as db:
        seed(db); db.commit()
    return app


from sqlalchemy.orm import Session


def csrf(response):
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert match, response.get_data(as_text=True)[:500]
    return match.group(1)


def login(client, role='aluno'):
    token = csrf(client.get('/login'))
    result = client.post('/login', data={'csrf_token':token, 'email': f'{role}@lise.demo', 'password':'LiseDemo123!'})
    assert result.status_code == 303
    return result


def game(client, kind='montagem', **params):
    from urllib.parse import urlencode
    response = client.get('/jogos/' + kind + '?' + urlencode(params))
    assert response.status_code == 200, response.get_data(as_text=True)
    text = response.get_data(as_text=True)
    ident = re.search(r'/partidas/([0-9a-f-]+)/responder', text).group(1)
    return ident, csrf(response), text


def answer(app, client, ident, token, correct=True):
    with Session(app.extensions['engine']) as db:
        row = db.get(Partida, ident)
        value = ','.join(map(str,row.resposta_esperada)) if row.jogo == 'montagem' else row.resposta_esperada
        key = 'ordem' if row.jogo == 'montagem' else 'resposta'
    return client.post(f'/partidas/{ident}/responder', data={'csrf_token':token,key:value if correct else '99999','xp_earned':'999999','correct':'true'})


def test_local_http_does_not_force_secure_session_cookie():
    local_app = create_app({'TESTING': True, 'DEMO_MODE': True, 'DATABASE_URL': 'sqlite:///:memory:', 'SECRET_KEY': 'test-secret-with-more-than-thirty-two-characters', 'SESSION_COOKIE_SECURE': True, 'APP_BASE_URL': 'http://127.0.0.1:5000'})
    assert local_app.config['SESSION_COOKIE_SECURE'] is False
    https_app = create_app({'TESTING': True, 'DEMO_MODE': True, 'DATABASE_URL': 'sqlite:///:memory:', 'SECRET_KEY': 'test-secret-with-more-than-thirty-two-characters', 'SESSION_COOKIE_SECURE': True, 'APP_BASE_URL': 'https://lise.onrender.com'})
    assert https_app.config['SESSION_COOKIE_SECURE'] is True


def test_pages_and_auth(app):
    c=app.test_client()
    assert c.get('/home').status_code == 302
    assert c.post('/login',data={'email':'x','password':'x'}).status_code == 400
    assert login(c).location.endswith('/home')
    for path in ['/home','/explorador','/jogos','/jogos/montagem','/jogos/decifrador','/flashcards']:
        result=c.get(path)
        assert result.status_code == 200, (path,result.get_data(as_text=True))
        assert '{%' not in result.get_data(as_text=True)
    assert c.get('/dashboard').status_code == 403
    assert c.get('/turmas/1').status_code == 403
    assert c.get('/logout').status_code == 405
    token=csrf(c.get('/home'))
    assert c.post('/logout',data={'csrf_token':token}).status_code == 303
    assert c.get('/home').status_code == 302
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(func.count()).select_from(Sessao)) == 0


def test_professor_classes_trails_and_empty_student(app):
    p=app.test_client(); login(p,'professor')
    for path in ['/dashboard','/turmas/1','/termos/novo']:
        assert p.get(path).status_code == 200
    token=csrf(p.get('/dashboard'))
    result=p.post('/turmas/criar',data={'csrf_token':token,'name':'Nova turma'})
    assert result.status_code == 303
    result=p.post('/trilhas/criar',data={'csrf_token':token,'name':'Nova trilha','area':'Citologia','description':'Revisão','termos':['1','2'],'turma_id':'2'})
    assert result.status_code == 303
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(Trilha).where(Trilha.nome=='Nova trilha')).descricao == 'Revisão'
        assert db.scalar(select(TurmaTrilha).where(TurmaTrilha.fk_turma==2))
        db.query(Matricula).filter_by(fk_usuario=ALUNO_ID).delete(); db.commit()
    a=app.test_client();login(a)
    assert a.get('/home').status_code == 200
    token=csrf(a.get('/home'))
    for _ in range(2):
        assert a.post('/turmas/entrar',data={'csrf_token':token,'codigo':'lise26'}).status_code == 303
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(func.count()).select_from(Matricula).where(Matricula.fk_usuario==ALUNO_ID)) == 1


def test_private_terms_and_ownership(app):
    p=app.test_client();login(p,'professor'); token=csrf(p.get('/termos/novo'))
    assert p.post('/termos/novo',data={'csrf_token':token,'palavra':'Termo Privado','definicao':'Definição exclusiva','area_id':1,'turmas':['1'],'radicais':'termo | parte | RADICAL\nprivado | exclusivo | SUFIXO'}).status_code == 303
    other_id=str(uuid.uuid4()); teacher_id=str(uuid.uuid4())
    with Session(app.extensions['engine']) as db:
        db.add_all([Usuario(id_usuario=other_id,nome='Outro Aluno',email='outro@lise.demo',perfil='Aluno'), Usuario(id_usuario=teacher_id,nome='Outro Professor',email='outrop@lise.demo',perfil='Professor')]);db.flush()
        turma=Turma(nome='Outra',codigo='OTHER1',fk_professor=teacher_id);db.add(turma);db.commit()
        term=db.scalar(select(Termo).where(Termo.palavra_completa=='Termo Privado')); tid=term.id_termo
        turma_id=turma.id_turma
    a=app.test_client();login(a)
    assert 'Termo Privado' in a.get('/explorador').get_data(as_text=True)
    o=app.test_client();token=csrf(o.get('/login'))
    o.post('/login',data={'csrf_token':token,'email':'outro@lise.demo','password':'LiseDemo123!'})
    assert 'Termo Privado' not in o.get('/explorador').get_data(as_text=True)
    assert 'Nenhum termo disponível' in o.get(f'/jogos/montagem?termo_id={tid}').get_data(as_text=True)
    assert o.get('/jogos/montagem?vinculo_id=1').status_code == 404
    assert p.get(f'/turmas/{turma_id}').status_code == 404
    token=csrf(p.get('/dashboard'))
    assert p.post(f'/turmas/{turma_id}/trilhas',data={'csrf_token':token,'trilha_id':1}).status_code == 404


def test_game_server_validation_idempotency_and_progress(app):
    c=app.test_client();login(c)
    ident,token,html=game(c,vinculo_id=1,termo_id=1)
    assert 'correctIds' not in html and 'apiFetch' not in html
    assert answer(app,c,ident,token).status_code == 303
    assert answer(app,c,ident,token).status_code == 303
    with Session(app.extensions['engine']) as db:
        assert db.get(Partida,ident).xp == 10
        assert db.scalar(select(func.count()).select_from(Flashcard)) == 1
        assert db.scalar(select(func.count()).select_from(Progresso)) == 1
        assert db.scalar(select(Matricula)).pontuacao == 10
        assert db.scalar(select(Conquista).where(Conquista.codigo=='primeiro_acerto'))
    # Mesmo termo, novo desafio: prática permitida, sem novo XP no mesmo dia/jogo.
    second,token,_=game(c,vinculo_id=1,termo_id=1)
    answer(app,c,second,token)
    with Session(app.extensions['engine']) as db:
        assert db.get(Partida,second).xp == 0
        assert db.scalar(select(Matricula)).pontuacao == 10
    ident,token,_=game(c,termo_id=2)
    answer(app,c,ident,token,False)
    with Session(app.extensions['engine']) as db:
        assert db.get(Partida,ident).correto is False
        assert db.get(Partida,ident).xp == 0
    assert '20%' in c.get('/home').get_data(as_text=True)
    assert 'Biologia' in c.get(f'/partidas/{second}/resultado').get_data(as_text=True)


def test_decipher_normalization_and_flashcard_schedule(app):
    c=app.test_client();login(c)
    ident,token,_=game(c,'decifrador',termo_id=4)
    response=c.post(f'/partidas/{ident}/responder',data={'csrf_token':token,'resposta':'  FOTOSSINTESE  '})
    assert response.status_code == 303
    page=c.get('/flashcards');html=page.get_data(as_text=True)
    review=re.search(r'/partidas/([0-9a-f-]+)/responder',html).group(1)
    # Outra aba aberta antes de revisar: não pode antecipar segunda revisão.
    page2=c.get('/flashcards'); other=re.search(r'/partidas/([0-9a-f-]+)/responder',page2.get_data(as_text=True)).group(1)
    token=csrf(page)
    assert c.post(f'/partidas/{review}/responder',data={'csrf_token':token,'acertou':'nao'}).status_code == 303
    assert c.post(f'/partidas/{other}/responder',data={'csrf_token':token,'acertou':'sim'}).status_code == 409
    with Session(app.extensions['engine']) as db:
        card=db.scalar(select(Flashcard))
        assert card.dificuldade == 'difícil'
        from backend.services import aware
        assert utcnow()+timedelta(minutes=58) < aware(card.proxima_revisao_em) < utcnow()+timedelta(minutes=61)
        assert db.get(Partida,ident).xp == 15
    assert 'Revisões em dia' in c.get('/flashcards').get_data(as_text=True)


def test_expiration_csrf_result_access_and_xss(app):
    c=app.test_client();login(c)
    ident,token,_=game(c,termo_id=1)
    with Session(app.extensions['engine']) as db:
        db.get(Partida,ident).criada_em=utcnow()-timedelta(hours=3)
        db.get(Termo,1).palavra_completa='<script>alert(1)</script>'
        db.commit()
    assert answer(app,c,ident,token).status_code == 400
    assert c.post(f'/partidas/{ident}/responder',data={'ordem':'1,2'}).status_code == 400
    assert c.get(f'/partidas/{ident}/resultado').status_code == 404
    html=c.get('/explorador').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;' in html
    p=app.test_client();login(p,'professor')
    assert p.post(f'/partidas/{ident}/responder',data={'csrf_token':csrf(p.get('/dashboard')),'ordem':'1,2'}).status_code == 404


def test_trail_completed_and_achievements(app):
    c=app.test_client();login(c)
    for term in range(1,6):
        ident,token,_=game(c,vinculo_id=1,termo_id=term)
        assert answer(app,c,ident,token).status_code == 303
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(Conquista).where(Conquista.codigo=='primeira_trilha'))
    assert '100%' in c.get('/home').get_data(as_text=True)


def test_supabase_login_contract_and_session_revocation(app):
    class FakeAuth:
        def sign_in_with_password(self,data):
            assert data=={'email':'real@example.com','password':'password123'}
            return SimpleNamespace(user=SimpleNamespace(id=ALUNO_ID))
    app.config.update(DEMO_MODE=False, AUTH_FACTORY=lambda:SimpleNamespace(auth=FakeAuth()))
    c=app.test_client();token=csrf(c.get('/login'))
    assert c.post('/login',data={'csrf_token':token,'email':'real@example.com','password':'password123'}).status_code == 303
    with c.session_transaction() as s: sid=s['sid']
    with Session(app.extensions['engine']) as db:
        row=db.get(Sessao,digest(sid)); row.expira_em=utcnow()-timedelta(seconds=1);db.commit()
    assert c.get('/home').status_code == 302


def test_no_json_api_routes(app):
    assert not any(rule.rule.startswith('/api') for rule in app.url_map.iter_rules())


def test_invalid_ids_no_partial_trail(app):
    c=app.test_client();login(c,'professor');token=csrf(c.get('/dashboard'))
    assert c.post('/trilhas/criar',data={'csrf_token':token,'name':'Inválida','termos':['999999']}).status_code == 404
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(func.count()).select_from(Trilha)) == 1


def test_supabase_registration_recovery_and_password_reset(app):
    calls=[]
    class FakeAuth:
        def sign_up(self, data):
            calls.append(('signup', data))
            return SimpleNamespace(user=SimpleNamespace(id=ALUNO_ID))
        def reset_password_for_email(self, email, options): calls.append(('recovery',email,options))
        def verify_otp(self, data):
            calls.append(('verify',data))
            return SimpleNamespace(user=SimpleNamespace(id=ALUNO_ID),session=object())
        def update_user(self, data): calls.append(('update',data))
    app.config.update(DEMO_MODE=False,AUTH_FACTORY=lambda:SimpleNamespace(auth=FakeAuth()))
    c=app.test_client()
    token=csrf(c.get('/register'))
    r=c.post('/register',data={'csrf_token':token,'name':'Nova Pessoa','email':'nova@example.com','password':'newpassword123','role':'PROFESSOR'})
    assert r.status_code==303
    assert calls[0][1]['options']['data']=={'nome':'Nova Pessoa','perfil':'Professor'}
    r=c.post('/recuperar-senha',data={'csrf_token':token,'email':'nova@example.com'})
    assert r.status_code==303
    # Visitar o link não consome o token; somente o POST confirma a troca.
    page=c.get('/nova-senha?token_hash=abc123')
    assert page.status_code==200
    assert not any(x[0]=='verify' for x in calls)
    with Session(app.extensions['engine']) as db:
        db.add(Sessao(id='0'*64,fk_usuario=ALUNO_ID,expira_em=utcnow()+timedelta(hours=1)));db.commit()
    r=c.post('/nova-senha',data={'csrf_token':csrf(page),'token_hash':'abc123','password':'newpassword123','confirm_password':'newpassword123'})
    assert r.status_code==303
    assert ('verify',{'token_hash':'abc123','type':'recovery'}) in calls
    with Session(app.extensions['engine']) as db:
        assert db.scalar(select(func.count()).select_from(Sessao))==0


def test_revoked_private_access_invalidates_pending_game(app):
    p=app.test_client();login(p,'professor')
    token=csrf(p.get('/termos/novo'))
    p.post('/termos/novo',data={'csrf_token':token,'palavra':'Exclusivo','definicao':'Conteúdo de turma','area_id':1,'turmas':['1'],'radicais':'ex | parte | PREFIXO\nclusivo | parte | RADICAL'})
    with Session(app.extensions['engine']) as db: tid=db.scalar(select(Termo.id_termo).where(Termo.palavra_completa=='Exclusivo'))
    c=app.test_client();login(c)
    ident,token,_=game(c,termo_id=tid)
    with Session(app.extensions['engine']) as db:
        db.query(Matricula).filter_by(fk_usuario=ALUNO_ID).delete();db.commit()
    assert answer(app,c,ident,token).status_code==404


def test_new_terms_and_database_values_cannot_inject_html(app):
    p=app.test_client();login(p,'professor')
    token=csrf(p.get('/dashboard'))
    result=p.post('/turmas/criar',data={'csrf_token':token,'name':'<img src=x onerror=alert(1)>'})
    assert result.status_code==303
    html=p.get(result.location).get_data(as_text=True)
    assert '<img src=x onerror=alert(1)>' not in html
    assert '&lt;img' in html


def test_repeated_radicals_are_distinct_pieces(app):
    with Session(app.extensions['engine']) as db:
        first=db.scalar(select(TermoRadical).where(TermoRadical.fk_termo==1).order_by(TermoRadical.ordem))
        db.add(TermoRadical(fk_termo=1,fk_radical=first.fk_radical,ordem=3));db.commit()
    c=app.test_client();login(c)
    ident,token,html=game(c,termo_id=1)
    with Session(app.extensions['engine']) as db:
        expected=db.get(Partida,ident).resposta_esperada
        assert len(expected)==3 and len(set(expected))==3
    assert answer(app,c,ident,token).status_code==303


def test_login_rate_limit(app):
    c=app.test_client(); token=csrf(c.get('/login'))
    for _ in range(15):
        assert c.post('/login',data={'csrf_token':token,'email':'no@example.com','password':'wrong'}).status_code==303
    assert c.post('/login',data={'csrf_token':token,'email':'no@example.com','password':'wrong'}).status_code==429
