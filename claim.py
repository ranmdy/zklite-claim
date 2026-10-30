#!/usr/bin/env python3
import argparse
import csv
import sys
import zipfile
from pathlib import Path

import requests
from web3 import Web3

DATA_URL = "https://zksync-lite-sunset.matterlabs.dev/mainnet/data.zip"
CLAIM_CONTRACT = "0x0a14B696350546110a0D8acDb86226983af9D2a0"
CLAIM_ABI = [
    {
        "inputs": [
            {"name": "index", "type": "uint256"},
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "proof", "type": "bytes32[]"},
        ],
        "name": "claim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


def keccak256(data):
    return bytes(Web3.keccak(primitive=data))


def leaf_hash(index, claimant, token, amount):
    packed = (
        index.to_bytes(32, "big")
        + bytes.fromhex(claimant[2:])
        + bytes.fromhex(token[2:])
        + amount.to_bytes(32, "big")
    )
    return keccak256(packed)


def hash_pair(a, b):
    return keccak256(a + b) if a <= b else keccak256(b + a)


def build_proof(hashes, target):
    level = list(hashes)
    proof = []
    pos = target

    while len(level) > 1:
        sibling = pos ^ 1
        if sibling < len(level):
            proof.append(level[sibling])

        next_level = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                next_level.append(hash_pair(level[i], level[i + 1]))
            else:
                next_level.append(level[i])

        pos //= 2
        level = next_level

    return level[0], proof


def download_data(dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / "data.zip"

    if not zip_path.exists():
        print("Downloading snapshot (~440 MB)...")
        r = requests.get(DATA_URL, stream=True)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        done = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / total:.0%}", end="", flush=True)
        print()

    needed = {"accounts.csv", "balances.csv", "tokens.csv"}
    if not all((dest / n).exists() for n in needed):
        print("Extracting...")
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                name = Path(member).name
                if name in needed:
                    (dest / name).write_bytes(zf.read(member))


def load_leaves(data_dir):
    data_dir = Path(data_dir)

    tokens = {}
    with open(data_dir / "tokens.csv") as f:
        for row in csv.DictReader(f):
            tokens[int(row["id"])] = row["address"].lower()

    accounts = {}
    with open(data_dir / "accounts.csv") as f:
        for row in csv.DictReader(f):
            accounts[int(row["id"])] = row["address"].lower()

    agg = {}
    with open(data_dir / "balances.csv") as f:
        for row in csv.DictReader(f):
            bal = int(row["balance"])
            if bal == 0:
                continue
            addr = accounts.get(int(row["account_id"]))
            tok = tokens.get(int(row["coin_id"]))
            if addr and tok:
                key = (addr, tok)
                agg[key] = agg.get(key, 0) + bal

    # matches Rust BTreeMap<(Address, Address)> ordering
    sorted_pairs = sorted(
        agg.items(),
        key=lambda x: (bytes.fromhex(x[0][0][2:]), bytes.fromhex(x[0][1][2:]))
    )

    return [(i, addr, tok, amt) for i, ((addr, tok), amt) in enumerate(sorted_pairs)]


def send_claim(w3, key, address, index, token, amount, proof):
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CLAIM_CONTRACT), abi=CLAIM_ABI
    )
    proof_bytes = [bytes.fromhex(p[2:]) for p in proof]

    tx = contract.functions.claim(
        index,
        Web3.to_checksum_address(token),
        amount,
        proof_bytes,
    ).build_transaction({
        "from": address,
        "nonce": w3.eth.get_transaction_count(address),
        "gas": 150_000,
    })

    signed = w3.eth.account.sign_transaction(tx, key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    return receipt


def main():
    parser = argparse.ArgumentParser(description="Claim zkSync Lite funds after the May 2026 sunset")
    parser.add_argument("--address", required=True)
    parser.add_argument("--rpc", required=True, help="Ethereum mainnet RPC URL")
    parser.add_argument("--key", help="Private key (0x...)")
    parser.add_argument("--data-dir", default="./data")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    download_data(args.data_dir)

    print("Building Merkle tree from snapshot (may take a few minutes)...")
    leaves = load_leaves(args.data_dir)
    print(f"  {len(leaves):,} leaves")

    addr = args.address.lower()
    my_leaves = [(i, a, t, amt) for i, a, t, amt in leaves if a == addr]

    if not my_leaves:
        print(f"No balances found for {args.address}")
        sys.exit(0)

    for _, _, tok, amt in my_leaves:
        label = "ETH" if tok == "0x" + "0" * 40 else tok
        print(f"  {amt} of {label}")

    print("Computing proofs...")
    all_hashes = [leaf_hash(i, a, t, amt) for i, a, t, amt in leaves]

    w3 = Web3(Web3.HTTPProvider(args.rpc)) if not args.dry_run else None

    for index, _, token, amount in my_leaves:
        root, proof = build_proof(all_hashes, index)
        proof_hex = ["0x" + p.hex() for p in proof]

        print(f"\n  token:  {token}")
        print(f"  index:  {index}")
        print(f"  amount: {amount}")
        print(f"  root:   0x{root.hex()}")

        if args.dry_run:
            print("  [dry-run]")
            continue

        if not args.key:
            print("  skipping (no --key provided)")
            continue

        checksum = Web3.to_checksum_address(args.address)
        receipt = send_claim(w3, args.key, checksum, index, token, amount, proof_hex)
        status = "success" if receipt.status == 1 else "failed"
        print(f"  {status}: {receipt.transactionHash.hex()}")


if __name__ == "__main__":
    main()
