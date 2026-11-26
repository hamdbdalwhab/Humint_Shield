/**
 * WhatsApp (smishing) landing page — `/whatsapp-lure/:trackingUuid`.
 *
 * The tracking endpoint `/api/v1/track/whatsapp/{uuid}` writes `whatsapp_clicked`
 * and redirects here with `?page=…`, so the page is the SMS lure verbatim: the
 * same Cisco VPN / Supplier Portal / HR Portal / Teams Invite skins, the same
 * department → keyword resolution and the same evidence trail. Only the entry
 * link differs, which keeps the WhatsApp and SMS funnels directly comparable.
 */
import { SmsLureLandingPage } from '@/pages/SmsLureLandingPage';

export function WhatsAppLureLandingPage() {
  return <SmsLureLandingPage />;
}
