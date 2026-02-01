# Deploy Synth-Engine to Railway

## Quick Deploy Steps

### 1. Go to Railway
Open [railway.app](https://railway.app) and sign in with GitHub.

### 2. Create New Project
- Click "New Project"
- Select "Deploy from GitHub repo"
- Choose your Perseus repository
- **Important**: Set the root directory to `roma-n8n-synthesizer/synth-engine`

### 3. Add Environment Variables
In Railway's Variables tab, add these:

```
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key (optional)
N8N_API_KEY=your_n8n_api_key
N8N_BASE_URL=https://perseustech.app.n8n.cloud/api/v1
SUPABASE_URL=your_supabase_url
SUPABASE_ANON_KEY=your_supabase_anon_key
LLM_PROVIDER=anthropic
```

### 4. Deploy
Railway will automatically build and deploy using the Dockerfile.

### 5. Get Your URL
After deployment, Railway gives you a URL like:
`https://synth-engine-production-xxxx.up.railway.app`

### 6. Update AGENT_RUNNER_URL
Once deployed, update your local `.env`:
```
AGENT_RUNNER_URL=https://your-railway-url.up.railway.app
```

### 7. Test the Deployment
```bash
curl https://your-railway-url.up.railway.app/health
```

---

## Alternative: Deploy via CLI

If you have Railway CLI token:
```bash
cd roma-n8n-synthesizer/synth-engine
export RAILWAY_TOKEN=your_token
railway up
```

## Troubleshooting

- If build fails, check Railway logs
- Ensure Python 3.11 is used (specified in Dockerfile)
- Check all env vars are set correctly
