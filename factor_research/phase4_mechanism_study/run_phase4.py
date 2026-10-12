from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .contracts import Phase4ContractError, load_and_verify_preregistration

ENGINE_FILES = (
    "__init__.py",
    "contracts.py",
    "mechanisms.py",
    "overlap.py",
    "run_phase4.py",
    "simulator.py",
    "statistics.py",
    "volatility.py",
)


def engine_code_hash(root: Path | None = None) -> str:
    base = root or Path(__file__).parent
    digest = hashlib.sha256()
    for relative in sorted(ENGINE_FILES):
        source = base / relative
        if not source.is_file():
            raise Phase4ContractError(f"CODE_FILE_MISSING: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def verify_frozen_contract(root: Path | None = None) -> dict[str, str]:
    base = root or Path(__file__).parent
    preregistration = load_and_verify_preregistration(base / "preregistration.json")
    expected_code_hash = preregistration.get("code_hash_sha256")
    actual_code_hash = engine_code_hash(base)
    if not expected_code_hash:
        raise Phase4ContractError("CODE_HASH_NOT_FROZEN")
    if actual_code_hash != expected_code_hash:
        raise Phase4ContractError("CODE_HASH_MISMATCH")
    return {
        "status": "PHASE4_1_CONTRACT_VERIFIED",
        "rule_hash_sha256": preregistration["rule_hash_sha256"],
        "code_hash_sha256": actual_code_hash,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4.1 contract verifier; real research execution is disabled.")
    parser.add_argument("--verify-contract-only", action="store_true")
    args = parser.parse_args()
    if not args.verify_contract_only:
        parser.error("REAL_PHASE4_EXECUTION_NOT_AUTHORIZED; use --verify-contract-only")
    print(json.dumps(verify_frozen_contract(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
