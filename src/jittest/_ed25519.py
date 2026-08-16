"""Pure-Python Ed25519 (RFC 8032), vendored so that jittest keeps zero dependencies.

Source: the reference implementation published in RFC 8032, "Edwards-Curve Digital
Signature Algorithm (EdDSA)", Appendix A (Josefsson & Liusvaara, IRTF, January 2017).
The RFC's example code is published for unrestricted use; it is reproduced here with
type annotations added and no algorithmic changes.

Why vendored rather than depending on `cryptography`:

    A verification tool must not gate its central guarantee on an optional
    dependency. Before this module existed, a default `pip install jittest`
    could neither produce an independently verifiable receipt nor verify the
    receipts in jittest's own published evidence. Both are now possible in
    every install.

Correctness is pinned by RFC 8032 test vectors in
`tests/test_cross_env_receipt_verification.py`, and by a byte-equality test against
`cryptography` when that package happens to be present. Ed25519 signatures are
deterministic, so agreement is exact rather than probabilistic.

Performance note: signing or verifying costs single-digit milliseconds here versus
microseconds in libsodium. jittest signs one receipt per verification run, so the
difference is immaterial; `receipt.py` still prefers `cryptography` when available.
"""

from __future__ import annotations

import hashlib

__all__ = ["sign", "verify", "secret_to_public", "SEED_SIZE", "SIGNATURE_SIZE"]

SEED_SIZE = 32
PUBLIC_KEY_SIZE = 32
SIGNATURE_SIZE = 64

# Base field Z_p
_p = 2**255 - 19

# Group order
_q = 2**252 + 27742317777372353535851937790883648493


def _sha512(s: bytes) -> bytes:
    return hashlib.sha512(s).digest()


def _modp_inv(x: int) -> int:
    return pow(x, _p - 2, _p)


# Curve constant
_d = -121665 * _modp_inv(121666) % _p

# Square root of -1
_modp_sqrt_m1 = pow(2, (_p - 1) // 4, _p)


def _sha512_modq(s: bytes) -> int:
    return int.from_bytes(_sha512(s), "little") % _q


# Points are represented as tuples (X, Y, Z, T) of extended coordinates,
# with x = X/Z, y = Y/Z, x*y = T/Z


def _point_add(P: tuple, Q: tuple) -> tuple:
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _point_mul(s: int, P: tuple) -> tuple:
    Q = (0, 1, 1, 0)  # neutral element
    while s > 0:
        if s & 1:
            Q = _point_add(Q, P)
        P = _point_add(P, P)
        s >>= 1
    return Q


def _point_equal(P: tuple, Q: tuple) -> bool:
    # x1/z1 == x2/z2  <==>  x1*z2 == x2*z1
    if (P[0] * Q[2] - Q[0] * P[2]) % _p != 0:
        return False
    return (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _p:
        return None
    x2 = (y * y - 1) * _modp_inv(_d * y * y + 1)
    if x2 == 0:
        return None if sign else 0

    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _modp_sqrt_m1 % _p
    if (x * x - x2) % _p != 0:
        return None

    if (x & 1) != sign:
        x = _p - x
    return x


# Base point
_g_y = 4 * _modp_inv(5) % _p
_g_x = _recover_x(_g_y, 0)
assert _g_x is not None
_G = (_g_x, _g_y, 1, _g_x * _g_y % _p)


def _point_compress(P: tuple) -> bytes:
    zinv = _modp_inv(P[2])
    x = P[0] * zinv % _p
    y = P[1] * zinv % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _point_decompress(s: bytes) -> tuple | None:
    if len(s) != 32:
        raise ValueError("invalid input length for decompression")
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _p)


def _secret_expand(secret: bytes) -> tuple[int, bytes]:
    if len(secret) != SEED_SIZE:
        raise ValueError(f"ed25519 seed must be {SEED_SIZE} bytes, got {len(secret)}")
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return (a, h[32:])


def secret_to_public(secret: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte seed."""
    a, _ = _secret_expand(secret)
    return _point_compress(_point_mul(a, _G))


def sign(secret: bytes, msg: bytes) -> bytes:
    """Return the deterministic 64-byte Ed25519 signature of ``msg``."""
    a, prefix = _secret_expand(secret)
    A = _point_compress(_point_mul(a, _G))
    r = _sha512_modq(prefix + msg)
    R = _point_mul(r, _G)
    Rs = _point_compress(R)
    h = _sha512_modq(Rs + A + msg)
    s = (r + h * a) % _q
    return Rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    """Return True only if ``signature`` is a valid Ed25519 signature of ``msg``."""
    if len(public) != PUBLIC_KEY_SIZE:
        return False
    if len(signature) != SIGNATURE_SIZE:
        return False
    try:
        A = _point_decompress(public)
        if not A:
            return False
        Rs = signature[:32]
        R = _point_decompress(Rs)
        if not R:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= _q:
            return False
        h = _sha512_modq(Rs + public + msg)
        sB = _point_mul(s, _G)
        hA = _point_mul(h, A)
        return _point_equal(sB, _point_add(R, hA))
    except (ValueError, TypeError):
        return False
