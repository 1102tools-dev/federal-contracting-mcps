// Set with: wrangler secret put ORIGIN_SECRET --env production (the Dell gateway's
// X-Origin-Auth value, /etc/mcp-origin/origin.env on govnode).
interface Env {
  ORIGIN_URL?: string;
  ORIGIN_SECRET?: string;
  RELEASE_SHA?: string;
}
