# Local and deployment setup

## Local development

Use Python 3.11+ and Node.js 20.9+ (the current Next.js 16 minimum). From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
set -a && source .env && set +a
PYTHONPATH=src uvicorn finsight.api.app:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd web
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`; the API health endpoint is `http://localhost:8000/api/health`, and interactive API documentation is available at `/docs`. Set `NEXT_PUBLIC_FINSIGHT_API_URL` in `web/.env.local` when the API runs at a different local URL.

## Public deployment path

The initial hosting split is Next.js on Vercel and FastAPI on Render. Both can deploy from this repository without changing the application's API/database boundary.

1. **Deploy the API on Render:** connect the existing GitHub repository and use the included `render.yaml`. It builds with `pip install -r requirements.txt`, starts Uvicorn, and checks `/api/health`. Set `FINSIGHT_CORS_ORIGINS` to the Vercel site origin after the Vercel project has a URL.
2. **Deploy the frontend on Vercel:** import the same repository, set Root Directory to `web`, and set `NEXT_PUBLIC_FINSIGHT_API_URL` to the Render API origin before building. The variable is public and must contain no credentials.
3. Verify the Vercel page can reach `/api/status`, and verify the API health URL responds. Add the resulting public URLs to project documentation only after checking them.

Vercel's monorepo project setup uses a selected root directory; Next.js public environment variables are bundled at build time, so configure the API URL in the Vercel project before deployment. See [Vercel monorepo setup](https://vercel.com/docs/monorepos) and [Next.js environment variables](https://nextjs.org/docs/app/guides/environment-variables).

Render web services have an ephemeral filesystem by default. The included free service stores its empty SQLite file under `/tmp`; it can be recreated after a restart or deploy. This is acceptable only while there is no onboarded financial dataset. Render persistent disks are available to paid services and preserve files only beneath their mount path. Before onboarding real data, either upgrade and mount a persistent disk (for example `/var/data`, with `FINSIGHT_DATABASE_PATH=/var/data/finsight.sqlite3`) or migrate to managed PostgreSQL. Do not rely on the included ephemeral SQLite path for durable disclosures. See [Render web services](https://render.com/docs/web-services) and [Render disks](https://render.com/docs/disks).

No hosting account has been connected, and this project has not been deployed. Public service creation requires the owner to authorize the repository in Vercel and Render and configure the two public origins. Do not claim a live URL until both deployments have been tested.
