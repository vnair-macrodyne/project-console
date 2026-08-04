"""
pfx_to_pem.py — convert a Windows PFX/P12 to PEM (cert + chain + key) WITHOUT openssl.

Uses Python's `cryptography` (pip install cryptography) — it reads the PFX file directly, so it
does NOT hit the PowerShell/CNG plaintext-export block. Prompts for the password so there's no
quoting/placeholder trouble, and falls back to the no-password case automatically.

Usage:
    pip install cryptography
    python pfx_to_pem.py C:\\Caddy\\certs\\console.pfx            (writes into the pfx's folder)
    python pfx_to_pem.py C:\\Caddy\\certs\\console.pfx C:\\Caddy\\certs
Outputs: console.crt (leaf + any chain) and console.key (unencrypted) in the output folder.
"""
import os
import sys
import getpass

try:
    from cryptography.hazmat.primitives.serialization import (
        pkcs12, Encoding, PrivateFormat, NoEncryption)
except ImportError:
    sys.exit("cryptography not installed — run:  pip install cryptography")


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python pfx_to_pem.py <path-to.pfx> [output-dir]")
    pfx_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else (os.path.dirname(pfx_path) or ".")
    if not os.path.isfile(pfx_path):
        sys.exit(f"file not found: {pfx_path}")
    with open(pfx_path, "rb") as f:
        blob = f.read()

    entered = getpass.getpass("PFX password (leave blank if none): ")
    # try what they typed, then the empty-password forms — covers "no password" exports
    candidates = ([entered.encode()] if entered else []) + [None, b""]
    key = cert = chain = None
    last_err = None
    for pw in candidates:
        try:
            key, cert, chain = pkcs12.load_key_and_certificates(blob, pw)
            break
        except Exception as e:      # ValueError: Invalid password or PKCS12 data
            last_err = e
            key = cert = None

    if cert is None:
        print("\nCouldn't open the PFX. Most likely one of:")
        print("  • wrong password (check caps / no stray quotes or < > brackets)")
        print("  • the .pfx was exported WITHOUT the private key")
        print("  • you're pointing at the wrong file")
        print(f"\nUnderlying error: {type(last_err).__name__}: {last_err}")
        print("\nFix: in certlm.msc re-export the cert → 'Yes, export the private key' → PFX →")
        print("     set a simple password (letters/numbers), then re-run this against that file.")
        sys.exit(1)
    if key is None:
        sys.exit("The PFX has the certificate but NO private key — re-export with the key included.")

    crt_path = os.path.join(out_dir, "console.crt")
    key_path = os.path.join(out_dir, "console.key")
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    with open(crt_path, "wb") as f:
        f.write(cert.public_bytes(Encoding.PEM))
        for c in (chain or []):                 # include the issuing/intermediate chain
            f.write(c.public_bytes(Encoding.PEM))

    print("OK — wrote:")
    print(f"  {crt_path}   (leaf + {len(chain or [])} chain cert(s))")
    print(f"  {key_path}   (unencrypted key — keep it protected)")
    print("\nPoint the Caddyfile at these two files and you're set.")


if __name__ == "__main__":
    main()
