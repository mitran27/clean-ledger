# Report: anyone can withdraw bounty funds
Researcher: bob-demo.testnet
Contact: bob@example.org
Program: sealed-bounty-demo

I found that the payout function in the escrow contract can be called by any account,
not just the relayer. I called it from bob-demo.testnet and received the program funds.
Same contract: escrow.demo.testnet, method release.
