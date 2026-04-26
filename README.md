# LeadsAPI — Global Lead Generation SaaS

## Architecture
```
GET /leads?query=gyms in hyderabad
        ↓
Extract location → "hyderabad"
        ↓
Geocode → lat: 17.38, lon: 78.48
        ↓
Generate 5x5 grid (25 points, ~5km apart)
        ↓
Google Maps scraper × 25 points → raw businesses
        ↓
Filter unique websites (max 50)
        ↓
Contact scraper × websites → emails + phones
        ↓
Clean + deduplicate + sort by confidence
        ↓
Return clean leads list
```

## File Structure
```
leads/
├── api_server.py        # FastAPI endpoints
├── leads_service.py     # Full scraping pipeline
├── config.py            # MongoDB URI, port
├── db.py                # Shared Motor client
├── keys.py              # Apify key rotation (MongoDB)
├── run.py               # Entry point
├── cloudflare_tunnel.py # Tunnel manager
├── requirements.txt
└── utils/
    ├── location.py      # Geocoding + grid generation
    └── cleaner.py       # Dedup + data cleaning
```

## Setup
```bash
cd leads/
pip install -r requirements.txt
python run.py
```

## API Usage

### Get Leads
```
GET /leads?query=gyms in hyderabad
Header: x-api-key: <your-key>

# Optional: control coverage
GET /leads?query=gyms in hyderabad&grid_size=1   # 3x3 = 9 points (faster)
GET /leads?query=gyms in hyderabad&grid_size=2   # 5x5 = 25 points (default)
GET /leads?query=gyms in hyderabad&grid_size=3   # 7x7 = 49 points (wider)
```

### Response
```json
{
  "query": "gyms in hyderabad",
  "total_leads": 23,
  "leads": [
    {
      "name": "Power Gym",
      "website": "https://powergym.in",
      "email": "info@powergym.in",
      "phone": "+91 98765 43210",
      "confidence": 0.92
    }
  ]
}
```

### Check Usage
```
GET /me
Header: x-api-key: <your-key>
```

## Key Management
Uses same Apify key rotation system as Instagram API.
Add keys via Telegram bot → 🔑 API Keys → ➕ Add Key

## Query Examples
- `gyms in hyderabad`
- `restaurants in dubai`
- `dentists near mumbai`
- `hotels in bangalore`
- `plumbers in delhi`
- `beauty salons in chennai`

## Actors Used
| Actor | Purpose | Cost |
|-------|---------|------|
| `xmiso_scrapers/google-maps-scraper` | Find businesses on Maps | varies |
| `happyfhantum/verified-website-contact-scraper` | Extract emails from websites | varies |

## Grid Size Guide
| grid_size | Points | Coverage | Speed |
|-----------|--------|----------|-------|
| 1 | 9 | ~15km radius | Fast |
| 2 | 25 | ~25km radius | Medium (default) |
| 3 | 49 | ~35km radius | Slow but thorough |
