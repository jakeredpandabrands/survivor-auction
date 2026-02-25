# Survivor Auction

Outwit, outbid, outlast. The party game inspired by the Survivor TV auction. Bid back and forth on items (food, comforts, gag items). When the auction ends, everyone ranks each other's performance. The winner is decided by your peers!

## Quick Start

```bash
cd survivor-auction
pip install -r requirements.txt
python app.py
```

Open http://localhost:5001 (or http://YOUR_IP:5001 for others on your WiFi).

1. Host: Create Game (choose a 4–6 character code) → host auto-joins
2. Players: Enter the game code and name on the main page
3. Host: Start Game when 2–8 players are ready
4. Each round: bid to outbid the current high bid, or sit out (just don't bid)
5. Timer runs out → highest bidder wins the item
6. Dynamic round count: players × 2 to × 5 rounds (you don't know when it ends!)
7. Mystery items: 10–20% of rounds — you bid without knowing what it is until someone wins
8. After the auction: rank all other players from best to worst auction performance
9. Winner = Borda count from everyone's rankings

## Rules

- **Starting budget:** $1,000
- **Starting bid per item:** $20
- **Timer:** 30 seconds per item; new bid extends by 30 seconds
- **No pass button:** To sit out, simply don't bid
- **Win condition:** Peers rank your auction performance; highest Borda score wins

## Deploy to Render

1. Push this repo to GitHub.
2. Go to [render.com](https://render.com) → Sign up (free).
3. **New** → **Web Service**.
4. Connect your GitHub repo. If survivor-auction is a subfolder, set **Root Directory** to `survivor-auction`.
5. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app -c gunicorn_config.py` (1 worker for shared state)
6. Click **Create Web Service**.

## Future Enhancements

**Blind auction mode:** Alternative game mode where each player submits one secret bid per item. No one sees others' bids until the reveal. Highest bid wins. Simpler technically (no timer, no real-time bidding) but different from the TV show. Could be a host-selectable option in a future release.
