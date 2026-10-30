# zklite-claim

Claim your funds from zkSync Lite after the May 2026 sunset.

zkSync Lite stopped producing blocks on May 4 2026. All balances were frozen and migrated to an L1 claim contract at `0x0a14B696350546110a0D8acDb86226983af9D2a0`. This tool downloads the final state snapshot, generates the Merkle proof for your address, and sends the claim transaction.

## How it works

Matter Labs published the full final state (accounts, balances, tokens) as a ~440 MB zip. The tool downloads it, reconstructs the OZ-compatible keccak Merkle tree, and calls `claim(index, token, amount, proof[])` on the L1 distributor contract.

## Requirements

- Python 3.10+
- An Ethereum mainnet RPC URL (Alchemy, Infura, etc.)

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python claim.py \
  --address 0xYourAddress \
  --rpc https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY \
  --key 0xYourPrivateKey
```

Dry run (builds proof, skips transaction):

```bash
python claim.py \
  --address 0xYourAddress \
  --rpc https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY \
  --dry-run
```

The snapshot is cached in `./data` after first download. Building the Merkle tree takes 1-3 minutes depending on your machine.

## Options

| Flag | Description |
|---|---|
| `--address` | Your wallet address |
| `--rpc` | Ethereum mainnet RPC |
| `--key` | Private key (keep it safe) |
| `--data-dir` | Cache dir for snapshot (default: `./data`) |
| `--dry-run` | Print proof without sending |

## Contract

- Claim contract: [`0x0a14B696350546110a0D8acDb86226983af9D2a0`](https://etherscan.io/address/0x0a14b696350546110a0d8acdb86226983af9d2a0)
- Implementation: `0xfb94f8a45e81fa9f6256ddb0eec0735b8520cdea`
- Snapshot data: `https://zksync-lite-sunset.matterlabs.dev/mainnet/data.zip`
