"""Execute python run_demo.py para testar localmente sem credenciais do Supabase."""
import secrets
from pathlib import Path
from sqlalchemy.orm import Session
from app import create_app
from backend.models import Base
from backend.demo import seed

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    app = create_app({'DEMO_MODE': True, 'DATABASE_URL': 'sqlite:///' + str(root / 'demo.db'),
                      'SECRET_KEY': secrets.token_hex(32), 'SESSION_COOKIE_SECURE': False,
                      'APP_BASE_URL': 'http://127.0.0.1:5000', 'PROXY_HOPS': 0})
    Base.metadata.create_all(app.extensions['engine'])
    with Session(app.extensions['engine']) as db:
        seed(db)
        db.commit()
    print('Abra http://127.0.0.1:5000. Senha das contas demo: LiseDemo123!')
    app.run(host='127.0.0.1', port=5000, debug=False)
