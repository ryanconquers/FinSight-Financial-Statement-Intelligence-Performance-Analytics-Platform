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

## GitHub Pages frontend

The frontend exports as static HTML, CSS, and JavaScript and deploys to GitHub Pages through `.github/workflows/deploy-pages.yml`. GitHub Pages hosts the UI only: the workflow sets a static mode that clearly reports that no API or financial data is connected. It does not ship sample metrics or run the FastAPI application.

After pushing the workflow to `main`, configure the repository's **Settings → Pages → Build and deployment → Source** to **GitHub Actions** if it is not already selected. The workflow builds the app with the repository-name base path and deploys the `web/out` artifact. The project site URL is `https://ryanconquers.github.io/FinSight-Financial-Statement-Intelligence-Performance-Analytics-Platform/` after the deployment completes.

GitHub Pages supports static hosting from a custom GitHub Actions workflow. Next.js static export creates the files in `web/out`; server features such as the FastAPI service require a separate host. See [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) and [Next.js static exports](https://nextjs.org/docs/app/guides/static-exports).

## API deployment

For a data-connected site later, deploy the API separately. The included Render definition builds with `pip install -r requirements.txt`, starts Uvicorn, and checks `/api/health`. Set `FINSIGHT_CORS_ORIGINS` to the GitHub Pages origin and set `NEXT_PUBLIC_FINSIGHT_API_URL` to the API origin before building the frontend with static mode disabled. The public environment variable is bundled into frontend JavaScript and must contain no credentials.

Render web services have an ephemeral filesystem by default. The included free service stores its empty SQLite file under `/tmp`; it can be recreated after a restart or deploy. This is acceptable only while there is no onboarded financial dataset. Render persistent disks are available to paid services and preserve files only beneath their mount path. Before onboarding real data, either upgrade and mount a persistent disk (for example `/var/data`, with `FINSIGHT_DATABASE_PATH=/var/data/finsight.sqlite3`) or migrate to managed PostgreSQL. Do not rely on the included ephemeral SQLite path for durable disclosures. See [Render web services](https://render.com/docs/web-services) and [Render disks](https://render.com/docs/disks).

The Pages site is not live until the GitHub Actions deployment has completed and its URL has been checked. The API remains unhosted until a separate backend deployment is configured.
