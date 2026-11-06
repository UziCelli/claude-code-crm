# Imagem do CRM para o Google Cloud Run (a reserva do celular). Passo a passo no README ("Reserva: Google Cloud Run").
# O Cloud Run lê este arquivo sozinho a cada mudança na main (implantação contínua).
FROM python:3.13-slim

# TZ: fuso do Brasil (sem isso o "hoje" do servidor é UTC e vira o dia às 21h).
# CRM_NUVEM: liga a portaria do Cloudflare Access em tudo e esconde o botão Encerrar.
# CRM_ENDERECOS: o endereço que o navegador vê. Atrás do Worker do Cloudflare o Host chega como *.run.app,
#   e sem isto a proteção contra CSRF (app/acesso.py) recusaria todo formulário.
ENV TZ=America/Sao_Paulo \
    CRM_NUVEM=1 \
    CRM_ENDERECOS=crm-reserva.vfitcoachapp.com \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /crm
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# O Cloud Run informa a porta em $PORT (normalmente 8080). Chaves do Turso e do Cloudflare: variáveis do serviço, nunca aqui.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
