# Tio Bigode Django

Sistema online de agendamento e gerenciamento de barbearia em Django.

## Arquitetura encontrada e decisao

O projeto original `tio bigode` era um app Next.js com interface publica e painel visual, mas usava arrays em `lib/data.ts`, sem banco de dados, ORM, autenticacao real ou APIs persistentes. Esta entrega cria uma versao Django completa no diretorio solicitado, preservando a identidade e o fluxo do Tio Bigode com backend server-rendered, APIs JSON e painel administrativo seguro.

## Tabelas principais

- `Service`: catalogo de servicos, preco atual, duracao e status ativo/inativo.
- `Barber`: barbeiros, opcionalmente vinculados a usuarios Django.
- `Appointment`: agendamentos com cliente, barbeiro, servico, snapshot de nome/preco/duracao, status, pagamento e exclusao logica.
- `Payment`: pagamentos vinculados ao agendamento, com valor validado no backend.
- `ServicePriceHistory`: historico de alteracoes de preco.
- `AuditLog`: trilha de auditoria para acoes administrativas e financeiras.

## Rotas

- `GET /`: site publico e formulario de agendamento.
- `POST /agendar/`: cria agendamento publico.
- `GET /api/services/`: lista servicos ativos.
- `GET /api/availability/?date=YYYY-MM-DD&barber=ID&service=ID`: horarios disponiveis.
- `POST /api/appointments/`: cria agendamento via JSON.
- `GET|POST /admin/login/`: login administrativo.
- `GET /admin/`: painel com lista/calendario, filtros, servicos e financeiro.
- `GET|POST /admin/agendamentos/<id>/editar/`: edita agendamento.
- `POST /admin/agendamentos/<id>/<acao>/`: confirmar, iniciar, concluir, cancelar, ausencia ou arquivar.
- `POST /admin/agendamentos/<id>/pagamento/`: registra pagamento.
- `GET|POST /admin/servicos/novo/`: cria servico.
- `GET|POST /admin/servicos/<id>/editar/`: edita servico e historico de preco.
- `GET /admin/financeiro/exportar.csv`: exporta movimentacoes em CSV.

## Variaveis de ambiente

Copie `.env.example` conforme o ambiente e configure:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_DB_ENGINE`, `DJANGO_DB_NAME`, `DJANGO_DB_USER`, `DJANGO_DB_PASSWORD`, `DJANGO_DB_HOST`, `DJANGO_DB_PORT` quando usar PostgreSQL ou outro banco.
- `TIO_BIGODE_SEED_PASSWORD` somente para definir senha inicial dos usuarios de desenvolvimento criados pelo seed.

## Como rodar

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
$env:TIO_BIGODE_SEED_PASSWORD="defina-uma-senha-forte"
python manage.py seed_initial_data
python manage.py runserver
```

Usuarios de desenvolvimento criados pelo seed: `admin`, `gerente`, `recepcao`, `tiobigode`. Se `TIO_BIGODE_SEED_PASSWORD` nao estiver definido, usuarios novos sao criados sem senha utilizavel.

## Validacoes e seguranca

- Hash de senha via Argon2 com fallback Django.
- CSRF ativo em formularios.
- Cookies `HttpOnly`, `SameSite` e `Secure` em producao.
- ORM Django e validacao server-side para prevenir SQL Injection e conflito de agenda.
- Rate limiting simples de login via cache.
- Autorizacao por grupos: Administrador, Gerente, Barbeiro e Recepcionista.
- Exclusao logica de agendamentos para auditoria.
- Transacao atomica para concluir atendimento e registrar pagamento.
- Financeiro considera somente pagamentos pagos de atendimentos concluidos.

## Testes

```powershell
python manage.py test
```

Os testes cobrem conflito de horarios, preservacao de preco antigo, permissao de recepcionista, rejeicao de conflito via API e calculo financeiro.
