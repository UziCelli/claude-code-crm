"""Regressões: CSRF sem Referer, verbos futuros e cache de dados privados."""
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from app import acesso, main


@pytest.mark.parametrize('metodo', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_cross_site_sem_origin_nao_pode_alterar_local(monkeypatch, metodo):
    monkeypatch.setattr(acesso, 'LIGADO', False)
    headers = Headers({'host': 'localhost:8765', 'sec-fetch-site': 'cross-site'})
    assert acesso.motivo_bloqueio(metodo, '/backup', headers, {}) == 'origem'


@pytest.mark.parametrize('metodo', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_verbo_inseguro_exige_origem_na_internet(monkeypatch, metodo):
    monkeypatch.setattr(acesso, 'LIGADO', True)
    monkeypatch.setattr(acesso, 'EQUIPE', 'example.cloudflareaccess.com')
    monkeypatch.setattr(acesso, 'AUD', 'teste')
    monkeypatch.setattr(acesso, 'verificar', lambda _: {})
    h = Headers({'host': 'crm.example.com', 'cf-access-jwt-assertion': 'sintetico'})
    assert acesso.motivo_bloqueio(metodo, '/backup', h, {}) == 'origem'
    h = Headers({**dict(h), 'origin': 'https://crm.example.com'})
    assert acesso.motivo_bloqueio(metodo, '/backup', h, {}) is None


@pytest.mark.parametrize('caminho', ['/saude', '/', '/exportar/clientes.csv', '/static/style.css'])
def test_respostas_nao_sao_guardadas_no_cache(monkeypatch, caminho):
    monkeypatch.setattr(acesso, 'LIGADO', True)
    monkeypatch.setattr(acesso, 'AUD', '')
    r = TestClient(main.app).get(caminho)
    assert r.headers['cache-control'] == 'no-store'
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert r.headers['x-frame-options'] == 'DENY'
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']
