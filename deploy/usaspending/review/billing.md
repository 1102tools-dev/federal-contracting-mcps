# Cloudflare hosting and billing note

Confirmed September 7, 2026: the checkout reported purchase complete and Workers Paid active. Continued setup from the confirmation screen; no additional card number was entered by the agent.

- Base price: $5 per month.
- Usage exceeding included allowances is billed monthly.
- Recurring charges continue until cancellation. Checkout stated that cancellation takes effect at the end of the current billing period.
- Checkout linked the Cloudflare Terms of Service and Privacy Policy.
- Selected checkout allowances: 10 million Worker requests, 30 million CPU milliseconds, and 6,000 build minutes per month; Durable Objects include 1 million requests, 400,000 GB-seconds, and 1 GB storage. Other products have separate allowances and rates.
- The pilot is limited to one lite container and sleeps after two idle minutes. These controls limit resource use; they are not a hard dollar cap.

References:
- https://developers.cloudflare.com/containers/platform/pricing/
- https://www.cloudflare.com/terms/
- https://www.cloudflare.com/privacypolicy/

Review actual billed usage in the Cloudflare dashboard. No recurring billing-monitor automation was created.
