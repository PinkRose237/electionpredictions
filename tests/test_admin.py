import hashlib

from electionpredictions import admin


def test_pbkdf2_matches_webcrypto_parameters():
    salt = "00112233445566778899aabbccddeeff"
    h = admin.pbkdf2_hex("correct horse battery staple", salt)
    assert h == hashlib.pbkdf2_hmac("sha256", b"correct horse battery staple", bytes.fromhex(salt), 200_000, dklen=32).hex()
    assert len(h) == 64 and h != admin.pbkdf2_hex("wrong", salt)


def test_write_config(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "CONFIG_PATH", tmp_path / "admin-config.json")
    cfg = admin.write_config("a-long-passphrase", repo="owner/name")
    assert cfg["repo"] == "owner/name" and cfg["iterations"] == 200_000 and (tmp_path / "admin-config.json").exists()
    assert admin.pbkdf2_hex("a-long-passphrase", cfg["salt"]) == cfg["hash"]
