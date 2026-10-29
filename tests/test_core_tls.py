from __future__ import annotations

from pathlib import Path

from ultima_scraper_core.tls import ensure_self_signed, fingerprint, fingerprint_der


def test_a_self_signed_certificate_is_kept_and_its_fingerprint_matches_the_peer_view(tmp_path: Path) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding

    first = ensure_self_signed(tmp_path, ["alpha.lan"], common_name="UltimaScraper backend")
    again = ensure_self_signed(tmp_path, ["alpha.lan"], common_name="UltimaScraper backend")

    certificate = x509.load_pem_x509_certificate(first.cert_file.read_bytes())
    assert first == again and first.self_signed
    assert "UltimaScraper backend" in certificate.subject.rfc4514_string()
    assert (first.key_file.stat().st_mode & 0o777) == 0o600
    # What a client computes from the certificate the server presents.
    assert fingerprint_der(certificate.public_bytes(Encoding.DER)) == fingerprint(first.cert_file)
    assert len(fingerprint(first.cert_file).split(":")) == 32


def test_a_new_name_renews_the_certificate(tmp_path: Path) -> None:
    first = fingerprint(ensure_self_signed(tmp_path, ["a.lan"]).cert_file)
    renewed = fingerprint(ensure_self_signed(tmp_path, ["a.lan", "b.lan"]).cert_file)

    assert renewed != first
