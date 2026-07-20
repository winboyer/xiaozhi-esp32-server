#!/usr/bin/env python3
"""Fetch platformPersonId from /report/attendance/attendanceDay for 2026-06-03"""
import json
import time
import uuid
import base64
import requests
from urllib.parse import quote

BASE_URL = "https://dw.yzw.cn/open"
ACCESS_KEY = "be69162bdd4e46619ac95824a88b1ec2"
PROJECT_KEY = "e3ae0e4a0ab6478da33bce089237a9ed"
PRIVATE_KEY_BASE64 = (
    "MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAMjBwnRaM3p+uDJQ0WsESmaOIbgNOtvkIMacRuJK+okoIqJFeWQhjPvimnTaQdvHFuYemaLllkH5tWNTlxM4cwSDw7OISc/2wGcfn8jX+QWu46MohsfNGudBG+/izia3I3QtwZmlSDBRjOYK2KbmO853zMxZnyj2b5lLCo/nixnjAgMBAAECgYAPbPf2MCu7DCHQiyFneDDUhYC1kp3eevGolFlL/QsYK+A3y/loxlbKnSq7sz0scbVJB4cYzn+HrUDEE46AGK4zQt5B4EAqtDsyC0Lwjpo2O4ObrLPeSN+CehUZ4fnXqnPq+/+vwjflzysYPh8ij7FYGOhme2QpPgBlVNX9zYlQgQJBAOMFE3jN2WazdXZfmfQIJPjC6F0fIEhXgSyhqpxeB5iMOyu5jmI2HhMVmqUogvj3WNjwxeuO87DpoMDehoBBQIECQQDiYmt9UMEEIw3ko6zklUM6KOJuf4CuniCplW9B7W14QgSYF/fjQ+5J6MHSPIR5n4JSc5ih72qgfobSHtj+uyhjAkB8iLlQyKNcyk9CW1lJ2/nkGI99HekIpi/vOtQrqQ1DqpF+//BSgdtnnq9RsHKAfrdXcmUwPiACSXbstmVUD/eBAkBHNPnmcu4jZPtLvYf2ZlS9CHsgko5hXm+bp9tU+1+BghJ73J4mKAndyY6dmFd7Agc19BJAbVQ2o1W45ecPSMNNAkEAmxqzT4nt0pujXBP5XsLuta0WT9XszMNC1yJef1kcTCMHQGntmNHhD/oOheGyFGc+hOB6AfZbAim9GyCgBxQDMQ=="
)

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

pem = "-----BEGIN PRIVATE KEY-----\n" + PRIVATE_KEY_BASE64 + "\n-----END PRIVATE KEY-----"
private_key = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())

ts = str(int(time.time() * 1000))
nonce = uuid.uuid4().hex
sign_source = ACCESS_KEY + ts + nonce
sig = private_key.sign(sign_source.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
sign = quote(base64.b64encode(sig).decode(), safe="")

url = f"{BASE_URL}/report/attendance/attendanceDay?projectKey={PROJECT_KEY}&accessKey={ACCESS_KEY}&timestamp={ts}&nonce={nonce}&sign={sign}"
print(f"URL: {url}")
print()

resp = requests.post(url, json={"projectKey": PROJECT_KEY, "date": "2026-06-03"}, timeout=60)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Code: {data.get('statusCode')}  Msg: {data.get('message')}")

# Extract platformPersonId
platform_person_ids = []
def extract_ids(obj):
    if isinstance(obj, dict):
        if "platformPersonId" in obj and obj["platformPersonId"] is not None:
            platform_person_ids.append(str(obj["platformPersonId"]))
        elif "personId" in obj and obj["personId"] is not None:
            platform_person_ids.append(str(obj["personId"]))
        for v in obj.values():
            extract_ids(v)
    elif isinstance(obj, list):
        for item in obj:
            extract_ids(item)

extract_ids(data.get("data", {}))
print(f"\nTotal platformPersonId count: {len(platform_person_ids)}")
print("platformPersonId list:")
print(json.dumps(platform_person_ids, ensure_ascii=False))