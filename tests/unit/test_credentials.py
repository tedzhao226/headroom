import base64
import json

import pytest
from google.oauth2 import service_account

from headroom.core.credentials import get_gcp_credentials

FAKE_SA_INFO = {
    "type": "service_account",
    "project_id": "test-project",
    "private_key_id": "key-id",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEAqdUQoPhu8CDjzcBFILeLXehaDH2sX3AG0l33G6DoI3Vf+Ewu\nwKIOgO4mzt6OjkvMZ85nfa9J3ssX3f04j3MuwMzZ14oK55FUga7lXpk0fWq3ZwGd\nq18da0OPiSJVl4UQ2Az8GD2f9kKQAD72jo+TDPKLIqluiZz3/xubEALqjat92UnT\nKkp9njCU+BOiqzZtuLqO4FbeT+7UVsGZA5GHcYdMgUc6Q9EEF5TS7jA6lnoCneii\nx0yd6kJ+DT+qVqbs7QrL3wiWvYAjulaGdqNYooRHdVAezaE1IsfikCNFKZRO9krS\nq/iCyyWHlEWgPibLbIHD15qYkJbGuJFTJ3V1eQIDAQABAoIBAA86yRv2S1SDTopj\n5I8Tho7sSC74kh2Y2TPCM2ep3UdYvjtw8Xxay/wp3xcMBDKkf3cLnmI59uDgy4of\nrBPJG3c0p5BZk7LCaJacjXsXOArLKBk3nuEATY4R5+w/RPeqeiE1wOGXnSGjRHCR\nNOEB5QjzMyDvmrcCeYbJ/fTInioIAi9/XjTs4UNE2bSqbjGXqObdSp4UhqdAKIfx\narGW39YUX6TIqyNOQfQDLi0KaT6F6zTcocapcQklD7yQgfXv8/ai3quoVDV+CMR0\niJS6nDlSKB6Tz6A0gWMalXn1FJ1DiRed5G3lBps64m0QcYBebTjCqyybdJp5z1pR\n5k5g2gUCgYEA7dWmRtd4+G9oEKOy8dDU7e6y0UHiuoC1Uyfs7Ck2HvRpGXjKJ8ZK\nepg8PK0Obbwow0rtNBAkYimyplo7K14FN/58I4y43K3EF1j7C9amdbfrDqfXHMsQ\nnxD30VyLOiFvLJ9MW1PAKCiiF84LRp0TYtVJ4VlhNJ2A6LTu4cVn03cCgYEAts3G\naKKo080pQ5PWkcAe6yQPQWoLkJZuWhsDbjbEED0pzFsx2R+X/kTiGLS2t9wjyGp3\nxHi6CmrJ6amCy8qBehnGkyDqMfIEK/u4N0UzgyG6e3XglXVtBAf4NDMteKgLxFTc\nOe9PBtvF4UsA3syYU6yGE787NfQc40d9TYV12o8CgYBO/EZlfofhUfZomEUEhAtD\nHaPrVQs8TyRpAnhvkdw0eY0x9WiFvxfbERXoPLzu+q869HZEdRvwMdLv5kWCSI5J\nI04M7F40g8z8yANP0jCkJbl9u4X4PQQ/H3593FMssg/e7OSJ7A2ECMKUT0x1XhMj\nHpyTp4Bd3fUC05wGBO5PTwKBgCg9H4GE3JjSvlSLxF2M5sFnzJvflfAbzOq0q4ql\nL39Ll1nOcSiUFcb4rrQ1g0rxgEbreLWcxYbpfsyabZoiV2HjLpzQT/zygwyTejdg\nWjhxQjVO+0Kq+HY8stv6r/WxN/XdoCR4kvK1iddPxT9F1foFLfZGz+fOdlVpNSHN\nUOXtAoGAKSHgr0fq+NNqiFhdWm8Klr6HM75nBMGGxlA1/K1psLTxocer70XnfOUP\nr553DcWMFiHK7LwQPftHUfRhTomNb3VOQDV2kUBh38nMNMczD5m2p4L+Zsr0Rx2A\nCAA3fhIR5nxGpP4wZIA028C46dmNOayoB5iGJ5ltHwW5x+UI5F4=\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "test@test-project.iam.gserviceaccount.com",
    "client_id": "123456789",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def test_get_gcp_credentials(monkeypatch) -> None:
    encoded = base64.b64encode(json.dumps(FAKE_SA_INFO).encode()).decode()
    monkeypatch.setenv("GCP_SA_KEY", encoded)

    creds = get_gcp_credentials()

    assert isinstance(creds, service_account.Credentials)
    assert creds.service_account_email == "test@test-project.iam.gserviceaccount.com"


def test_get_gcp_credentials_missing_env(monkeypatch) -> None:
    monkeypatch.delenv("GCP_SA_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GCP_SA_KEY"):
        get_gcp_credentials()
