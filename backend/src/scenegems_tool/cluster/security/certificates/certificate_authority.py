"""The master's own certificate authority.

Created once when the master is installed. Its certificate is the trust anchor a node
receives at pairing; its key never leaves the master's security folder. It issues the
server certificates of the master's API and broker, each listing the master's IP
addresses and host names as subject alternative names.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from scenegems_tool.cluster.security.certificates.subject_names import subject_alternative_names
from scenegems_tool.cluster.security.file_writing import write_private_file, write_public_file

CA_VALIDITY = datetime.timedelta(days=3650)
SERVER_CERTIFICATE_VALIDITY = datetime.timedelta(days=825)
# Tolerates clocks of nodes that run slightly behind the master.
CLOCK_SKEW_ALLOWANCE = datetime.timedelta(minutes=5)


@dataclass(frozen=True)
class IssuedCertificate:
    certificate_pem: bytes
    private_key_pem: bytes

    @property
    def certificate(self) -> x509.Certificate:
        return x509.load_pem_x509_certificate(self.certificate_pem)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _new_private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _private_key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    # The traditional EC format is the one NanoMQ's TLS stack was verified with.
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption())


class CertificateAuthority:
    def __init__(self, certificate: x509.Certificate, private_key: ec.EllipticCurvePrivateKey) -> None:
        self.certificate = certificate
        self._private_key = private_key

    @classmethod
    def create(cls, master_id: str, *, now: Optional[datetime.datetime] = None) -> "CertificateAuthority":
        now = now or _utc_now()
        key = _new_private_key()
        name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SceneGEMS"), x509.NameAttribute(NameOID.COMMON_NAME, f"SceneGEMS master {master_id} CA")])
        public_key = key.public_key()
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - CLOCK_SKEW_ALLOWANCE)
            .not_valid_after(now + CA_VALIDITY)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(public_key), critical=False)
            .sign(key, hashes.SHA256())
        )
        return cls(certificate, key)

    @classmethod
    def load(cls, certificate_path: Path, key_path: Path) -> "CertificateAuthority":
        certificate = x509.load_pem_x509_certificate(Path(certificate_path).read_bytes())
        key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or key.public_key().public_numbers() != certificate.public_key().public_numbers():
            raise ValueError(f"The CA key {key_path} does not belong to the CA certificate {certificate_path}")
        return cls(certificate, key)

    def save(self, certificate_path: Path, key_path: Path) -> None:
        write_private_file(Path(key_path), _private_key_pem(self._private_key))
        write_public_file(Path(certificate_path), self.certificate_pem)

    @property
    def certificate_pem(self) -> bytes:
        return self.certificate.public_bytes(serialization.Encoding.PEM)

    def issue_server_certificate(self, common_name: str, addresses: Iterable[str], *, now: Optional[datetime.datetime] = None) -> IssuedCertificate:
        """A TLS server certificate for `common_name`, valid for every address and the defaults."""
        now = now or _utc_now()
        key = _new_private_key()
        public_key = key.public_key()
        not_after = min(now + SERVER_CERTIFICATE_VALIDITY, self.certificate.not_valid_after_utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SceneGEMS"), x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
            .issuer_name(self.certificate.subject)
            .public_key(public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - CLOCK_SKEW_ALLOWANCE)
            .not_valid_after(not_after)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=True,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(subject_alternative_names(addresses)), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(self._private_key.public_key()), critical=False)
            .sign(self._private_key, hashes.SHA256())
        )
        return IssuedCertificate(certificate_pem=certificate.public_bytes(serialization.Encoding.PEM), private_key_pem=_private_key_pem(key))
