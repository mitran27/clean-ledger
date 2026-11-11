# Report: escrow release missing caller check
Researcher: alice-demo.testnet
Contact: alice@example.com
Program: sealed-bounty-demo

The `release` method on contract `escrow.demo.testnet` does not check `predecessor_account_id`.
Anyone can call release(program_id="p1", report_id="x", to="attacker.testnet", amount=1000000).

Steps:
1. Fund program p1 with 10 USDC.
2. From any account, call release with to=your account.
3. Funds transfer without owner approval.

Test key used (revoked): ed25519:FAKEKEY1234567890abcdefDEMOONLY
