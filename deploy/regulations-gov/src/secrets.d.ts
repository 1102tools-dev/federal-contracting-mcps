// Set with: wrangler secret put REGULATIONS_GOV_API_KEY --name regulations-gov-mcp
// ORIGIN_SECRET: wrangler secret put ORIGIN_SECRET --env production (the Dell
// gateway's X-Origin-Auth value, /etc/mcp-origin/origin.env on govnode).
interface Env {
  REGULATIONS_GOV_API_KEY?: string;
  ORIGIN_URL?: string;
  ORIGIN_SECRET?: string;
  RELEASE_SHA?: string;
}
