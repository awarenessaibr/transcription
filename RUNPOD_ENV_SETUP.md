# RunPod Serverless Endpoint Environment Configuration

## Critical Issue: Environment Variables Not Loaded in Production

When running in **RunPod Serverless**, the `.env` file is **NOT automatically loaded** because the service runs in production mode (`ENV=production`). 

You must configure all environment variables directly in your **RunPod endpoint settings**.

## Required Environment Variables for RunPod

Go to your RunPod endpoint configuration and set these variables:

### 1. **HuggingFace Authentication** (REQUIRED)
```
PYANNOTE_AUTH_TOKEN=hf_your_token_here
```
OR set at least one of:
- `HF_TOKEN`
- `HUGGINGFACE_HUB_TOKEN`  
- `use_auth_token`

Get token from: https://huggingface.co/settings/tokens

### 2. **AI Provider** (REQUIRED for analysis features)
Choose ONE:

**Option A: DeepSeek (Currently Configured)**
```
DEEPSEEK_API_KEY=sk-your_key_here
DEEPSEEK_ANALYZER_MODEL=deepseek-v4-flash
DEEPSEEK_RECONCILER_MODEL=deepseek-v4-pro
```

**Option B: Anthropic Claude**
```
ANTHROPIC_API_KEY=sk-your_key_here
ANTHROPIC_MODEL=claude-3-opus
ANTHROPIC_BASE_URL=https://api.anthropic.com
```

### 3. **Qdrant Vector Database** (Optional)
```
QDRANT_URL=https://your-qdrant-instance.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key_here
```

### 4. **RunPod Configuration** (REQUIRED)
```
RUNPOD_API_KEY=rpa_your_key_here
RUNPOD_ENDPOINT_ID=your_endpoint_id
```

### 5. **Optional: Logging**
```
LOG_LEVEL=INFO
ENV=production
```

## Verification

After updating the endpoint configuration:

1. **Restart the endpoint** to apply new environment variables
2. **Check logs** for the message: `[runpod] Runtime config validated. Ready to accept jobs.`
3. **Test with a job** — submit a test transcription job to verify it's picked up and processed

## Troubleshooting

### Jobs Still Stuck?
1. Check CloudWatch/RunPod logs for initialization errors
2. Verify all required tokens are present and valid
3. Restart the endpoint if you just updated environment variables

### "Transcript analysis disabled" in logs?
- Ensure `DEEPSEEK_API_KEY` or `ANTHROPIC_API_KEY` is set in endpoint config
- Check the token is valid and not expired

### Qdrant connection failed?
- If Qdrant is optional for your use case, this is non-fatal
- If you need vector search, verify `QDRANT_URL` and `QDRANT_API_KEY` are correct

## Reference: How to Access RunPod Endpoint Settings

1. Log in to https://www.runpod.io/console
2. Navigate to **Serverless** → **Endpoints**
3. Click your endpoint
4. Go to **Settings** or **Environment**
5. Add/update environment variables
6. **Save** and **Restart** the endpoint
