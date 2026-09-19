"""
solana_agent.py
===============
Solana Agent Skills for Project Tara:
- Persistent Devnet Agent Keypair (Sender)
- Dedicated Tara DCA Savings Vault (Recipient)
- Autonomous Agentic DCA Transfers
- On-Chain Attestation via Solana Memo Program
"""

import json
import base64
import os
import time
import requests
import base58
from pathlib import Path
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash

DEVNET_RPC_URL = "https://api.devnet.solana.com"
MEMO_PROGRAM_ID_STR = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
KEY_FILE = Path(__file__).resolve().parent / "solana_agent_key.json"
VAULT_FILE = Path(__file__).resolve().parent / "solana_vault_key.json"


class SolanaAgentEngine:
    def __init__(self):
        # 1. Agent Wallet (Sender - funded with your 0.5 SOL)
        self.keypair = self._load_or_create_keypair(KEY_FILE)
        self.pubkey = self.keypair.pubkey()
        self.pubkey_str = str(self.pubkey)

        # 2. Tara DCA Vault Wallet (Recipient of the DCA investments)
        self.vault_keypair = self._load_or_create_keypair(VAULT_FILE)
        self.vault_pubkey = self.vault_keypair.pubkey()
        self.vault_pubkey_str = str(self.vault_pubkey)

        print(f"✓ Solana Agent Active on Devnet! Sender: {self.pubkey_str}")
        print(f"✓ Tara DCA Savings Vault: {self.vault_pubkey_str}")

    def _load_or_create_keypair(self, file_path: Path) -> Keypair:
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text())
                return Keypair.from_bytes(bytes(data))
            except Exception:
                pass
        
        new_kp = Keypair()
        try:
            file_path.write_text(json.dumps(list(bytes(new_kp))))
        except Exception:
            pass
        return new_kp

    def _rpc_call(self, method: str, params: list) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        res = requests.post(DEVNET_RPC_URL, json=payload, timeout=10)
        return res.json()

    def get_balance(self, address: str = None) -> float:
        target = address or self.pubkey_str
        try:
            res = self._rpc_call("getBalance", [target])
            lamports = res.get("result", {}).get("value", 0)
            return round(lamports / 1_000_000_000, 4)
        except Exception:
            return 0.0

    def get_latest_blockhash(self) -> Hash:
        res = self._rpc_call("getLatestBlockhash", [{"commitment": "finalized"}])
        bh_str = res["result"]["value"]["blockhash"]
        return Hash.from_string(bh_str)

    def execute_agent_dca_transfer(self, destination_address: str = None, sol_amount: float = 0.05) -> dict:
        """
        Autonomous Agent Skill: Transfers Devnet SOL from the agent wallet
        into the Tara DCA Savings Vault.
        """
        try:
            # INTERCEPTOR: If destination is empty, Vote1111, or a program ID, redirect to Tara DCA Vault
            if (not destination_address 
                or "Vote1111" in str(destination_address) 
                or "11111111111111111111111111111111" in str(destination_address)):
                destination_address = self.vault_pubkey_str

            dest_pubkey = Pubkey.from_string(destination_address)
            lamports = int(sol_amount * 1_000_000_000)
            recent_blockhash = self.get_latest_blockhash()

            # Build transfer instruction
            transfer_ix = transfer(
                TransferParams(
                    from_pubkey=self.pubkey,
                    to_pubkey=dest_pubkey,
                    lamports=lamports
                )
            )

            # Cryptographically sign transaction with Agent Keypair
            msg = Message([transfer_ix], self.pubkey)
            tx = Transaction([self.keypair], msg, recent_blockhash)

            # Broadcast wire transaction to Solana Devnet
            wire_b64 = base64.b64encode(bytes(tx)).decode('utf-8')
            res = self._rpc_call("sendTransaction", [wire_b64, {"encoding": "base64"}])

            if "error" in res:
                return {"status": "error", "message": res["error"].get("message", "Devnet RPC rejection")}

            tx_sig = res.get("result")
            return {
                "status": "success",
                "signature": tx_sig,
                "explorer_url": f"https://explorer.solana.com/tx/{tx_sig}?cluster=devnet",
                "amount": sol_amount,
                "from": self.pubkey_str,
                "to": destination_address
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}