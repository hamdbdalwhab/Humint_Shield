/**
 * USB drop document names.
 *
 * A dropped file must match the story the campaign tells: an "urgent password
 * change" campaign drops a password document, not a salary statement. The rules
 * mirror the backend resolver in `app/services/usb_drop_service.py` so the
 * operator preview shows exactly the file names that will be written to the
 * drive.
 */

const RULES: Array<[string[], string]> = [
  [['password', 'passwd', 'reset', 'كلمة المرور', 'كلمه المرور', 'إعادة تعيين'], 'تحديث_كلمة_المرور'],
  [['mfa', 'otp', 'verification', 'verify', 'تحقق', 'رمز'], 'رمز_التحقق_الجديد'],
  [['invoice', 'payment', 'billing', 'فاتورة', 'دفعة', 'مستحقات'], 'فاتورة_مستحقة'],
  [['bonus', 'reward', 'مكافأة', 'مكافاه'], 'مكافأة_الأداء'],
  [['salary', 'payroll', 'رواتب', 'راتب'], 'كشف_الراتب'],
  [['vpn', 'network', 'firewall', 'شبكة', 'الجدار الناري'], 'تحديث_إعدادات_الشبكة'],
  [['leave', 'policy', 'سياسة', 'إجازة', 'موارد بشرية'], 'تعميم_الموارد_البشرية'],
  [['security', 'alert', 'phish', 'أمن', 'امن', 'تنبيه'], 'تنبيه_أمني'],
  [['update', 'upgrade', 'patch', 'تحديث', 'ترقية'], 'تحديث_النظام'],
  [['covid', 'health', 'صحة'], 'تعميم_صحي'],
];

export interface UsbDocumentNames {
  html: string;
  pdf: string;
}

/** Document title implied by the campaign template, or `null` when unknown. */
export function usbDocumentTitle(
  templateName?: string | null,
  subject?: string | null,
): string | null {
  const haystack = `${templateName ?? ''} ${subject ?? ''}`.toLowerCase().trim();
  if (!haystack) return null;
  for (const [needles, title] of RULES) {
    if (needles.some((needle) => haystack.includes(needle))) return title;
  }
  return null;
}

/** File names written to the USB drive for a campaign. */
export function usbDocumentNames(
  templateName?: string | null,
  subject?: string | null,
): UsbDocumentNames {
  const title = usbDocumentTitle(templateName, subject);
  if (!title) return { html: 'الرواتب_السرية.html', pdf: 'راتب_الشهر_القادم.pdf' };
  return { html: `${title}.html`, pdf: `${title}.pdf` };
}
